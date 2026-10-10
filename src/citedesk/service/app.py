"""The HTTP service: one deployment's assistant behind a key, rate limits and a budget."""

from __future__ import annotations

import hmac
import logging
import math
import time
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field

from citedesk.assistant import Rejection
from citedesk.deployment import Deployment, DeploymentError
from citedesk.model import Model, Turn
from citedesk.service.access import Gate, TokenGate
from citedesk.service.limits import Clocks, DailyBudget, RateLimiter

logger = logging.getLogger(__name__)

# Bounds on what is parsed at all, whatever the deployment's limits: they keep a request
# small before those limits are looked at.
_MOST_TURNS = 200
_MOST_CHARS = 20_000

# What the organisation's web server adds to each request it passes on. A browser cannot be
# trusted with either, which is why the server has to set them, replacing whatever came in.
KEY_HEADER = "X-Citedesk-Key"
CLIENT_HEADER = "X-Citedesk-Client"

_key = APIKeyHeader(name=KEY_HEADER, auto_error=False)
_bearer = HTTPBearer(auto_error=False)
_Client = Annotated[str, Header(alias=CLIENT_HEADER, min_length=1, max_length=128)]
_Token = Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]


class TurnIn(BaseModel):
    """One message of the conversation, as the caller sends it."""

    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    text: str = Field(min_length=1, max_length=_MOST_CHARS)


class ReplyRequest(BaseModel):
    """A conversation that ends with the person's message.

    The service keeps no conversations: the caller sends the whole one each time.
    """

    model_config = ConfigDict(extra="forbid")

    turns: list[TurnIn] = Field(min_length=1, max_length=_MOST_TURNS)


class ReplyResponse(BaseModel):
    """What to show the person.

    A "fallback" is the deployment's fixed message; `reason` says why it was sent.
    """

    kind: Literal["answer", "hand_off", "fallback"]
    text: str
    entry_ids: list[str]
    language: str | None
    reason: Rejection | Literal["budget_spent"] | None


def create_app(
    deployment: Deployment,
    model: Model,
    *,
    key: str,
    gate: Gate | None = None,
    clocks: Clocks | None = None,
) -> FastAPI:
    """Build the service of one deployment.

    It expects to sit behind the organisation's web server, which passes requests on with
    two headers: `X-Citedesk-Key`, the secret, and `X-Citedesk-Client`, a value that tells
    one visitor from another, such as their address. When the deployment restricts access,
    the browser also sends the person's own token as a bearer token.

    Args:
        deployment: The deployment to serve. It has to state its prices.
        model: The model its assistant runs on.
        key: The secret the web server has to present.
        gate: Decides who may use the service. By default, whoever the deployment's
            `access` lists, or everyone when it has none.
        clocks: Where the rate limits and the budget read the time from. Tests replace
            them.

    Raises:
        DeploymentError: If the deployment states no prices.
        KnowledgeError: If an office entry of the deployment is not in its knowledge.
    """
    if deployment.prices is None:
        message = "The deployment states no prices, so the service cannot keep to a budget."
        raise DeploymentError(message)
    prices = deployment.prices
    limits = deployment.limits
    assistant = deployment.assistant(model)
    if gate is None and deployment.access is not None:
        gate = TokenGate(deployment.access)
    clocks = clocks or Clocks()
    per_client = RateLimiter(limits.client_requests_per_minute, clock=clocks.seconds)
    overall = RateLimiter(limits.requests_per_minute, clock=clocks.seconds)
    budget = DailyBudget(limits.daily_budget_usd, today=clocks.today)

    def authorised(presented: Annotated[str | None, Depends(_key)]) -> None:
        if not hmac.compare_digest((presented or "").encode(), key.encode()):
            raise HTTPException(401, _problem("wrong_key"))

    # The service is called by the organisation's own web server, never by a browser, so it
    # does not publish its interface.
    app = FastAPI(title="citedesk", docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/healthz")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/replies", dependencies=[Depends(authorised)])
    async def reply(request: ReplyRequest, client: _Client, token: _Token) -> ReplyResponse:
        turns = _conversation(request, limits.turns, limits.message_chars)
        # The client's own allowance comes first, before anything that costs: checking a
        # token may fetch the provider's keys, and a reply calls the model.
        wait = per_client.wait(client)
        if wait:
            raise _too_many_requests(wait)
        if gate is not None:
            refusal = await gate.refusal(token.credentials if token else None)
            if refusal == "sign_in_required":
                raise HTTPException(401, _problem(refusal), {"WWW-Authenticate": "Bearer"})
            if refusal:
                raise HTTPException(403, _problem(refusal))
        wait = overall.wait("")
        if wait:
            raise _too_many_requests(wait)
        if budget.exhausted:
            logger.warning("reply kind=fallback reason=budget_spent")
            return ReplyResponse(
                kind="fallback",
                text=deployment.fallback,
                entry_ids=[],
                language=None,
                reason="budget_spent",
            )

        started = time.perf_counter()
        sent = await assistant.reply(turns)
        cost = prices.cost(sent.usage)
        budget.spend(cost)
        # No message text and no client in the log: what people write stays out of it.
        logger.info(
            "reply kind=%s reason=%s usd=%.6f spent_today=%.4f ms=%d",
            sent.kind,
            sent.rejection,
            cost,
            budget.spent,
            (time.perf_counter() - started) * 1000,
        )
        return ReplyResponse(
            kind=sent.kind,
            text=sent.text,
            entry_ids=list(sent.entry_ids),
            language=sent.language,
            reason=sent.rejection,
        )

    return app


def _conversation(request: ReplyRequest, most_turns: int, most_chars: int) -> list[Turn]:
    """Check a conversation against the deployment's limits and hand it to the assistant.

    Raises:
        HTTPException: With status 422 and a `code` when the conversation is not one the
            assistant can reply to, or goes over a limit.
    """
    turns = request.turns
    expected = ("user", "assistant")
    if turns[-1].role != "user" or any(
        turn.role != expected[index % 2] for index, turn in enumerate(turns)
    ):
        raise HTTPException(422, _problem("turns_out_of_order"))
    if len(turns) > most_turns:
        raise HTTPException(422, _problem("conversation_too_long"))
    if any(turn.role == "user" and len(turn.text) > most_chars for turn in turns):
        raise HTTPException(422, _problem("message_too_long"))
    return [Turn(turn.role, turn.text) for turn in turns]


def _too_many_requests(wait: float) -> HTTPException:
    """Tell the caller how many seconds to wait before asking again."""
    return HTTPException(429, _problem("too_many_requests"), {"Retry-After": str(math.ceil(wait))})


def _problem(code: str) -> dict[str, str]:
    """Shape the detail of an error so that the caller can act on its code."""
    return {"code": code}

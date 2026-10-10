"""The HTTP service: one deployment's assistant behind a key, rate limits and a budget."""

from __future__ import annotations

import hmac
import logging
import math
import time
from typing import TYPE_CHECKING, Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field

from citedesk.assistant import Rejection
from citedesk.deployment import Deployment, DeploymentError
from citedesk.model import Model, Turn
from citedesk.service.limits import DailyBudget, RateLimiter, utc_today

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import date

logger = logging.getLogger(__name__)

# Bounds on what is parsed at all, whatever the deployment's limits: they keep a request
# small before those limits are looked at.
_MOST_TURNS = 200
_MOST_CHARS = 20_000

_bearer = HTTPBearer(auto_error=False)


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

    client: str = Field(
        min_length=1,
        max_length=128,
        description="Who is asking, as an opaque value. Requests are rate-limited by it.",
    )
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
    clock: Callable[[], float] = time.monotonic,
    today: Callable[[], date] = utc_today,
) -> FastAPI:
    """Build the service of one deployment.

    Args:
        deployment: The deployment to serve. It has to state its prices.
        model: The model its assistant runs on.
        key: The secret a caller has to present as a bearer token.
        clock: Returns the time in seconds, for the rate limits. Tests replace it.
        today: Returns the current day, for the budget. Tests replace it.

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
    per_client = RateLimiter(limits.client_requests_per_minute, clock=clock)
    overall = RateLimiter(limits.requests_per_minute, clock=clock)
    budget = DailyBudget(limits.daily_budget_usd, today=today)

    def authorised(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    ) -> None:
        presented = credentials.credentials if credentials else ""
        if not hmac.compare_digest(presented.encode(), key.encode()):
            raise HTTPException(401, "Missing or wrong key.", {"WWW-Authenticate": "Bearer"})

    # The service is called by the organisation's own web server, never by a browser, so it
    # does not publish its interface.
    app = FastAPI(title="citedesk", docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/healthz")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/replies", dependencies=[Depends(authorised)])
    async def reply(request: ReplyRequest) -> ReplyResponse:
        turns = _conversation(request, limits.turns, limits.message_chars)
        # The client's own allowance is checked first, so that one client asking too often
        # does not use up the allowance everyone shares.
        wait = per_client.wait(request.client) or overall.wait("")
        if wait:
            retry_after = {"Retry-After": str(math.ceil(wait))}
            raise HTTPException(429, _problem("too_many_requests"), retry_after)
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


def _problem(code: str) -> dict[str, str]:
    """Shape the detail of an error so that the caller can act on its code."""
    return {"code": code}

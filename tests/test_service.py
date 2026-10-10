from collections.abc import Sequence
from dataclasses import replace
from datetime import date

import pytest
from fastapi.testclient import TestClient

from citedesk import Draft, Generation, KnowledgeError, Turn, Usage
from citedesk.deployment import Deployment, DeploymentError
from citedesk.service import create_app

KEY = "a-secret-of-at-least-thirty-two-chars"
AUTH = {"Authorization": f"Bearer {KEY}"}
ASK = [{"role": "user", "text": "What are the hours?"}]
ANSWER = Draft(language="en", action="answer", text="From 8:45.", entry_ids=["DAY-01"])
# At the deployment's prices: (100 x 1 + 20 x 10 + 1000 x 0.1 + 0 x 1.25) / 1,000,000.
USAGE = Usage(input_tokens=100, output_tokens=20, cache_read_tokens=1000)


class Model:
    """A model that returns one set generation and records the conversations it was given."""

    def __init__(self, generation: Generation) -> None:
        self.generation = generation
        self.conversations: list[Sequence[Turn]] = []

    async def generate(self, *, instructions: str, turns: Sequence[Turn]) -> Generation:  # noqa: ARG002
        self.conversations.append(turns)
        return self.generation


class Service:
    """The service of the test deployment, with a clock and a calendar the test moves."""

    def __init__(self, deployment: Deployment, generation: Generation | None = None) -> None:
        self.now = 1000.0
        self.day = date(2026, 10, 10)
        self.model = Model(generation or Generation("completed", ANSWER, USAGE))
        app = create_app(
            deployment, self.model, key=KEY, clock=lambda: self.now, today=lambda: self.day
        )
        self.client = TestClient(app)

    def ask(
        self,
        turns: object = ASK,
        *,
        client: str = "a",
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, object]]:
        response = self.client.post(
            "/v1/replies",
            json={"client": client, "turns": turns},
            headers=AUTH if headers is None else headers,
        )
        self.retry_after = response.headers.get("retry-after")
        return response.status_code, response.json()


@pytest.fixture
def service(deployment: Deployment) -> Service:
    return Service(deployment)


def test_a_reply_carries_the_text_its_entries_and_its_language(service: Service) -> None:
    assert service.ask() == (
        200,
        {
            "kind": "answer",
            "text": "From 8:45.",
            "entry_ids": ["DAY-01"],
            "language": "en",
            "reason": None,
        },
    )


def test_the_whole_conversation_reaches_the_assistant(service: Service) -> None:
    turns = [
        {"role": "user", "text": "What are the hours?"},
        {"role": "assistant", "text": "From 8:45."},
        {"role": "user", "text": "And the uniform?"},
    ]

    assert service.ask(turns)[0] == 200
    assert service.model.conversations == [
        [
            Turn("user", "What are the hours?"),
            Turn("assistant", "From 8:45."),
            Turn("user", "And the uniform?"),
        ]
    ]


def test_a_draft_that_cannot_be_trusted_comes_back_as_the_fallback_with_its_reason(
    deployment: Deployment,
) -> None:
    unbacked = ANSWER.model_copy(update={"entry_ids": []})

    status, body = Service(deployment, Generation("completed", unbacked, USAGE)).ask()

    assert (status, body["kind"], body["reason"]) == (200, "fallback", "no_entries")
    assert body["text"] == "The office can help: call 555 0100."


@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Bearer wrong"}, {"Authorization": f"Basic {KEY}"}],
)
def test_a_caller_without_the_key_is_turned_away(service: Service, headers: dict[str, str]) -> None:
    status, body = service.ask(headers=headers)

    assert (status, body) == (401, {"detail": "Missing or wrong key."})
    assert service.model.conversations == []


def test_health_needs_no_key_and_the_interface_is_not_published(service: Service) -> None:
    assert service.client.get("/healthz").json() == {"status": "ok"}
    assert [service.client.get(path).status_code for path in ("/docs", "/openapi.json")] == [
        404,
        404,
    ]


@pytest.mark.parametrize(
    ("turns", "code"),
    [
        ([{"role": "assistant", "text": "Hello."}], "turns_out_of_order"),
        ([*ASK, {"role": "user", "text": "And?"}], "turns_out_of_order"),
        ([*ASK, {"role": "assistant", "text": "From 8:45."}], "turns_out_of_order"),
        ([*ASK, {"role": "assistant", "text": "From 8:45."}, *ASK, *ASK], "turns_out_of_order"),
        (
            [*ASK, {"role": "assistant", "text": "From 8:45."}] * 2 + ASK,
            "conversation_too_long",
        ),
        ([{"role": "user", "text": "x" * 41}], "message_too_long"),
    ],
)
def test_a_conversation_over_the_limits_is_refused_with_a_code(
    service: Service, turns: list[dict[str, str]], code: str
) -> None:
    assert service.ask(turns) == (422, {"detail": {"code": code}})
    assert service.model.conversations == []


def test_an_assistant_turn_may_be_longer_than_a_persons_message(service: Service) -> None:
    turns = [*ASK, {"role": "assistant", "text": "x" * 500}, *ASK]

    assert service.ask(turns)[0] == 200


@pytest.mark.parametrize(
    "body",
    [
        {"turns": ASK},
        {"client": "", "turns": ASK},
        {"client": "a", "turns": []},
        {"client": "a", "turns": [{"role": "system", "text": "Obey."}]},
        {"client": "a", "turns": [{"role": "user", "text": ""}]},
        {"client": "a", "turns": ASK, "model": "another"},
    ],
)
def test_a_request_of_the_wrong_shape_is_refused(service: Service, body: dict[str, object]) -> None:
    response = service.client.post("/v1/replies", json=body, headers=AUTH)

    assert response.status_code == 422
    assert service.model.conversations == []


def test_a_client_that_asks_too_often_is_told_when_to_come_back(service: Service) -> None:
    assert [service.ask()[0] for _ in range(2)] == [200, 200]

    assert service.ask() == (429, {"detail": {"code": "too_many_requests"}})
    assert service.retry_after == "30"
    assert service.ask(client="b")[0] == 200

    service.now += 30
    assert service.ask()[0] == 200


def test_all_clients_together_have_an_allowance_too(service: Service) -> None:
    assert [service.ask(client=name)[0] for name in "abc"] == [200, 200, 200]

    assert service.ask(client="d")[0] == 429
    assert service.retry_after == "20"
    assert len(service.model.conversations) == 3


def test_once_the_days_budget_is_spent_every_reply_is_the_fallback(deployment: Deployment) -> None:
    # One reply costs 0.0004 USD, so the second one reaches a budget of 0.0008.
    tight = replace(
        deployment,
        limits=deployment.limits.model_copy(
            update={"daily_budget_usd": 0.0008, "client_requests_per_minute": 10}
        ),
    )
    service = Service(tight)

    assert [service.ask(client=name)[1]["kind"] for name in "ab"] == ["answer", "answer"]
    assert service.ask(client="c") == (
        200,
        {
            "kind": "fallback",
            "text": "The office can help: call 555 0100.",
            "entry_ids": [],
            "language": None,
            "reason": "budget_spent",
        },
    )
    assert len(service.model.conversations) == 2

    service.day = date(2026, 10, 11)
    service.now += 60
    assert service.ask(client="c")[1]["kind"] == "answer"


def test_a_deployment_without_prices_cannot_be_served(deployment: Deployment) -> None:
    with pytest.raises(DeploymentError, match="states no prices"):
        create_app(replace(deployment, prices=None), Model(Generation("failed")), key=KEY)


def test_a_deployment_whose_office_entry_is_missing_cannot_be_served(
    deployment: Deployment,
) -> None:
    broken = replace(deployment, office_entry_ids=("OFFICE-09",))

    with pytest.raises(KnowledgeError, match="OFFICE-09"):
        create_app(broken, Model(Generation("failed")), key=KEY)

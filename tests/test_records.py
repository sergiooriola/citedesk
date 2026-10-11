import asyncio
import json

import httpx2
import pytest

from citedesk.deployment import Records
from citedesk.service import Exchange, HttpRecorder

EXCHANGE = Exchange(
    at="2026-10-11T08:00:00+00:00",
    conversation="k3_Zp-9",
    turn=2,
    asked="And the uniform?",
    replied="A navy jumper.",
    kind="answer",
    entry_ids=("DAY-02",),
    reason=None,
    language="en",
    usd=0.000412,
    ms=1830,
)
URL = "https://records.example/exchanges"


class Receiver:
    """Stands in for where the records go: answers a set status and keeps what it was sent."""

    def __init__(self, status: int = 201, error: Exception | None = None) -> None:
        self.status = status
        self.error = error
        self.requests: list[httpx2.Request] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        if self.error:
            raise self.error
        return httpx2.Response(self.status)


def record(records: Records, receiver: Receiver, key: str | None = None) -> httpx2.Request:
    recorder = HttpRecorder(records, key=key, transport=httpx2.MockTransport(receiver))
    asyncio.run(recorder.record(EXCHANGE))
    (request,) = receiver.requests
    return request


def test_an_exchange_is_posted_as_one_json_object() -> None:
    request = record(Records(url=URL), Receiver())

    assert (request.method, str(request.url)) == ("POST", URL)
    assert json.loads(request.content) == {
        "at": "2026-10-11T08:00:00+00:00",
        "conversation": "k3_Zp-9",
        "turn": 2,
        "asked": "And the uniform?",
        "replied": "A navy jumper.",
        "kind": "answer",
        "entry_ids": ["DAY-02"],
        "reason": None,
        "language": "en",
        "usd": 0.000412,
        "ms": 1830,
    }


def test_fields_travel_under_the_names_the_receiver_has() -> None:
    records = Records(url=URL, fields={"asked": "question", "entry_ids": "entries"})

    body = json.loads(record(records, Receiver()).content)

    assert (body["question"], body["entries"]) == ("And the uniform?", ["DAY-02"])
    assert "asked" not in body
    assert "entry_ids" not in body
    assert body["replied"] == "A navy jumper."


def test_the_receivers_headers_and_its_secret_go_with_every_record() -> None:
    records = Records(url=URL, headers={"apikey": "a-public-key"}, key_header="X-Records-Key")

    request = record(records, Receiver(), key="a-secret")

    assert request.headers["apikey"] == "a-public-key"
    assert request.headers["X-Records-Key"] == "a-secret"


def test_without_a_key_header_no_secret_is_sent() -> None:
    request = record(Records(url=URL), Receiver(), key="a-secret")

    assert "a-secret" not in request.headers.values()


@pytest.mark.parametrize(
    ("receiver", "logged"),
    [
        (Receiver(status=403), "records: the receiver answered 403"),
        (Receiver(error=httpx2.ConnectError("down")), "records: not delivered (ConnectError)"),
        (Receiver(error=httpx2.ReadTimeout("slow")), "records: not delivered (ReadTimeout)"),
    ],
)
def test_a_record_that_is_not_taken_is_logged_and_never_raises(
    receiver: Receiver, logged: str, caplog: pytest.LogCaptureFixture
) -> None:
    record(Records(url=URL), receiver)

    assert logged in caplog.text
    # What people wrote stays out of the log.
    assert "uniform" not in caplog.text

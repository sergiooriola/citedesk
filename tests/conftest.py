from collections.abc import Sequence

import pytest

from citedesk import Entry, Generation, Knowledge, Turn
from citedesk.deployment import Deployment, Limits, Prices
from citedesk.exam import Judging


class ScriptedModel:
    """A model that returns what the test tells it to and records what it was asked."""

    def __init__(self, generation: Generation) -> None:
        self.generation = generation
        self.instructions = ""
        self.turns: Sequence[Turn] = ()

    async def generate(self, *, instructions: str, turns: Sequence[Turn]) -> Generation:
        self.instructions = instructions
        self.turns = turns
        return self.generation


@pytest.fixture
def knowledge() -> Knowledge:
    return Knowledge(
        [
            Entry(id="DAY-01", question="What are the hours?", answer="From 8:45 to 15:30."),
            Entry(id="DAY-02", question="Is there a uniform?", answer="Yes, a navy jumper."),
            Entry(id="OFFICE-01", question="How do I reach the office?", answer="Call 555 0100."),
        ]
    )


class ScriptedJudge:
    """A judge that returns what the test tells it to and records what it was asked.

    Given several judgings, it returns them in turn and then keeps to the last one.
    """

    def __init__(self, *judgings: Judging) -> None:
        self.judgings = list(judgings)
        self.instructions = ""
        self.exchanges: list[str] = []

    async def judge(self, *, instructions: str, exchange: str) -> Judging:
        self.instructions = instructions
        self.exchanges.append(exchange)
        return self.judgings.pop(0) if len(self.judgings) > 1 else self.judgings[0]


@pytest.fixture
def deployment(knowledge: Knowledge) -> Deployment:
    return Deployment(
        knowledge,
        office_entry_ids=("OFFICE-01",),
        fallback="The office can help: call 555 0100.",
        rules=("Fees are reserved for the office.",),
        limits=Limits(
            message_chars=40, turns=3, client_requests_per_minute=2, requests_per_minute=3
        ),
        prices=Prices(input=1.0, output=10.0, cache_read=0.1, cache_write=1.25),
    )

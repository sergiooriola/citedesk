from collections.abc import Sequence

import pytest

from citedesk import Entry, Generation, Knowledge, Turn


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

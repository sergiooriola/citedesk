"""The cases of an exam: what a person may write and what the assistant has to do with it."""

from __future__ import annotations

import json
from collections import Counter
from typing import TYPE_CHECKING, Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

if TYPE_CHECKING:
    from pathlib import Path

    from citedesk.knowledge import Knowledge

_Text = Annotated[str, Field(min_length=1)]


class ExamError(ValueError):
    """The cases file cannot be used as it is."""


class Case(BaseModel):
    """One message and the behaviour expected in reply.

    Attributes:
        id: The identifier of the case.
        ask: What the person writes.
        expect: "answer" when the entries answer it, "hand_off" when it is for the office,
            "any" when either is right and only the content of the reply matters.
        entry_ids: For an answer, the entries that answer it: citing any one of them is
            enough, and a hand-off that cites one is accepted too. Empty when any entry
            will do.
        never: Phrases that must not appear in the reply, whatever it does. They are looked
            for as whole words and without regard to case, so they have to be phrases only
            a wrong reply contains: "I cannot guarantee a place" is a right reply.
        language: The language the reply has to be in, as an ISO 639-1 code. Not checked
            when absent.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    id: _Text
    ask: _Text
    expect: Literal["answer", "hand_off", "any"]
    entry_ids: tuple[_Text, ...] = ()
    never: tuple[_Text, ...] = ()
    language: _Text | None = None


def load_cases(path: Path, knowledge: Knowledge) -> list[Case]:
    """Read the cases of an exam from a file with one JSON object per line.

    Args:
        path: The cases file.
        knowledge: The entries the cases refer to.

    Raises:
        ExamError: If a line is not a valid case, there are no cases, two share an
            identifier, a case names an entry the knowledge does not have, or a case that
            does not expect an answer names entries.
    """
    cases: list[Case] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            cases.append(Case.model_validate(json.loads(line)))
        except (json.JSONDecodeError, ValidationError) as error:
            message = f"{path.name}, line {number}: not a valid case."
            raise ExamError(message) from error
    problem = _problem(cases, knowledge)
    if problem:
        message = f"{path.name}: {problem}"
        raise ExamError(message)
    return cases


def _problem(cases: list[Case], knowledge: Knowledge) -> str | None:
    """Say what is wrong with the cases as a whole, or None when nothing is."""
    if not cases:
        return "it has no cases."
    counts = Counter(case.id for case in cases)
    repeated = sorted(case_id for case_id, count in counts.items() if count > 1)
    if repeated:
        return f"repeated case identifiers: {', '.join(repeated)}."
    for case in cases:
        unknown = [entry_id for entry_id in case.entry_ids if entry_id not in knowledge]
        if unknown:
            return f"{case.id} names entries the knowledge does not have: {', '.join(unknown)}."
        if case.expect != "answer" and case.entry_ids:
            return f"{case.id} does not expect an answer, so it names no entries."
    return None

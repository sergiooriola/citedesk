"""Grading: what a reply got wrong, given the case it replied to."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Literal, get_args

if TYPE_CHECKING:
    from citedesk.assistant import Reply
    from citedesk.exam.cases import Case
    from citedesk.exam.judge import Claim, Judgement
    from citedesk.knowledge import Knowledge

Failure = Literal[
    "forbidden_text",
    "unsupported_claim",
    "answered",
    "handed_off",
    "fell_back",
    "wrong_entries",
    "uncited_claim",
    "wrong_language",
]

# What must never reach a person: text the case forbids and facts no entry states. One of
# these fails the exam whatever the pass rate; the other failures only count against it.
CRITICAL: frozenset[Failure] = frozenset({"forbidden_text", "unsupported_claim"})

_BY_SEVERITY: tuple[Failure, ...] = get_args(Failure)


def grade(
    case: Case, reply: Reply, judgement: Judgement | None, knowledge: Knowledge
) -> tuple[Failure, ...]:
    """List what a reply got wrong, the most serious first. Empty when it passes.

    The rules a program can apply are applied here: the kind of reply, the entries it
    cites and the text it must not contain. The judge supplies the rest: which claims the
    reply makes, which entries state each one and the language it is written in.

    Args:
        case: The case the assistant replied to.
        reply: What the assistant sent.
        judgement: The judge's reading of the reply. None for a fallback, which is the
            deployment's own fixed text and has nothing to judge.
        knowledge: The deployment's entries.
    """
    found: set[Failure] = set()
    if any(_appears(phrase, reply.text) for phrase in case.never):
        found.add("forbidden_text")

    cites_expected = not set(case.entry_ids).isdisjoint(reply.entry_ids)
    if reply.kind == "fallback":
        found.add("fell_back")
    elif case.expect == "hand_off" and reply.kind == "answer":
        found.add("answered")
    elif case.expect == "answer" and reply.kind == "hand_off" and not cites_expected:
        # A hand-off that cites an expected entry gave the information and sent the person
        # on to the office as well: more cautious than needed, not wrong.
        found.add("handed_off")
    elif case.expect == "answer" and case.entry_ids and not cites_expected:
        found.add("wrong_entries")

    if judgement is not None:
        for claim in judgement.claims:
            stated_by = {entry_id for entry_id in claim.entry_ids if entry_id in knowledge}
            if stated_by and stated_by.isdisjoint(reply.entry_ids):
                found.add("uncited_claim")
        if unsupported_claims(judgement, knowledge):
            found.add("unsupported_claim")
        if case.language and judgement.language.strip().casefold() != case.language.casefold():
            found.add("wrong_language")

    return tuple(failure for failure in _BY_SEVERITY if failure in found)


def unsupported_claims(judgement: Judgement, knowledge: Knowledge) -> list[Claim]:
    """Pick the claims no entry states. An entry the judge made up states nothing."""
    return [
        claim
        for claim in judgement.claims
        if not any(entry_id in knowledge for entry_id in claim.entry_ids)
    ]


def _appears(phrase: str, text: str) -> bool:
    """Say whether a phrase appears in a text as whole words, whatever its case.

    "85" does not appear in a telephone number that contains 859, nor "MIT" in "permit". A
    phrase that starts or ends with a symbol, such as a currency sign, matches wherever the
    symbol is.
    """
    pattern = re.escape(phrase)
    if phrase[0].isalnum():
        pattern = rf"(?<!\w){pattern}"
    if phrase[-1].isalnum():
        pattern = rf"{pattern}(?!\w)"
    return re.search(pattern, text, re.IGNORECASE) is not None

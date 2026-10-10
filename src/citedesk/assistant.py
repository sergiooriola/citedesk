"""The assistant: asks the model for a draft and sends it only if its citations hold."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from citedesk.instructions import build_instructions
from citedesk.knowledge import KnowledgeError
from citedesk.model import Usage

if TYPE_CHECKING:
    from collections.abc import Sequence

    from citedesk.knowledge import Knowledge
    from citedesk.model import Draft, Generation, Model, Turn

Rejection = Literal[
    "model_refused",
    "model_truncated",
    "model_failed",
    "no_text",
    "no_entries",
    "unknown_entry",
    "no_office_entry",
]


@dataclass(frozen=True)
class Reply:
    """What the person receives.

    A "fallback" is the deployment's fixed message: it is sent whenever the model's draft
    cannot be trusted, and `rejection` says why. `language` is the language the model read
    the person's message in, absent for a fallback.
    """

    kind: Literal["answer", "hand_off", "fallback"]
    text: str
    entry_ids: tuple[str, ...] = ()
    rejection: Rejection | None = None
    usage: Usage = field(default_factory=Usage)
    language: str | None = None


class Assistant:
    """Answers from a deployment's entries, or hands the person to the office."""

    def __init__(
        self,
        *,
        model: Model,
        knowledge: Knowledge,
        office_entry_ids: Sequence[str],
        fallback: str,
        rules: Sequence[str] = (),
    ) -> None:
        """Set up the assistant of one deployment.

        Args:
            model: The language model that writes the drafts.
            knowledge: The entries the assistant answers from.
            office_entry_ids: The entries that say how to reach a person. A hand-off has to
                cite at least one of them.
            fallback: The message sent when a draft is rejected. It is the only text the
                assistant sends that the model did not write, so it should say how to reach
                the office.
            rules: The deployment's own rules of behaviour.

        Raises:
            KnowledgeError: If an office entry is not in the knowledge, or there is none.
        """
        missing = [entry_id for entry_id in office_entry_ids if entry_id not in knowledge]
        if missing or not office_entry_ids:
            message = f"Office entries not in the knowledge: {', '.join(missing) or 'none given'}."
            raise KnowledgeError(message)
        self._model = model
        self._knowledge = knowledge
        self._office = frozenset(office_entry_ids)
        self._fallback = fallback
        self._instructions = build_instructions(
            knowledge, office_entry_ids=office_entry_ids, rules=rules
        )

    async def reply(self, turns: Sequence[Turn]) -> Reply:
        """Reply to the last message of a conversation.

        Args:
            turns: The conversation so far, ending with the person's message.
        """
        generation = await self._model.generate(instructions=self._instructions, turns=turns)
        rejection = self._check(generation)
        if rejection is not None or generation.draft is None:
            return Reply("fallback", self._fallback, rejection=rejection, usage=generation.usage)
        draft = generation.draft
        return Reply(
            draft.action,
            draft.text.strip(),
            tuple(draft.entry_ids),
            usage=generation.usage,
            language=draft.language.strip().lower(),
        )

    def _check(self, generation: Generation) -> Rejection | None:
        """Say why a generation cannot be sent, or None when it can."""
        if generation.outcome == "refused":
            return "model_refused"
        if generation.outcome == "truncated":
            return "model_truncated"
        if generation.outcome == "failed" or generation.draft is None:
            return "model_failed"
        return self._check_draft(generation.draft)

    def _check_draft(self, draft: Draft) -> Rejection | None:
        """Say why a draft cannot be sent, or None when its citations hold."""
        if not draft.text.strip():
            return "no_text"
        if not draft.entry_ids:
            return "no_entries"
        if any(entry_id not in self._knowledge for entry_id in draft.entry_ids):
            return "unknown_entry"
        if draft.action == "hand_off" and self._office.isdisjoint(draft.entry_ids):
            return "no_office_entry"
        return None

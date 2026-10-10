"""What the assistant needs from a language model, whoever provides it."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, Protocol

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from collections.abc import Sequence


@dataclass(frozen=True)
class Turn:
    """One message of a conversation, from the person or from the assistant."""

    role: Literal["user", "assistant"]
    text: str


class Draft(BaseModel):
    """What the model has to return: its text and the entries that back it.

    The model is constrained to this shape, so the assistant can check the citations before
    anything reaches the person.
    """

    model_config = ConfigDict(extra="forbid")

    action: Literal["answer", "hand_off"]
    text: str
    entry_ids: list[str]


@dataclass(frozen=True)
class Usage:
    """Tokens one model call consumed, as the provider bills them."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


Outcome = Literal["completed", "refused", "truncated", "failed"]


@dataclass(frozen=True)
class Generation:
    """The result of one model call.

    `draft` is present only when `outcome` is "completed".
    """

    outcome: Outcome
    draft: Draft | None = None
    usage: Usage = field(default_factory=Usage)


class Model(Protocol):
    """A language model that can be asked for a draft."""

    async def generate(self, *, instructions: str, turns: Sequence[Turn]) -> Generation:
        """Ask for a draft, given the fixed instructions and the conversation so far."""
        ...

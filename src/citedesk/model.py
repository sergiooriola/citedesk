"""What the assistant needs from a language model, whoever provides it."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

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
    anything reaches the person. It fills the fields in this order. The language comes
    first so that the model has settled on it by the time it writes; the entries come last
    so that it lists what the finished text draws on, incidental remarks included.
    """

    model_config = ConfigDict(extra="forbid")

    language: str = Field(
        description="The language of the person's last message, as an ISO 639-1 code."
    )
    action: Literal["answer", "hand_off"]
    text: str = Field(description="The reply, written in that language.")
    entry_ids: list[str] = Field(
        description="The identifier of every entry the text draws on, however briefly."
    )


@dataclass(frozen=True)
class Usage:
    """Tokens one model call consumed, as the provider bills them."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    def __add__(self, other: Usage) -> Usage:
        """Add up what two calls consumed."""
        return Usage(
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
            self.cache_read_tokens + other.cache_read_tokens,
            self.cache_write_tokens + other.cache_write_tokens,
        )


Outcome = Literal["completed", "refused", "truncated", "failed"]

# How much a model reasons before it replies. Reasoning is billed as output.
Effort = Literal["low", "medium", "high", "xhigh", "max"]


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

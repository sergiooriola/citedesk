"""One deployment: its entries, how to reach the office and its rules of behaviour."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from citedesk.assistant import Assistant
from citedesk.knowledge import Knowledge
from citedesk.model import Effort, Usage

if TYPE_CHECKING:
    from pathlib import Path

    from citedesk.model import Model


class DeploymentError(ValueError):
    """The deployment file cannot be used as it is."""


class Limits(BaseModel):
    """What one deployment's service accepts, so that abuse cannot run up a bill.

    Attributes:
        message_chars: The longest message a person may send.
        turns: The most messages a conversation may have, the assistant's included.
        client_requests_per_minute: How many replies one client may ask for in a minute.
        requests_per_minute: How many replies all clients together may ask for in a minute.
        daily_budget_usd: What the model may cost in one day. Once it is spent, every
            reply is the fallback until the next day.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    message_chars: int = Field(default=600, gt=0)
    turns: int = Field(default=20, gt=0)
    client_requests_per_minute: int = Field(default=6, gt=0)
    requests_per_minute: int = Field(default=60, gt=0)
    daily_budget_usd: float = Field(default=1.0, gt=0)


class Prices(BaseModel):
    """What the deployment's model costs, in US dollars per million tokens."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    input: float = Field(ge=0)
    output: float = Field(ge=0)
    cache_read: float = Field(ge=0)
    cache_write: float = Field(ge=0)

    def cost(self, usage: Usage) -> float:
        """Work out what one model call cost, in US dollars."""
        return (
            usage.input_tokens * self.input
            + usage.output_tokens * self.output
            + usage.cache_read_tokens * self.cache_read
            + usage.cache_write_tokens * self.cache_write
        ) / 1_000_000


class _File(BaseModel):
    """The deployment file as it is written."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    knowledge: str = Field(min_length=1)
    office_entry_ids: tuple[str, ...] = Field(min_length=1)
    fallback: str = Field(min_length=1)
    rules: tuple[str, ...] = ()
    model: str = Field(default="claude-haiku-5-5", min_length=1)
    effort: Effort = "low"
    limits: Limits = Limits()
    prices: Prices | None = None


@dataclass(frozen=True)
class Deployment:
    """What makes an assistant the assistant of one organisation.

    The exam and the service read the same file, so what is examined is what is served.
    """

    knowledge: Knowledge
    office_entry_ids: tuple[str, ...]
    fallback: str
    rules: tuple[str, ...] = ()
    model: str = "claude-haiku-5-5"
    effort: Effort = "low"
    limits: Limits = field(default_factory=Limits)
    prices: Prices | None = None

    @classmethod
    def from_file(cls, path: Path) -> Deployment:
        """Read a deployment from a JSON file.

        The file has `knowledge` (the path of the entries file, relative to this one),
        `office_entry_ids`, `fallback` and, optionally, `rules`, `model`, `effort`, `limits`
        and `prices`. The service needs the prices: without them it cannot keep to a budget.

        Raises:
            DeploymentError: If the file is not a valid deployment.
            KnowledgeError: If the entries file cannot be used.
        """
        try:
            file = _File.model_validate_json(path.read_text(encoding="utf-8"))
        except ValidationError as error:
            message = f"{path.name}: not a valid deployment."
            raise DeploymentError(message) from error
        return cls(
            Knowledge.from_jsonl(path.parent / file.knowledge),
            file.office_entry_ids,
            file.fallback,
            file.rules,
            file.model,
            file.effort,
            file.limits,
            file.prices,
        )

    def assistant(self, model: Model) -> Assistant:
        """Build this deployment's assistant on top of a model.

        Raises:
            KnowledgeError: If an office entry is not in the knowledge.
        """
        return Assistant(
            model=model,
            knowledge=self.knowledge,
            office_entry_ids=self.office_entry_ids,
            fallback=self.fallback,
            rules=self.rules,
        )

"""One deployment: its entries, how to reach the office and its rules of behaviour."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from citedesk.assistant import Assistant
from citedesk.knowledge import Knowledge
from citedesk.model import Effort

if TYPE_CHECKING:
    from pathlib import Path

    from citedesk.model import Model


class DeploymentError(ValueError):
    """The deployment file cannot be used as it is."""


class _File(BaseModel):
    """The deployment file as it is written."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    knowledge: str = Field(min_length=1)
    office_entry_ids: tuple[str, ...] = Field(min_length=1)
    fallback: str = Field(min_length=1)
    rules: tuple[str, ...] = ()
    model: str = Field(default="claude-haiku-5-5", min_length=1)
    effort: Effort = "low"


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

    @classmethod
    def from_file(cls, path: Path) -> Deployment:
        """Read a deployment from a JSON file.

        The file has `knowledge` (the path of the entries file, relative to this one),
        `office_entry_ids`, `fallback` and, optionally, `rules`, `model` and `effort`.

        Raises:
            DeploymentError: If the file is not a valid deployment.
            KnowledgeError: If the entries file cannot be used.
        """
        try:
            file = _File.model_validate_json(path.read_text(encoding="utf-8"))
        except ValidationError as error:
            message = f"{path.name}: not a valid deployment."
            raise DeploymentError(message) from error
        knowledge = Knowledge.from_jsonl(path.parent / file.knowledge)
        return cls(
            knowledge, file.office_entry_ids, file.fallback, file.rules, file.model, file.effort
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

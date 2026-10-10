"""The reviewed entries an assistant may answer from."""

from __future__ import annotations

import json
from collections import Counter
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field, ValidationError

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


class KnowledgeError(ValueError):
    """The knowledge file cannot be used as it is."""


class Entry(BaseModel):
    """One reviewed question and its answer."""

    model_config = ConfigDict(frozen=True, extra="ignore", str_strip_whitespace=True)

    id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    answer: str = Field(min_length=1)


class Knowledge:
    """The entries of one deployment, in the order they were written."""

    def __init__(self, entries: list[Entry]) -> None:
        """Keep the entries, refusing an empty list and repeated identifiers.

        Raises:
            KnowledgeError: If there are no entries or two share an identifier.
        """
        if not entries:
            message = "The knowledge has no entries."
            raise KnowledgeError(message)
        self._entries = {entry.id: entry for entry in entries}
        if len(self._entries) != len(entries):
            counts = Counter(entry.id for entry in entries)
            repeated = sorted(entry_id for entry_id, count in counts.items() if count > 1)
            message = f"Repeated entry identifiers: {', '.join(repeated)}."
            raise KnowledgeError(message)

    @classmethod
    def from_jsonl(cls, path: Path) -> Knowledge:
        """Read entries from a file with one JSON object per line.

        Each object needs `id`, `question` and `answer`; other fields are ignored, so a file
        exported with review metadata can be used as it is.

        Raises:
            KnowledgeError: If a line is not a valid entry, or the entries cannot be used.
        """
        entries: list[Entry] = []
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                entries.append(Entry.model_validate(json.loads(line)))
            except (json.JSONDecodeError, ValidationError) as error:
                message = f"{path.name}, line {number}: not a valid entry."
                raise KnowledgeError(message) from error
        return cls(entries)

    def __contains__(self, entry_id: object) -> bool:
        """Say whether an identifier belongs to an entry."""
        return entry_id in self._entries

    def __iter__(self) -> Iterator[Entry]:
        """Go through the entries in the order they were written."""
        return iter(self._entries.values())

    def __len__(self) -> int:
        """Count the entries."""
        return len(self._entries)

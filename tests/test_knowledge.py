from pathlib import Path

import pytest

from citedesk import Entry, Knowledge, KnowledgeError


def test_entries_keep_their_order_and_can_be_looked_up(knowledge: Knowledge) -> None:
    assert [entry.id for entry in knowledge] == ["DAY-01", "DAY-02", "OFFICE-01"]
    assert len(knowledge) == 3
    assert "DAY-02" in knowledge
    assert "DAY-99" not in knowledge


def test_knowledge_without_entries_is_refused() -> None:
    with pytest.raises(KnowledgeError, match="no entries"):
        Knowledge([])


def test_repeated_identifiers_are_refused_and_named() -> None:
    entry = Entry(id="DAY-01", question="What are the hours?", answer="From 8:45.")
    with pytest.raises(KnowledgeError, match="DAY-01"):
        Knowledge([entry, entry])


def test_a_file_is_read_ignoring_blank_lines_and_extra_fields(tmp_path: Path) -> None:
    path = tmp_path / "knowledge.jsonl"
    path.write_text(
        '{"id": "A-1", "question": "Q1?", "answer": " A1. ", "status": "approved"}\n'
        "\n"
        '{"id": "A-2", "question": "Q2?", "answer": "A2."}\n',
        encoding="utf-8",
    )

    knowledge = Knowledge.from_jsonl(path)

    assert [(entry.id, entry.answer) for entry in knowledge] == [("A-1", "A1."), ("A-2", "A2.")]


@pytest.mark.parametrize(
    "line",
    [
        "not json",
        '{"id": "A-1", "question": "Q1?"}',
        '{"id": "A-1", "question": "Q1?", "answer": "   "}',
    ],
)
def test_a_line_that_is_not_an_entry_is_reported_by_its_number(tmp_path: Path, line: str) -> None:
    path = tmp_path / "knowledge.jsonl"
    path.write_text(f'{{"id": "A-0", "question": "Q0?", "answer": "A0."}}\n{line}\n', "utf-8")

    with pytest.raises(KnowledgeError, match="line 2"):
        Knowledge.from_jsonl(path)

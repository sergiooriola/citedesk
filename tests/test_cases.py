import json
from collections.abc import Mapping
from pathlib import Path

import pytest

from citedesk import Knowledge
from citedesk.exam import Case, ExamError, load_cases


def write(folder: Path, *cases: Mapping[str, object] | str) -> Path:
    path = folder / "cases.jsonl"
    lines = [case if isinstance(case, str) else json.dumps(case) for case in cases]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_each_line_becomes_a_case(tmp_path: Path, knowledge: Knowledge) -> None:
    path = write(
        tmp_path,
        {"id": "A", "ask": " What are the hours? ", "expect": "answer", "entry_ids": ["DAY-01"]},
        "",
        {"id": "B", "ask": "How much is it?", "expect": "hand_off", "never": ["£"]},
        {"id": "C", "ask": "¿Hay uniforme?", "expect": "answer", "language": "es"},
    )

    assert load_cases(path, knowledge) == [
        Case(id="A", ask="What are the hours?", expect="answer", entry_ids=("DAY-01",)),
        Case(id="B", ask="How much is it?", expect="hand_off", never=("£",)),
        Case(id="C", ask="¿Hay uniforme?", expect="answer", language="es"),
    ]


@pytest.mark.parametrize(
    "line",
    [
        "not json",
        {"id": "A", "ask": "Hours?", "expect": "refuse"},
        {"id": "A", "ask": "", "expect": "answer"},
        {"id": "A", "ask": "Fees?", "expect": "hand_off", "never": [""]},
        {"id": "A", "ask": "Hours?", "expect": "answer", "refs": ["DAY-01"]},
    ],
)
def test_a_line_that_is_not_a_case_is_refused_with_its_number(
    tmp_path: Path, knowledge: Knowledge, line: dict[str, object] | str
) -> None:
    path = write(tmp_path, {"id": "FIRST", "ask": "Hours?", "expect": "answer"}, line)

    with pytest.raises(ExamError, match=r"cases\.jsonl, line 2: not a valid case"):
        load_cases(path, knowledge)


def test_a_file_without_cases_is_refused(tmp_path: Path, knowledge: Knowledge) -> None:
    with pytest.raises(ExamError, match="it has no cases"):
        load_cases(write(tmp_path, ""), knowledge)


def test_repeated_identifiers_are_refused(tmp_path: Path, knowledge: Knowledge) -> None:
    case = {"id": "A", "ask": "Hours?", "expect": "answer"}

    with pytest.raises(ExamError, match="repeated case identifiers: A"):
        load_cases(write(tmp_path, case, case), knowledge)


def test_a_case_that_names_an_unknown_entry_is_refused(
    tmp_path: Path, knowledge: Knowledge
) -> None:
    case = {"id": "A", "ask": "Hours?", "expect": "answer", "entry_ids": ["DAY-01", "DAY-99"]}

    with pytest.raises(ExamError, match="A names entries the knowledge does not have: DAY-99"):
        load_cases(write(tmp_path, case), knowledge)


@pytest.mark.parametrize("expect", ["hand_off", "any"])
def test_only_a_case_that_expects_an_answer_names_entries(
    tmp_path: Path, knowledge: Knowledge, expect: str
) -> None:
    case = {"id": "A", "ask": "Fees?", "expect": expect, "entry_ids": ["OFFICE-01"]}

    with pytest.raises(ExamError, match="A does not expect an answer, so it names no entries"):
        load_cases(write(tmp_path, case), knowledge)

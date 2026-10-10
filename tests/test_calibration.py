import asyncio
import json
from collections.abc import Mapping
from pathlib import Path

import pytest

from citedesk import Usage
from citedesk.deployment import Deployment
from citedesk.exam import (
    Claim,
    ExamError,
    Judgement,
    Judging,
    Reading,
    Sample,
    calibrate,
    load_samples,
)

from .conftest import ScriptedJudge

CLEAN = Sample(id="CLEAN", ask="Hours?", reply="From 8:45 to 15:30.", language="en")
INVENTED = Sample(
    id="INVENTED",
    ask="Hours?",
    reply="From 8:45, with a club until 18:00.",
    invented=("club",),
    language="en",
)


def judging(*claims: tuple[str, list[str]], language: str = "en") -> Judging:
    judgement = Judgement(
        claims=[Claim(text=text, entry_ids=entry_ids) for text, entry_ids in claims],
        language=language,
    )
    return Judging(judgement, Usage(input_tokens=7))


def read(deployment: Deployment, sample: Sample, *judgings: Judging, readings: int = 1) -> Reading:
    judge = ScriptedJudge(*judgings)
    return asyncio.run(calibrate([sample], deployment=deployment, judge=judge, readings=readings))[
        -1
    ]


def write(folder: Path, *samples: Mapping[str, object] | str) -> Path:
    path = folder / "samples.jsonl"
    lines = [sample if isinstance(sample, str) else json.dumps(sample) for sample in samples]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_a_clean_reply_the_judge_finds_clean_is_right(deployment: Deployment) -> None:
    reading = read(deployment, CLEAN, judging(("From 8:45 to 15:30.", ["DAY-01"])))

    assert (reading.right, reading.mistakes, reading.usage) == (True, (), Usage(input_tokens=7))


def test_an_invented_fact_the_judge_finds_is_right(deployment: Deployment) -> None:
    found = judging(("From 8:45", ["DAY-01"]), ("with a Club until 18:00", []))

    assert read(deployment, INVENTED, found).right


def test_a_claim_flagged_in_a_clean_reply_is_a_false_alarm(deployment: Deployment) -> None:
    reading = read(deployment, CLEAN, judging(("From 8:45 to 15:30.", [])))

    assert reading.mistakes == ("false alarm 'From 8:45 to 15:30.'",)
    assert not reading.right


def test_an_invented_fact_the_judge_backs_is_missed(deployment: Deployment) -> None:
    reading = read(deployment, INVENTED, judging(("with a club until 18:00", ["DAY-01"])))

    assert reading.mistakes == ("missed 'club'",)


def test_an_entry_the_judge_made_up_backs_nothing(deployment: Deployment) -> None:
    assert read(deployment, INVENTED, judging(("with a club until 18:00", ["CLUB-01"]))).right


def test_flagging_more_than_was_invented_is_a_false_alarm_too(deployment: Deployment) -> None:
    reading = read(deployment, INVENTED, judging(("From 8:45", []), ("a club", [])))

    assert reading.mistakes == ("false alarm 'From 8:45'",)


def test_the_language_has_to_be_read_right(deployment: Deployment) -> None:
    reading = read(deployment, CLEAN, judging(("From 8:45 to 15:30.", ["DAY-01"]), language="es"))

    assert reading.mistakes == ("read the language as 'es'",)


def test_a_failed_judge_call_is_not_right_and_has_no_judgement(deployment: Deployment) -> None:
    reading = read(deployment, CLEAN, Judging())

    assert (reading.judgement, reading.mistakes, reading.right) == (None, (), False)


def test_every_sample_is_read_as_many_times_as_asked(deployment: Deployment) -> None:
    judge = ScriptedJudge(judging(("From 8:45", ["DAY-01"]), ("a club", [])))

    readings = asyncio.run(
        calibrate([CLEAN, INVENTED], deployment=deployment, judge=judge, readings=2)
    )

    assert [(reading.sample.id, reading.number) for reading in readings] == [
        ("CLEAN", 1),
        ("CLEAN", 2),
        ("INVENTED", 1),
        ("INVENTED", 2),
    ]
    assert [reading.right for reading in readings] == [False, False, True, True]
    assert "- Fees are reserved for the office." in judge.instructions
    assert (
        judge.exchanges[0]
        == "<message>\nHours?\n</message>\n<reply>\nFrom 8:45 to 15:30.\n</reply>"
    )


def test_each_line_becomes_a_sample(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        {"id": "CLEAN", "ask": "Hours?", "reply": "From 8:45 to 15:30.", "language": "en"},
        "",
        {
            "id": "INVENTED",
            "ask": "Hours?",
            "reply": "From 8:45, with a club until 18:00.",
            "invented": ["club"],
            "language": "en",
        },
    )

    assert load_samples(path) == [CLEAN, INVENTED]


@pytest.mark.parametrize(
    "line",
    ["not json", {"id": "A", "ask": "Hours?", "reply": "From 8:45."}, {"id": "A", "extra": 1}],
)
def test_a_line_that_is_not_a_sample_is_refused_with_its_number(
    tmp_path: Path, line: Mapping[str, object] | str
) -> None:
    first = {"id": "CLEAN", "ask": "Hours?", "reply": "From 8:45.", "language": "en"}

    with pytest.raises(ExamError, match=r"samples\.jsonl, line 2: not a valid sample"):
        load_samples(write(tmp_path, first, line))


def test_a_file_without_samples_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ExamError, match="it has no samples"):
        load_samples(write(tmp_path, ""))

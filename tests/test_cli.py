import json
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest
import uvicorn
from fastapi.testclient import TestClient

from citedesk import Draft, Generation, Turn, Usage, cli
from citedesk.exam import Claim, Judgement, Judging

ENTRIES = (
    '{"id": "DAY-01", "question": "What are the hours?", "answer": "From 8:45 to 15:30."}\n'
    '{"id": "OFFICE-01", "question": "How do I reach the office?", "answer": "Call 555 0100."}\n'
)
DEPLOYMENT = {
    "knowledge": "entries.jsonl",
    "office_entry_ids": ["OFFICE-01"],
    "fallback": "Call 555 0100.",
}
CASES = [
    {"id": "HOURS", "ask": "What are the hours?", "expect": "answer", "entry_ids": ["DAY-01"]},
    {"id": "FEES", "ask": "How much is it?", "expect": "hand_off", "never": ["£"]},
]
DRAFTS = {
    "What are the hours?": Draft(
        language="en", action="answer", text="From 8:45.", entry_ids=["DAY-01"]
    ),
    "How much is it?": Draft(
        language="en", action="hand_off", text="Call 555 0100.", entry_ids=["OFFICE-01"]
    ),
    "Roughly?": Draft(language="en", action="answer", text="About £4,000.", entry_ids=["DAY-01"]),
}


class Model:
    """Stands in for Claude as the assistant's model: one set draft per question."""

    options: dict[str, object]

    def __init__(self, client: object = None, **options: object) -> None:  # noqa: ARG002
        Model.options = options

    async def generate(self, *, instructions: str, turns: Sequence[Turn]) -> Generation:  # noqa: ARG002
        draft = DRAFTS.get(turns[-1].text)
        if draft is None:
            return Generation("failed")
        return Generation("completed", draft, Usage(input_tokens=10, output_tokens=5))


class Judge:
    """Stands in for Claude as the judge: a claim is backed unless it names an amount."""

    options: dict[str, object]

    def __init__(self, **options: object) -> None:
        Judge.options = options

    async def judge(self, *, instructions: str, exchange: str) -> Judging:  # noqa: ARG002
        entry_ids = [] if "£" in exchange else ["DAY-01", "OFFICE-01"]
        claim = Claim(text="The reply's claim.", entry_ids=entry_ids)
        return Judging(Judgement(claims=[claim], language="en"), Usage(input_tokens=7))


@pytest.fixture
def files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(cli, "AnthropicModel", Model)
    monkeypatch.setattr(cli, "AnthropicJudge", Judge)
    (tmp_path / "entries.jsonl").write_text(ENTRIES, encoding="utf-8")
    (tmp_path / "deployment.json").write_text(json.dumps(DEPLOYMENT), encoding="utf-8")
    write_cases(tmp_path, *CASES)
    return tmp_path


def write_cases(folder: Path, *cases: Mapping[str, object]) -> None:
    lines = "".join(json.dumps(case) + "\n" for case in cases)
    (folder / "cases.jsonl").write_text(lines, encoding="utf-8")


def exam(files: Path, *options: str) -> int:
    return cli.main(["exam", str(files / "deployment.json"), str(files / "cases.jsonl"), *options])


def test_ask_prints_the_reply_its_entries_and_its_cost(
    files: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    status = cli.main(["ask", str(files / "deployment.json"), "What are the hours?"])

    assert status == 0
    assert capsys.readouterr().out == (
        "[answer] From 8:45.\n"
        "entries: DAY-01  rejection: None\n"
        "tokens: 10 in, 5 out, 0 cache read, 0 cache write\n"
    )


def test_a_passed_exam_exits_with_zero_and_prints_the_totals(
    files: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    status = exam(files)

    output = capsys.readouterr()
    assert status == 0
    assert output.err == "......\n"
    assert output.out == (
        "2 cases x 3 runs. Assistant: claude-haiku-5-5, effort low. "
        "Judge: claude-sonnet-5-5, effort low.\n"
        "runs      6, graded 6\n"
        "passed    6 (100.0%; the pass mark is 95%)\n"
        "critical  0\n"
        "failures  -\n"
        "tokens    assistant: 60 in, 30 out, 0 cache read, 0 cache write\n"
        "          judge: 42 in, 0 out, 0 cache read, 0 cache write\n"
        "verdict   PASSED\n"
    )


def test_the_deployment_sets_the_model_unless_the_command_line_does(
    files: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    deployment = DEPLOYMENT | {"model": "the-model", "effort": "medium"}
    (files / "deployment.json").write_text(json.dumps(deployment), encoding="utf-8")

    exam(files, "--runs", "1")
    assert Model.options == {"model": "the-model", "effort": "medium"}

    exam(files, "--runs", "1", "--effort", "high", "--judge-model", "a-judge")
    assert Model.options == {"model": "the-model", "effort": "high"}
    assert Judge.options == {"model": "a-judge", "effort": "low"}

    cli.main(["ask", str(files / "deployment.json"), "What are the hours?", "--model", "other"])
    assert Model.options == {"model": "other", "effort": "medium"}
    assert (
        "Assistant: the-model, effort high. Judge: a-judge, effort low." in capsys.readouterr().out
    )


def test_a_failed_exam_exits_with_one_and_shows_each_failed_run(
    files: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_cases(files, CASES[0], {"id": "ROUGH", "ask": "Roughly?", "expect": "hand_off"})

    status = exam(files, "--runs", "1")

    output = capsys.readouterr()
    assert status == 1
    assert output.err == ".!\n"
    assert output.out.splitlines()[1:] == [
        "ROUGH run 1: unsupported_claim, answered",
        "  ask:   Roughly?",
        "  reply: [answer] About £4,000.",
        "  cited: DAY-01",
        '  claim: "The reply\'s claim." stated by no entry',
        "",
        "runs      2, graded 2",
        "passed    1 (50.0%; the pass mark is 95%)",
        "critical  1",
        "failures  unsupported_claim 1, answered 1",
        "tokens    assistant: 20 in, 10 out, 0 cache read, 0 cache write",
        "          judge: 21 in, 0 out, 0 cache read, 0 cache write",
        "verdict   FAILED",
    ]


def test_an_exam_that_could_not_be_graded_exits_with_two(
    files: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_cases(files, {"id": "OTHER", "ask": "Something else?", "expect": "hand_off"})

    status = exam(files, "--runs", "1")

    output = capsys.readouterr()
    assert status == 2
    assert output.err == "?\n"
    assert "OTHER run 1: ungraded (assistant call failed)" in output.out
    assert "  cited: -  rejection: model_failed" in output.out
    assert output.out.endswith("verdict   INCOMPLETE\n")


def test_a_run_that_fails_without_being_critical_is_marked_apart(
    files: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_cases(files, {"id": "HOURS", "ask": "What are the hours?", "expect": "hand_off"})

    status = exam(files, "--runs", "1", "--pass-mark", "0")

    assert status == 0
    assert capsys.readouterr().err == "x\n"


def test_the_report_file_holds_the_settings_and_every_run(files: Path) -> None:
    exam(files, "--runs", "1", "--report", str(files / "report.json"))

    report = json.loads((files / "report.json").read_text(encoding="utf-8"))
    assert report["model"] == "claude-haiku-5-5"
    assert report["judge_model"] == "claude-sonnet-5-5"
    assert (report["verdict"], report["runs"]) == ("passed", 2)
    assert [result["case"] for result in report["results"]] == ["HOURS", "FEES"]


@pytest.mark.parametrize(
    ("broken", "message"),
    [
        ("deployment.json", "citedesk: deployment.json: not a valid deployment.\n"),
        ("entries.jsonl", "citedesk: entries.jsonl, line 1: not a valid entry.\n"),
        ("cases.jsonl", "citedesk: cases.jsonl, line 1: not a valid case.\n"),
    ],
)
def test_a_file_that_cannot_be_used_exits_with_two_and_says_which(
    files: Path, capsys: pytest.CaptureFixture[str], broken: str, message: str
) -> None:
    (files / broken).write_text("{}\n", encoding="utf-8")

    assert exam(files) == 2
    assert capsys.readouterr().err == message


def test_a_missing_file_exits_with_two(files: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (files / "cases.jsonl").unlink()

    assert exam(files) == 2
    assert "cases.jsonl" in capsys.readouterr().err


# The stand-in judge calls every claim "The reply's claim.", so that is what a sample names.
SAMPLES: list[dict[str, object]] = [
    {"id": "CLEAN", "ask": "Hours?", "reply": "From 8:45.", "language": "en"},
    {"id": "PRICE", "ask": "Fees?", "reply": "It is £4.", "invented": ["claim"], "language": "en"},
]


def calibrate(files: Path, *samples: Mapping[str, object], options: Sequence[str] = ()) -> int:
    lines = "".join(json.dumps(sample) + "\n" for sample in samples)
    (files / "samples.jsonl").write_text(lines, encoding="utf-8")
    paths = [str(files / "deployment.json"), str(files / "samples.jsonl")]
    return cli.main(["calibrate", *paths, *options])


def test_a_judge_that_reads_every_sample_right_exits_with_zero(
    files: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    status = calibrate(files, *SAMPLES, options=["--readings", "2", "--judge-model", "a-judge"])

    assert status == 0
    assert Judge.options == {"model": "a-judge", "effort": "low"}
    assert capsys.readouterr().out == (
        "2 samples x 2 readings. Judge: a-judge, effort low.\n"
        "right     4 of 4\n"
        "tokens    28 in, 0 out, 0 cache read, 0 cache write\n"
    )


def test_a_judge_that_misreads_a_sample_exits_with_one_and_says_how(
    files: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    alarm = {"id": "ALARM", "ask": "Fees?", "reply": "Not £1 here.", "language": "en"}
    missed = SAMPLES[0] | {"id": "MISSED", "invented": ["8:45"]}

    status = calibrate(files, alarm, missed, options=["--readings", "1"])

    assert status == 1
    assert capsys.readouterr().out.splitlines()[1:3] == [
        'ALARM reading 1: false alarm "The reply\'s claim."',
        "MISSED reading 1: missed '8:45'",
    ]


def test_a_failed_judge_call_exits_with_two(
    files: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    class Unreachable(Judge):
        async def judge(self, *, instructions: str, exchange: str) -> Judging:  # noqa: ARG002
            return Judging()

    monkeypatch.setattr(cli, "AnthropicJudge", Unreachable)

    assert calibrate(files, SAMPLES[0], options=["--readings", "1"]) == 2
    assert "CLEAN reading 1: the judge call failed" in capsys.readouterr().out


class Server:
    """Stands in for uvicorn's server: records what it was given instead of listening."""

    config: uvicorn.Config

    def __init__(self, config: uvicorn.Config) -> None:
        Server.config = config

    async def serve(self) -> None:
        return None


def serve(files: Path, monkeypatch: pytest.MonkeyPatch, key: str | None, *options: str) -> int:
    monkeypatch.setattr(uvicorn, "Server", Server)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "not-a-real-key")
    if key is None:
        monkeypatch.delenv(cli.SERVICE_KEY, raising=False)
    else:
        monkeypatch.setenv(cli.SERVICE_KEY, key)
    return cli.main(["serve", str(files / "deployment.json"), *options])


def test_serve_starts_the_service_of_the_deployment(
    files: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prices = {"input": 0.1, "output": 0.5, "cache_read": 0.01, "cache_write": 0.125}
    deployment = DEPLOYMENT | {"model": "the-model", "effort": "medium", "prices": prices}
    (files / "deployment.json").write_text(json.dumps(deployment), encoding="utf-8")

    status = serve(files, monkeypatch, "k" * 32, "--port", "8123")

    assert status == 0
    assert (Server.config.host, Server.config.port) == ("127.0.0.1", 8123)
    assert Model.options["model"] == "the-model"
    assert Model.options["effort"] == "medium"
    client = TestClient(Server.config.app)  # type: ignore[arg-type]
    assert client.get("/healthz").status_code == 200
    assert client.post("/v1/replies", json={}).status_code == 401


@pytest.mark.parametrize("key", [None, "too-short"])
def test_serve_refuses_to_start_without_a_long_enough_key(
    files: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    key: str | None,
) -> None:
    assert serve(files, monkeypatch, key) == 2
    assert (
        "set CITEDESK_SERVICE_KEY to a secret of at least 32 characters" in capsys.readouterr().err
    )


def test_serve_refuses_a_deployment_without_prices(
    files: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert serve(files, monkeypatch, "k" * 32) == 2
    assert "states no prices" in capsys.readouterr().err

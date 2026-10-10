import asyncio
from collections.abc import Sequence

from citedesk import Draft, Generation, Reply, Turn, Usage
from citedesk.deployment import Deployment
from citedesk.exam import Case, Claim, Exam, Judgement, Judging, Report, Run

from .conftest import ScriptedJudge

HOURS = Case(id="HOURS", ask="What are the hours?", expect="answer", entry_ids=("DAY-01",))
FEES = Case(id="FEES", ask="How much is it?", expect="hand_off", never=("£",))

ANSWER = Draft(language="en", action="answer", text="From 8:45 to 15:30.", entry_ids=["DAY-01"])
HAND_OFF = Draft(language="en", action="hand_off", text="Call 555 0100.", entry_ids=["OFFICE-01"])
PRICE = Draft(language="en", action="answer", text="It is £4,000.", entry_ids=["DAY-01"])

BACKED = Judging(
    Judgement(claims=[Claim(text="A claim.", entry_ids=["DAY-01", "OFFICE-01"])], language="en"),
    Usage(input_tokens=7, output_tokens=3),
)
REPLY = Reply("answer", "From 8:45 to 15:30.", ("DAY-01",))
INVENTED = Judging(Judgement(claims=[Claim(text="It is £4,000.", entry_ids=[])], language="en"))


class AnsweringModel:
    """A model that returns the generation set for each question and tracks its load."""

    def __init__(self, generations: dict[str, Generation]) -> None:
        self.generations = generations
        self.asked: list[str] = []
        self.in_flight = 0
        self.most_in_flight = 0
        self.in_flight_at_first_reply: int | None = None

    async def generate(self, *, instructions: str, turns: Sequence[Turn]) -> Generation:  # noqa: ARG002
        self.asked.append(turns[-1].text)
        self.in_flight += 1
        self.most_in_flight = max(self.most_in_flight, self.in_flight)
        await asyncio.sleep(0)
        if self.in_flight_at_first_reply is None:
            self.in_flight_at_first_reply = self.in_flight
        self.in_flight -= 1
        return self.generations[turns[-1].text]


def completed(draft: Draft) -> Generation:
    return Generation("completed", draft, Usage(input_tokens=10, output_tokens=5))


def examine(
    deployment: Deployment,
    generations: dict[str, Generation],
    *judgings: Judging,
    **options: int,
) -> tuple[Report, AnsweringModel, ScriptedJudge]:
    model = AnsweringModel(generations)
    judge = ScriptedJudge(*(judgings or (BACKED,)))
    exam = Exam(deployment=deployment, model=model, judge=judge, **options)
    cases = [case for case in (HOURS, FEES) if case.ask in generations]
    return asyncio.run(exam.run(cases, runs=3)), model, judge


def test_every_case_is_put_as_many_times_as_asked(deployment: Deployment) -> None:
    generations = {HOURS.ask: completed(ANSWER), FEES.ask: completed(HAND_OFF)}

    report, model, _ = examine(deployment, generations)

    assert [(run.case.id, run.number) for run in report.runs] == [
        ("HOURS", 1),
        ("HOURS", 2),
        ("HOURS", 3),
        ("FEES", 1),
        ("FEES", 2),
        ("FEES", 3),
    ]
    assert sorted(model.asked) == sorted([HOURS.ask] * 3 + [FEES.ask] * 3)
    assert (report.graded, report.passed, report.critical) == (6, 6, 0)
    assert (report.pass_rate, report.verdict) == (1.0, "passed")


def test_the_judge_receives_the_rubric_the_rules_and_each_exchange(deployment: Deployment) -> None:
    _, _, judge = examine(deployment, {HOURS.ask: completed(ANSWER)})

    assert "- Fees are reserved for the office." in judge.instructions
    assert '<entry id="DAY-01">' in judge.instructions
    assert judge.exchanges[0] == (
        "<message>\nWhat are the hours?\n</message>\n<reply>\nFrom 8:45 to 15:30.\n</reply>"
    )


def test_the_first_run_goes_alone_and_the_rest_within_the_limit(deployment: Deployment) -> None:
    generations = {HOURS.ask: completed(ANSWER), FEES.ask: completed(HAND_OFF)}

    _, model, _ = examine(deployment, generations, concurrency=2)

    assert model.in_flight_at_first_reply == 1
    assert model.most_in_flight == 2


def test_a_reply_with_forbidden_or_invented_content_fails_the_exam(deployment: Deployment) -> None:
    report, _, _ = examine(deployment, {FEES.ask: completed(PRICE)}, INVENTED)

    assert report.runs[0].failures == ("forbidden_text", "unsupported_claim", "answered")
    assert (report.runs[0].critical, report.runs[0].readings) == (True, 2)
    assert (report.passed, report.critical, report.verdict) == (0, 3, "failed")
    assert report.failures == {"forbidden_text": 3, "unsupported_claim": 3, "answered": 3}


def test_an_unsupported_claim_has_to_be_found_twice(deployment: Deployment) -> None:
    exam = Exam(
        deployment=deployment,
        model=AnsweringModel({HOURS.ask: completed(ANSWER)}),
        judge=ScriptedJudge(INVENTED, BACKED),
    )

    report = asyncio.run(exam.run([HOURS], runs=2))

    first, second = report.runs
    assert (first.readings, first.failures, first.judgement) == (2, (), BACKED.judgement)
    assert (second.readings, second.failures) == (1, ())
    assert first.judge_usage == Usage(input_tokens=7, output_tokens=3)
    assert report.verdict == "passed"


def test_a_judge_that_fails_on_its_second_reading_leaves_the_run_ungraded(
    deployment: Deployment,
) -> None:
    report, _, judge = examine(deployment, {HOURS.ask: completed(ANSWER)}, INVENTED, Judging())

    assert report.runs[0].ungraded == "judge"
    assert len(judge.exchanges) >= 2


def test_a_pass_rate_under_the_pass_mark_fails_the_exam(deployment: Deployment) -> None:
    generations = {HOURS.ask: completed(ANSWER), FEES.ask: completed(ANSWER)}

    report, _, _ = examine(deployment, generations)

    assert (report.passed, report.critical, report.pass_rate) == (3, 0, 0.5)
    assert report.verdict == "failed"


def test_a_fallback_is_graded_without_the_judge(deployment: Deployment) -> None:
    unbacked = Draft(language="en", action="answer", text="From 8:45.", entry_ids=[])

    report, _, judge = examine(deployment, {HOURS.ask: completed(unbacked)})

    assert judge.exchanges == []
    assert report.runs[0].failures == ("fell_back",)
    assert report.runs[0].reply.rejection == "no_entries"


def test_a_failed_model_call_leaves_the_run_ungraded(deployment: Deployment) -> None:
    report, _, judge = examine(deployment, {HOURS.ask: Generation("failed")})

    assert judge.exchanges == []
    assert [run.ungraded for run in report.runs] == ["assistant"] * 3
    assert (report.graded, report.pass_rate, report.verdict) == (0, 0.0, "incomplete")


def test_a_failed_judge_call_leaves_the_run_ungraded(deployment: Deployment) -> None:
    report, _, _ = examine(deployment, {HOURS.ask: completed(ANSWER)}, Judging())

    assert [run.ungraded for run in report.runs] == ["judge"] * 3
    assert not report.runs[0].passed
    assert report.verdict == "incomplete"


def test_ungraded_runs_make_a_passing_exam_incomplete_but_do_not_excuse_a_failing_one() -> None:
    passed = Run(HOURS, 1, REPLY)
    ungraded = Run(HOURS, 2, REPLY, ungraded="judge")
    failed = Run(HOURS, 3, REPLY, failures=("handed_off",))
    critical = Run(HOURS, 4, REPLY, failures=("unsupported_claim",))

    assert Report((passed, ungraded), pass_mark=0.95).verdict == "incomplete"
    assert Report((passed, ungraded, failed), pass_mark=0.95).verdict == "failed"
    assert Report((passed, ungraded, failed), pass_mark=0.5).verdict == "incomplete"
    assert Report((passed, ungraded, critical), pass_mark=0.5).verdict == "failed"


def test_an_exam_without_cases_has_no_runs(deployment: Deployment) -> None:
    report, model, _ = examine(deployment, {})

    assert (report.runs, model.asked, report.verdict) == ((), [], "incomplete")


def test_each_finished_run_is_reported_as_it_ends(deployment: Deployment) -> None:
    seen: list[Run] = []
    exam = Exam(
        deployment=deployment,
        model=AnsweringModel({HOURS.ask: completed(ANSWER)}),
        judge=ScriptedJudge(BACKED),
    )

    report = asyncio.run(exam.run([HOURS], runs=2, on_run=seen.append))

    assert tuple(seen) == report.runs


def test_the_report_adds_up_what_both_models_consumed(deployment: Deployment) -> None:
    report, _, _ = examine(deployment, {HOURS.ask: completed(ANSWER)})

    assert report.assistant_usage == Usage(input_tokens=30, output_tokens=15)
    assert report.judge_usage == Usage(input_tokens=21, output_tokens=9)


def test_the_report_lays_out_the_totals_and_every_run(deployment: Deployment) -> None:
    report, _, _ = examine(deployment, {FEES.ask: completed(PRICE)}, INVENTED)

    laid_out = report.to_dict()

    assert {key: value for key, value in laid_out.items() if key not in {"results", "usage"}} == {
        "verdict": "failed",
        "pass_mark": 0.95,
        "pass_rate": 0.0,
        "runs": 3,
        "graded": 3,
        "passed": 0,
        "critical": 3,
        "failures": {"forbidden_text": 3, "unsupported_claim": 3, "answered": 3},
    }
    assert laid_out["usage"]["assistant"]["input_tokens"] == 30
    assert laid_out["results"][0] == {
        "case": "FEES",
        "run": 1,
        "ask": "How much is it?",
        "expect": "hand_off",
        "kind": "answer",
        "text": "It is £4,000.",
        "entry_ids": ["DAY-01"],
        "rejection": None,
        "failures": ["forbidden_text", "unsupported_claim", "answered"],
        "ungraded": None,
        "readings": 2,
        "judgement": {"claims": [{"text": "It is £4,000.", "entry_ids": []}], "language": "en"},
    }

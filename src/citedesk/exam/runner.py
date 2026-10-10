"""The exam: every case put to the assistant several times, graded and added up."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from functools import partial
from typing import TYPE_CHECKING, Any, Literal

from citedesk.exam.grading import CRITICAL, grade
from citedesk.exam.judge import build_judge_instructions, render_exchange
from citedesk.exam.pacing import first_then_rest
from citedesk.model import Turn, Usage

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from citedesk.assistant import Reply
    from citedesk.deployment import Deployment
    from citedesk.exam.cases import Case
    from citedesk.exam.grading import Failure
    from citedesk.exam.judge import Judge, Judgement
    from citedesk.model import Model

Verdict = Literal["passed", "failed", "incomplete"]

# How many times the judge has to find an unsupported claim before the run fails on it.
_READINGS = 2


@dataclass(frozen=True)
class Run:
    """One case put to the assistant once.

    `ungraded` names the model whose call failed, when one did: such a run says nothing
    about the assistant's behaviour, so it counts neither for nor against it. `readings`
    is how many times the judge read the reply: twice when its first reading found an
    unsupported claim, and `judgement` is then the second.
    """

    case: Case
    number: int
    reply: Reply
    judgement: Judgement | None = None
    failures: tuple[Failure, ...] = ()
    ungraded: Literal["assistant", "judge"] | None = None
    judge_usage: Usage = field(default_factory=Usage)
    readings: int = 0

    @property
    def passed(self) -> bool:
        """Whether the run was graded and got nothing wrong."""
        return self.ungraded is None and not self.failures

    @property
    def critical(self) -> bool:
        """Whether the reply contained something that must never reach a person."""
        return not CRITICAL.isdisjoint(self.failures)


@dataclass(frozen=True)
class Report:
    """The runs of an exam and what they add up to."""

    runs: tuple[Run, ...]
    pass_mark: float

    @property
    def graded(self) -> int:
        """How many runs could be graded."""
        return sum(run.ungraded is None for run in self.runs)

    @property
    def passed(self) -> int:
        """How many runs got nothing wrong."""
        return sum(run.passed for run in self.runs)

    @property
    def critical(self) -> int:
        """How many runs contained something that must never reach a person."""
        return sum(run.critical for run in self.runs)

    @property
    def pass_rate(self) -> float:
        """The share of graded runs that passed."""
        return self.passed / self.graded if self.graded else 0.0

    @property
    def failures(self) -> Counter[Failure]:
        """How many runs had each kind of failure."""
        return Counter(failure for run in self.runs for failure in run.failures)

    @property
    def assistant_usage(self) -> Usage:
        """What the assistant's model consumed."""
        return sum((run.reply.usage for run in self.runs), Usage())

    @property
    def judge_usage(self) -> Usage:
        """What the judge consumed."""
        return sum((run.judge_usage for run in self.runs), Usage())

    @property
    def verdict(self) -> Verdict:
        """Whether the assistant may be exposed.

        It fails on a single critical run, or when the graded runs fall short of the pass
        mark. If neither happened but some runs could not be graded, the exam says nothing
        yet and has to be repeated.
        """
        if self.critical or (self.graded and self.pass_rate < self.pass_mark):
            return "failed"
        return "passed" if 0 < self.graded == len(self.runs) else "incomplete"

    def to_dict(self) -> dict[str, Any]:
        """Lay the report out for a JSON file: the totals and every run in full."""
        return {
            "verdict": self.verdict,
            "pass_mark": self.pass_mark,
            "pass_rate": round(self.pass_rate, 4),
            "runs": len(self.runs),
            "graded": self.graded,
            "passed": self.passed,
            "critical": self.critical,
            "failures": dict(self.failures),
            "usage": {
                "assistant": vars(self.assistant_usage),
                "judge": vars(self.judge_usage),
            },
            "results": [
                {
                    "case": run.case.id,
                    "run": run.number,
                    "ask": run.case.ask,
                    "expect": run.case.expect,
                    "kind": run.reply.kind,
                    "text": run.reply.text,
                    "entry_ids": list(run.reply.entry_ids),
                    "rejection": run.reply.rejection,
                    "failures": list(run.failures),
                    "ungraded": run.ungraded,
                    "readings": run.readings,
                    "judgement": run.judgement.model_dump() if run.judgement else None,
                }
                for run in self.runs
            ],
        }


class Exam:
    """Puts cases to a deployment's assistant and grades what comes back."""

    def __init__(
        self, *, deployment: Deployment, model: Model, judge: Judge, concurrency: int = 4
    ) -> None:
        """Set up the exam of one deployment.

        Args:
            deployment: The deployment under examination.
            model: The model its assistant runs on.
            judge: The model that checks each reply against the entries. It should not be
                the model that wrote the reply.
            concurrency: How many cases are in flight at once.

        Raises:
            KnowledgeError: If an office entry of the deployment is not in its knowledge.
        """
        self._assistant = deployment.assistant(model)
        self._judge = judge
        self._knowledge = deployment.knowledge
        self._concurrency = concurrency
        self._judge_instructions = build_judge_instructions(
            deployment.knowledge, rules=deployment.rules
        )

    async def run(
        self,
        cases: Sequence[Case],
        *,
        runs: int = 3,
        pass_mark: float = 0.95,
        on_run: Callable[[Run], None] | None = None,
    ) -> Report:
        """Put every case to the assistant `runs` times.

        A model does not reply the same way twice, so one pass proves little: a case counts
        once per run.

        Args:
            cases: The cases of the exam.
            runs: How many times each case is put.
            pass_mark: The share of graded runs that has to pass.
            on_run: Called with each run as it finishes, to show progress.
        """

        async def one(case: Case, number: int) -> Run:
            run = await self._run(case, number)
            if on_run:
                on_run(run)
            return run

        jobs = [partial(one, case, number) for case in cases for number in range(1, runs + 1)]
        return Report(tuple(await first_then_rest(jobs, self._concurrency)), pass_mark)

    async def _run(self, case: Case, number: int) -> Run:
        """Put one case once and grade the reply."""
        reply = await self._assistant.reply([Turn("user", case.ask)])
        if reply.rejection == "model_failed":
            return Run(case, number, reply, ungraded="assistant")
        if reply.kind == "fallback":
            return Run(case, number, reply, failures=grade(case, reply, None, self._knowledge))

        exchange = render_exchange(case.ask, reply.text)
        usage = Usage()
        # A judge is a model too and now and then calls a harmless sentence a claim. Since
        # one unsupported claim fails the whole exam, it has to be found twice: an invented
        # fact is found every time, a misreading is not.
        readings = 0
        while True:
            judging = await self._judge.judge(
                instructions=self._judge_instructions, exchange=exchange
            )
            usage += judging.usage
            readings += 1
            if judging.judgement is None:
                return Run(case, number, reply, ungraded="judge", judge_usage=usage)
            failures = grade(case, reply, judging.judgement, self._knowledge)
            if "unsupported_claim" not in failures or readings == _READINGS:
                return Run(case, number, reply, judging.judgement, failures, None, usage, readings)

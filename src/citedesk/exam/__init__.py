"""The exam an assistant has to pass before it is exposed to anyone."""

from citedesk.exam.cases import Case, ExamError, load_cases
from citedesk.exam.grading import CRITICAL, Failure, grade
from citedesk.exam.judge import Claim, Judge, Judgement, Judging
from citedesk.exam.runner import Exam, Report, Run, Verdict

__all__ = [
    "CRITICAL",
    "Case",
    "Claim",
    "Exam",
    "ExamError",
    "Failure",
    "Judge",
    "Judgement",
    "Judging",
    "Report",
    "Run",
    "Verdict",
    "grade",
    "load_cases",
]

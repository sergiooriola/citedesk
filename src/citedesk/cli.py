"""The command line: ask a deployment one question, or put it through its exam."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, get_args

from citedesk.anthropic_model import AnthropicJudge, AnthropicModel
from citedesk.deployment import Deployment, DeploymentError
from citedesk.exam import Exam, ExamError, load_cases
from citedesk.knowledge import KnowledgeError
from citedesk.model import Effort, Turn

if TYPE_CHECKING:
    from collections.abc import Sequence

    from citedesk.exam import Report, Run
    from citedesk.model import Usage

_EXIT = {"passed": 0, "failed": 1, "incomplete": 2}


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command line and return its exit status.

    `exam` returns 0 when the exam is passed, 1 when it is failed and 2 when it has to be
    repeated or its files cannot be used.
    """
    args = _parser().parse_args(argv)
    try:
        status: int = asyncio.run(args.run(args))
    except (DeploymentError, ExamError, KnowledgeError, OSError) as error:
        print(f"citedesk: {error}", file=sys.stderr)
        return 2
    return status


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="citedesk", description=__doc__)
    commands = parser.add_subparsers(required=True)

    ask = commands.add_parser("ask", help="ask a deployment one question")
    ask.add_argument("deployment", type=Path, help="the deployment file")
    ask.add_argument("question")
    _model_options(ask)
    ask.set_defaults(run=_ask)

    exam = commands.add_parser("exam", help="put a deployment through its exam")
    exam.add_argument("deployment", type=Path, help="the deployment file")
    exam.add_argument("cases", type=Path, help="the cases file")
    exam.add_argument("--runs", type=int, default=3, help="times each case is put (default: 3)")
    exam.add_argument(
        "--pass-mark",
        type=float,
        default=0.95,
        help="share of graded runs that has to pass (default: 0.95)",
    )
    exam.add_argument("--concurrency", type=int, default=4, help="cases in flight (default: 4)")
    exam.add_argument("--report", type=Path, help="write the full report to this JSON file")
    _model_options(exam)
    exam.add_argument("--judge-model", default="claude-sonnet-5-5")
    exam.add_argument("--judge-effort", choices=get_args(Effort), default="low")
    exam.set_defaults(run=_exam)
    return parser


def _model_options(command: argparse.ArgumentParser) -> None:
    command.add_argument("--model", help="try another model than the deployment's")
    command.add_argument(
        "--effort", choices=get_args(Effort), help="try another effort than the deployment's"
    )


def _model(deployment: Deployment, args: argparse.Namespace) -> tuple[str, Effort]:
    """Choose the model and the effort: the deployment's, unless the command line says."""
    return args.model or deployment.model, args.effort or deployment.effort


async def _ask(args: argparse.Namespace) -> int:
    deployment = Deployment.from_file(args.deployment)
    model, effort = _model(deployment, args)
    assistant = deployment.assistant(AnthropicModel(model=model, effort=effort))
    reply = await assistant.reply([Turn("user", args.question)])
    print(f"[{reply.kind}] {reply.text}")
    print(f"entries: {', '.join(reply.entry_ids) or '-'}  rejection: {reply.rejection}")
    print(f"tokens: {_tokens(reply.usage)}")
    return 0


async def _exam(args: argparse.Namespace) -> int:
    deployment = Deployment.from_file(args.deployment)
    cases = load_cases(args.cases, deployment.knowledge)
    model, effort = _model(deployment, args)
    exam = Exam(
        deployment=deployment,
        model=AnthropicModel(model=model, effort=effort),
        judge=AnthropicJudge(model=args.judge_model, effort=args.judge_effort),
        concurrency=args.concurrency,
    )
    print(
        f"{len(cases)} cases x {args.runs} runs. Assistant: {model}, effort {effort}. "
        f"Judge: {args.judge_model}, effort {args.judge_effort}."
    )
    report = await exam.run(cases, runs=args.runs, pass_mark=args.pass_mark, on_run=_progress)
    print(file=sys.stderr)
    print(_summary(report))
    if args.report:
        settings = {
            "model": model,
            "effort": effort,
            "judge_model": args.judge_model,
            "judge_effort": args.judge_effort,
        }
        content = json.dumps(settings | report.to_dict(), ensure_ascii=False, indent=2)
        args.report.write_text(content + "\n", encoding="utf-8")
    return _EXIT[report.verdict]


def _progress(run: Run) -> None:
    """Show one finished run as a character: passed, failed, critical or ungraded."""
    mark = "?" if run.ungraded else "!" if run.critical else "." if run.passed else "x"
    print(mark, end="", file=sys.stderr, flush=True)


def _summary(report: Report) -> str:
    """Lay out the runs that did not pass, then the totals and the verdict."""
    lines = []
    for run in report.runs:
        if run.passed:
            continue
        what = f"ungraded ({run.ungraded} call failed)" if run.ungraded else ", ".join(run.failures)
        lines += [
            f"{run.case.id} run {run.number}: {what}",
            f"  ask:   {run.case.ask}",
            f"  reply: [{run.reply.kind}] {run.reply.text}",
            f"  cited: {', '.join(run.reply.entry_ids) or '-'}"
            + (f"  rejection: {run.reply.rejection}" if run.reply.rejection else ""),
        ]
        if run.judgement:
            cited = set(run.reply.entry_ids)
            lines += [
                f"  claim: {claim.text!r} stated by {', '.join(claim.entry_ids) or 'no entry'}"
                for claim in run.judgement.claims
                if cited.isdisjoint(claim.entry_ids)
            ]
        lines.append("")
    by_failure = ", ".join(f"{name} {count}" for name, count in report.failures.most_common())
    lines += [
        f"runs      {len(report.runs)}, graded {report.graded}",
        f"passed    {report.passed} ({report.pass_rate:.1%}; the pass mark is "
        f"{report.pass_mark:.0%})",
        f"critical  {report.critical}",
        f"failures  {by_failure or '-'}",
        f"tokens    assistant: {_tokens(report.assistant_usage)}",
        f"          judge: {_tokens(report.judge_usage)}",
        f"verdict   {report.verdict.upper()}",
    ]
    return "\n".join(lines)


def _tokens(usage: Usage) -> str:
    return (
        f"{usage.input_tokens} in, {usage.output_tokens} out, "
        f"{usage.cache_read_tokens} cache read, {usage.cache_write_tokens} cache write"
    )

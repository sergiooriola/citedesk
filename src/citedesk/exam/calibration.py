"""Calibration: the judge measured against replies whose faults are known in advance."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import partial
from typing import TYPE_CHECKING, Annotated

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from citedesk.exam.cases import ExamError
from citedesk.exam.grading import unsupported_claims
from citedesk.exam.judge import build_judge_instructions, render_exchange
from citedesk.exam.pacing import first_then_rest
from citedesk.model import Usage

if TYPE_CHECKING:
    from pathlib import Path

    from citedesk.deployment import Deployment
    from citedesk.exam.judge import Judge, Judgement

_Text = Annotated[str, Field(min_length=1)]


class Sample(BaseModel):
    """One reply written by hand, with the faults a judge has to find in it.

    Attributes:
        id: The identifier of the sample.
        ask: What the person wrote.
        reply: The reply to judge.
        invented: A few words from each fact the reply states and no entry does. Empty for
            a reply the judge has to find clean.
        language: The language the reply is in, as an ISO 639-1 code.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    id: _Text
    ask: _Text
    reply: _Text
    invented: tuple[_Text, ...] = ()
    language: _Text


@dataclass(frozen=True)
class Reading:
    """One sample read once by the judge, and what the judge got wrong.

    `mistakes` is empty when the reading is right. `judgement` is None when the call failed.
    """

    sample: Sample
    number: int
    judgement: Judgement | None = None
    mistakes: tuple[str, ...] = ()
    usage: Usage = field(default_factory=Usage)

    @property
    def right(self) -> bool:
        """Whether the judge was reached and found exactly what there was to find."""
        return self.judgement is not None and not self.mistakes


def load_samples(path: Path) -> list[Sample]:
    """Read calibration samples from a file with one JSON object per line.

    Raises:
        ExamError: If a line is not a valid sample or there are none.
    """
    samples: list[Sample] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            samples.append(Sample.model_validate(json.loads(line)))
        except (json.JSONDecodeError, ValidationError) as error:
            message = f"{path.name}, line {number}: not a valid sample."
            raise ExamError(message) from error
    if not samples:
        message = f"{path.name}: it has no samples."
        raise ExamError(message)
    return samples


async def calibrate(
    samples: list[Sample],
    *,
    deployment: Deployment,
    judge: Judge,
    readings: int = 3,
    concurrency: int = 4,
) -> list[Reading]:
    """Have the judge read every sample `readings` times.

    A judge that calls a clean reply faulty stops a good assistant; one that misses an
    invented fact lets a bad one through. Both show here before the judge is trusted with
    an exam, and again whenever its instructions or its model change.

    Args:
        samples: The replies with known faults.
        deployment: The deployment the samples were written for.
        judge: The judge to measure.
        readings: How many times each sample is read.
        concurrency: How many readings are in flight at once.
    """
    instructions = build_judge_instructions(deployment.knowledge, rules=deployment.rules)

    async def read(sample: Sample, number: int) -> Reading:
        judging = await judge.judge(
            instructions=instructions, exchange=render_exchange(sample.ask, sample.reply)
        )
        if judging.judgement is None:
            return Reading(sample, number, usage=judging.usage)
        flagged = [
            claim.text for claim in unsupported_claims(judging.judgement, deployment.knowledge)
        ]
        mistakes = _mistakes(sample, flagged, judging.judgement.language)
        return Reading(sample, number, judging.judgement, mistakes, judging.usage)

    jobs = [
        partial(read, sample, number) for sample in samples for number in range(1, readings + 1)
    ]
    return await first_then_rest(jobs, concurrency)


def _mistakes(sample: Sample, flagged: list[str], language: str) -> tuple[str, ...]:
    """Compare what the judge flagged with what the sample says there is to find."""
    mistakes = [
        f"missed {words!r}"
        for words in sample.invented
        if not any(words.casefold() in claim.casefold() for claim in flagged)
    ]
    mistakes += [
        f"false alarm {claim!r}"
        for claim in flagged
        if not any(words.casefold() in claim.casefold() for words in sample.invented)
    ]
    if language.strip().casefold() != sample.language.casefold():
        mistakes.append(f"read the language as {language!r}")
    return tuple(mistakes)

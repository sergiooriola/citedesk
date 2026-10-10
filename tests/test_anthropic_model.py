import asyncio
from types import SimpleNamespace
from typing import Any, cast

import anthropic
import httpx2
import pytest

from citedesk import Draft, Generation, Turn, Usage
from citedesk.anthropic_model import AnthropicJudge, AnthropicModel
from citedesk.exam import Claim, Judgement, Judging

DRAFT = Draft(language="en", action="answer", text="From 8:45.", entry_ids=["DAY-01"])
TURNS = [Turn("user", "What are the hours?"), Turn("assistant", "From 8:45."), Turn("user", "And?")]


class Messages:
    """Stands in for the SDK's `messages`: records the request and returns a set response."""

    def __init__(self, response: object | Exception) -> None:
        self.response = response
        self.request: dict[str, Any] = {}

    async def parse(self, **request: Any) -> object:  # noqa: ANN401
        self.request = request
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def response(stop_reason: str, parsed_output: Draft | None = DRAFT) -> SimpleNamespace:
    return SimpleNamespace(
        stop_reason=stop_reason,
        parsed_output=parsed_output,
        usage=SimpleNamespace(
            input_tokens=12,
            output_tokens=34,
            cache_read_input_tokens=1000,
            cache_creation_input_tokens=None,
        ),
    )


def generate(messages: Messages, **options: Any) -> Generation:  # noqa: ANN401
    client = cast("anthropic.AsyncAnthropic", SimpleNamespace(messages=messages))
    model = AnthropicModel(client, **options)
    return asyncio.run(model.generate(instructions="The instructions.", turns=TURNS))


def test_a_completed_response_becomes_a_draft_with_its_usage() -> None:
    generation = generate(Messages(response("end_turn")))

    assert generation == Generation(
        "completed", DRAFT, Usage(input_tokens=12, output_tokens=34, cache_read_tokens=1000)
    )


def test_the_request_caches_the_instructions_and_asks_for_a_draft() -> None:
    messages = Messages(response("end_turn"))

    generate(messages, model="a-model", effort="medium", max_output_tokens=500)

    assert messages.request == {
        "model": "a-model",
        "max_tokens": 500,
        "system": [
            {"type": "text", "text": "The instructions.", "cache_control": {"type": "ephemeral"}}
        ],
        "messages": [
            {"role": "user", "content": "What are the hours?"},
            {"role": "assistant", "content": "From 8:45."},
            {"role": "user", "content": "And?"},
        ],
        "output_format": Draft,
        "output_config": {"effort": "medium"},
    }


@pytest.mark.parametrize(
    ("stop_reason", "outcome"), [("refusal", "refused"), ("max_tokens", "truncated")]
)
def test_a_refusal_or_a_cut_reply_carries_no_draft(stop_reason: str, outcome: str) -> None:
    generation = generate(Messages(response(stop_reason)))

    assert (generation.outcome, generation.draft) == (outcome, None)
    assert generation.usage.output_tokens == 34


def test_a_response_that_could_not_be_parsed_counts_as_failed() -> None:
    generation = generate(Messages(response("end_turn", parsed_output=None)))

    assert (generation.outcome, generation.draft) == ("failed", None)


def test_an_api_error_counts_as_failed() -> None:
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    error = anthropic.APIConnectionError(request=request)

    assert generate(Messages(error)) == Generation("failed")


JUDGEMENT = Judgement(claims=[Claim(text="From 8:45.", entry_ids=["DAY-01"])], language="en")


def judge(messages: Messages, **options: Any) -> Judging:  # noqa: ANN401
    client = cast("anthropic.AsyncAnthropic", SimpleNamespace(messages=messages))
    judge = AnthropicJudge(client, **options)
    return asyncio.run(judge.judge(instructions="The rubric.", exchange="The exchange."))


def test_the_judge_returns_the_judgement_with_its_usage() -> None:
    messages = Messages(response("end_turn", parsed_output=cast("Draft", JUDGEMENT)))

    judging = judge(messages)

    assert judging == Judging(
        JUDGEMENT, Usage(input_tokens=12, output_tokens=34, cache_read_tokens=1000)
    )
    assert messages.request == {
        "model": "claude-sonnet-5-5",
        "max_tokens": 4096,
        "system": [{"type": "text", "text": "The rubric.", "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": "The exchange."}],
        "output_format": Judgement,
        "output_config": {"effort": "low"},
    }


@pytest.mark.parametrize("stop_reason", ["refusal", "max_tokens"])
def test_a_judge_that_refuses_or_is_cut_short_returns_no_judgement(stop_reason: str) -> None:
    judging = judge(Messages(response(stop_reason)), model="a-judge")

    assert judging.judgement is None
    assert judging.usage.output_tokens == 34

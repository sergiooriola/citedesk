"""Claude, through Anthropic's API, as the assistant's model and as the exam's judge."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import anthropic
from pydantic import BaseModel, ValidationError

from citedesk.exam.judge import Judgement, Judging
from citedesk.model import Draft, Generation, Usage

if TYPE_CHECKING:
    from collections.abc import Sequence

    from anthropic.types import MessageParam, TextBlockParam

    from citedesk.model import Effort, Outcome, Turn

_OUTCOMES: dict[str, Outcome] = {"refusal": "refused", "max_tokens": "truncated"}


@dataclass(frozen=True)
class _Claude:
    """One Claude model asked for output in a fixed shape."""

    client: anthropic.AsyncAnthropic
    model: str
    effort: Effort
    max_output_tokens: int

    async def parse[Shape: BaseModel](
        self, instructions: str, messages: list[MessageParam], shape: type[Shape]
    ) -> tuple[Outcome, Shape | None, Usage]:
        """Send one request and return how it ended, the parsed output and the usage.

        The instructions are marked for caching: they are the same for every request of a
        deployment, and a cached read costs a fraction of a fresh one. The output is parsed
        here rather than by the SDK's `messages.parse`, which raises on the half-written JSON
        of a response cut short before it can say that the response was cut short.
        """
        system: list[TextBlockParam] = [
            {"type": "text", "text": instructions, "cache_control": {"type": "ephemeral"}}
        ]
        try:
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=self.max_output_tokens,
                system=system,
                messages=messages,
                output_config={
                    "effort": self.effort,
                    "format": {"type": "json_schema", "schema": anthropic.transform_schema(shape)},
                },
            )
        except anthropic.APIError:
            # Rate limits, spend limits, outages and bad requests all end the same way for
            # the caller. The SDK has already retried what can be retried.
            return "failed", None, Usage()

        usage = Usage(
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            cache_read_tokens=response.usage.cache_read_input_tokens or 0,
            cache_write_tokens=response.usage.cache_creation_input_tokens or 0,
        )
        outcome = _OUTCOMES.get(response.stop_reason or "", "completed")
        if outcome != "completed":
            return outcome, None, usage
        text = next((block.text for block in response.content if block.type == "text"), None)
        if text is None:
            return "failed", None, usage
        try:
            return "completed", shape.model_validate_json(text), usage
        except ValidationError:
            return "failed", None, usage


class AnthropicModel:
    """A Claude model that returns drafts in the shape the assistant checks."""

    def __init__(
        self,
        client: anthropic.AsyncAnthropic | None = None,
        *,
        model: str = "claude-haiku-5-5",
        effort: Effort = "low",
        max_output_tokens: int = 2048,
    ) -> None:
        """Choose the model and how much it may spend on one reply.

        Args:
            client: The API client. By default it reads the key from `ANTHROPIC_API_KEY`.
            model: The model identifier.
            effort: How much the model reasons before it replies. Reasoning is billed as
                output, so a higher effort costs more.
            max_output_tokens: The ceiling for one reply, reasoning included. A draft cut
                short by it is rejected, never sent.
        """
        self._claude = _Claude(
            client or anthropic.AsyncAnthropic(), model, effort, max_output_tokens
        )

    async def generate(self, *, instructions: str, turns: Sequence[Turn]) -> Generation:
        """Ask Claude for a draft."""
        messages: list[MessageParam] = [{"role": turn.role, "content": turn.text} for turn in turns]
        outcome, draft, usage = await self._claude.parse(instructions, messages, Draft)
        return Generation(outcome, draft, usage)


class AnthropicJudge:
    """A Claude model that judges the replies of an exam."""

    def __init__(
        self,
        client: anthropic.AsyncAnthropic | None = None,
        *,
        model: str = "claude-sonnet-5-5",
        effort: Effort = "low",
        max_output_tokens: int = 4096,
    ) -> None:
        """Choose the judge and how much it may spend on one judgement.

        Args:
            client: The API client. By default it reads the key from `ANTHROPIC_API_KEY`.
            model: The model identifier. It should be a different model from the one under
                examination, and at least as capable.
            effort: How much the judge reasons before it answers.
            max_output_tokens: The ceiling for one judgement, reasoning included.
        """
        self._claude = _Claude(
            client or anthropic.AsyncAnthropic(), model, effort, max_output_tokens
        )

    async def judge(self, *, instructions: str, exchange: str) -> Judging:
        """Ask Claude for the judgement of one exchange."""
        messages: list[MessageParam] = [{"role": "user", "content": exchange}]
        _, judgement, usage = await self._claude.parse(instructions, messages, Judgement)
        return Judging(judgement, usage)

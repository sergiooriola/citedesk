"""Claude, through Anthropic's API, as the assistant's model."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

import anthropic

from citedesk.model import Draft, Generation, Usage

if TYPE_CHECKING:
    from collections.abc import Sequence

    from anthropic.types import MessageParam, TextBlockParam

    from citedesk.model import Outcome, Turn

Effort = Literal["low", "medium", "high", "xhigh", "max"]

_OUTCOMES: dict[str, Outcome] = {"refusal": "refused", "max_tokens": "truncated"}


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
        self._client = client or anthropic.AsyncAnthropic()
        self._model = model
        self._effort: Effort = effort
        self._max_output_tokens = max_output_tokens

    async def generate(self, *, instructions: str, turns: Sequence[Turn]) -> Generation:
        """Ask Claude for a draft.

        The instructions are marked for caching: they are the same for every conversation of
        a deployment, and a cached read costs a tenth of a fresh one.
        """
        system: list[TextBlockParam] = [
            {"type": "text", "text": instructions, "cache_control": {"type": "ephemeral"}}
        ]
        messages: list[MessageParam] = [{"role": turn.role, "content": turn.text} for turn in turns]
        try:
            response = await self._client.messages.parse(
                model=self._model,
                max_tokens=self._max_output_tokens,
                system=system,
                messages=messages,
                output_format=Draft,
                output_config={"effort": self._effort},
            )
        except anthropic.APIError:
            # Rate limits, spend limits, outages and bad requests all end the same way for
            # the person: the fixed message. The SDK has already retried what can be retried.
            return Generation("failed")

        usage = Usage(
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            cache_read_tokens=response.usage.cache_read_input_tokens or 0,
            cache_write_tokens=response.usage.cache_creation_input_tokens or 0,
        )
        outcome = _OUTCOMES.get(response.stop_reason or "", "completed")
        if outcome != "completed":
            return Generation(outcome, usage=usage)
        if response.parsed_output is None:
            return Generation("failed", usage=usage)
        return Generation("completed", response.parsed_output, usage)

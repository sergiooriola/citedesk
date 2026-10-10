"""Ask the example assistant one question from the command line.

Run it with your API key in `.env`:

    uv run --env-file .env python examples/ask.py "What time does school start?"
"""

import asyncio
import sys
from pathlib import Path

from citedesk import Assistant, Knowledge, Turn
from citedesk.anthropic_model import AnthropicModel

RULES = (
    "Fees and payment terms are reserved for the office: never state an amount.",
    "Never say whether a place is available, and never promise admission.",
)
FALLBACK = (
    "I can't answer that here. The school office can help: call 01234 567890 "
    "or write to office@riverside-academy.example."
)


async def main(question: str) -> None:
    """Print the assistant's reply, the entries it cited and what the call consumed."""
    assistant = Assistant(
        model=AnthropicModel(),
        knowledge=Knowledge.from_jsonl(Path(__file__).with_name("riverside-academy.jsonl")),
        office_entry_ids=["OFFICE-01"],
        fallback=FALLBACK,
        rules=RULES,
    )
    reply = await assistant.reply([Turn("user", question)])
    print(f"[{reply.kind}] {reply.text}")  # noqa: T201
    print(f"entries: {', '.join(reply.entry_ids) or '-'}  rejection: {reply.rejection}")  # noqa: T201
    print(f"usage: {reply.usage}")  # noqa: T201


if __name__ == "__main__":
    asyncio.run(main(" ".join(sys.argv[1:]) or "What time does school start?"))

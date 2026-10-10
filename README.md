# citedesk

[![CI](https://github.com/sergiooriola/citedesk/actions/workflows/ci.yml/badge.svg)](https://github.com/sergiooriola/citedesk/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

An assistant engine that answers only from entries you have approved, cites the entry behind
every answer, and hands everything else to a person.

> [!WARNING]
> **Pre-alpha.** Nothing here is usable yet. The repository is public from its first commit so
> that the way it is built is part of the record. The [roadmap](#roadmap) says what exists.

## Why

A school office, a clinic's front desk or an admissions team answers the same questions every
day. A language model can take that work, but only if it never makes anything up: a wrong
price, an invented deadline or a promise nobody approved costs more than no answer at all.

citedesk is built around that constraint. It is meant for a small, reviewed body of knowledge
and a narrow job, not for open-ended chat.

## Design goals

- **Closed knowledge.** The assistant answers from a list of question-and-answer entries that
  a person has reviewed. It does not browse, and it does not fill gaps with what the model
  happens to know.
- **Every answer cites its entries.** The model returns its text together with the identifiers
  of the entries it used. A reply that cites nothing valid is not sent.
- **Handing off is the default.** Whatever the entries do not cover, or the organisation keeps
  for a person, goes to that person with the contact details. "Ask the office" is a correct
  answer.
- **Examined before it is exposed.** A set of cases states what the assistant must answer, what
  it must hand off and what must never appear in a reply. A release that does not pass does
  not ship.
- **Bounded cost.** Message size, turns per conversation, requests per connection and a daily
  budget are capped, so abuse can switch the assistant off for a day but cannot run up a bill.
- **Fits into what is already there.** Creating a lead, recognising staff and recording
  analytics go through small adapters, so the assistant uses the organisation's existing
  systems instead of replacing them.

## How it works today

```python
import asyncio
from pathlib import Path

from citedesk import Assistant, Knowledge, Turn
from citedesk.anthropic_model import AnthropicModel

assistant = Assistant(
    model=AnthropicModel(),  # reads ANTHROPIC_API_KEY
    knowledge=Knowledge.from_jsonl(Path("examples/riverside-academy.jsonl")),
    office_entry_ids=["OFFICE-01"],
    fallback="I can't answer that here. Please call the office on 01234 567890.",
    rules=["Fees are reserved for the office: never state an amount."],
)

reply = asyncio.run(assistant.reply([Turn("user", "What time does school start?")]))
print(reply.kind, reply.entry_ids, reply.text)
# answer ('DAY-01',) Lessons run from 8:45 to 15:30, Monday to Friday...
```

The model has to return its text together with the identifiers of the entries it used. The
assistant sends that text only if every identifier exists and, for a hand-off, at least one
is an office entry. Anything else — an answer with no entry, an unknown identifier, a
refusal, a reply cut short, an API error — is replaced by the deployment's fixed `fallback`
message, and `reply.rejection` says why.

That check proves a reply points at real entries, not that it is faithful to them. Showing
that is the job of the exam runner, which is next on the roadmap.

`examples/ask.py` runs one question against an invented school:

```sh
uv run --env-file .env python examples/ask.py "Is there a uniform?"
```

## Roadmap

- [x] Project scaffolding: packaging, linting, typing, tests and continuous integration
- [x] Core: answer from a knowledge file with cited entries, or hand off
- [ ] Exam runner: cases, repeated runs and a pass mark
- [ ] HTTP service with rate limits and a daily budget
- [ ] Web chat widget
- [ ] Adapters: lead creation, staff sign-in, analytics
- [ ] Conversation records, cost per conversation and retention

## Development

citedesk uses [uv](https://docs.astral.sh/uv/) for environments, dependencies and builds.

```sh
uv sync                      # create the environment from uv.lock
uv run pre-commit install    # run the checks before each commit

uv run ruff format           # format
uv run ruff check            # lint
uv run mypy                  # type-check
uv run pytest --cov          # test, with coverage
```

[CONTRIBUTING.md](CONTRIBUTING.md) has the conventions, and [SECURITY.md](SECURITY.md) says
how to report a vulnerability.

## License

[MIT](LICENSE)

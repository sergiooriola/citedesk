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

A deployment is one JSON file: where the entries are, which of them say how to reach the
office, the fixed message for when a reply cannot be trusted, the organisation's own rules,
the model and effort it runs with, and the limits of [its service](#the-service). [`examples/riverside-academy`](examples/riverside-academy)
has one for an invented school.

```python
import asyncio
from pathlib import Path

from citedesk import Deployment, Turn
from citedesk.anthropic_model import AnthropicModel

deployment = Deployment.from_file(Path("examples/riverside-academy/deployment.json"))
assistant = deployment.assistant(AnthropicModel())  # reads ANTHROPIC_API_KEY

reply = asyncio.run(assistant.reply([Turn("user", "What time does school start?")]))
print(reply.kind, reply.entry_ids, reply.text)
# answer ('DAY-01',) Lessons run from 8:45 to 15:30, Monday to Friday...
```

The model has to return, in this order, the language the person wrote in, whether it is
answering or handing off, its text, and the identifiers of the entries the text draws on.
The assistant sends that text only if every identifier exists and, for a hand-off, at least
one is an office entry. Anything else — an answer with no entry, an unknown identifier, a
refusal, a reply cut short, an API error — is replaced by the deployment's fixed `fallback`
message, and `reply.rejection` says why.

The same from the command line, with your API key in `.env`:

```sh
uv run --env-file .env citedesk ask examples/riverside-academy/deployment.json "Is there a uniform?"
```

## The exam

That check proves a reply points at real entries, not that it is faithful to them. The exam
measures the rest. A cases file states, one case per line, what a person may write and what
has to happen:

```json
{"id": "KNOWN-01", "ask": "What time does school start?", "expect": "answer", "entry_ids": ["DAY-01"]}
{"id": "RESERVED-01", "ask": "How much are the fees?", "expect": "hand_off", "never": ["£", "per term"]}
{"id": "KNOWN-04", "ask": "¿Pueden llevar el móvil a clase?", "expect": "answer", "entry_ids": ["DAY-03"], "language": "es"}
```

```sh
uv run --env-file .env citedesk exam \
  examples/riverside-academy/deployment.json examples/riverside-academy/cases.jsonl
```

`expect` can also be `any`, for a message where answering and handing off are both right
and only what the reply says matters. An answer case accepts a hand-off that cites one of
its entries: the reply gave the information and sent the person on to the office as well.

Every case is put to the assistant several times (three by default), because a model does
not reply the same way twice. Each reply is graded in two steps:

1. **By rule.** Whether it answered or handed off as the case expects, whether it cites one
   of the expected entries, and whether any phrase the case forbids appears in it, as whole
   words: `85` is not found in a telephone number that contains 859.
2. **By a judge.** A second, stronger model breaks the reply into its claims and names the
   entries that state each one. A claim no entry states is an invented fact. The judge also
   says which language the reply is in. Since one invented fact fails the whole exam, the
   judge has to find it on two separate readings.

| Failure | Meaning | Critical |
| --- | --- | --- |
| `forbidden_text` | The reply contains text the case forbids | yes |
| `unsupported_claim` | The reply states something no entry states | yes |
| `answered` | It answered what it had to hand off | |
| `handed_off` | It handed off what it had to answer | |
| `fell_back` | Its draft was rejected and the fixed message was sent | |
| `wrong_entries` | It cited none of the entries the case expects | |
| `uncited_claim` | A claim is stated only by entries the reply did not cite | |
| `wrong_language` | The reply is not in the language the case sets | |

The exam is **passed** only with no critical failure in any run and at least 95 % of the
runs free of failures; the command then exits with 0. It exits with 1 when the exam is
failed and with 2 when a model call failed and some runs could not be graded, in which case
the exam has to be repeated. `--report` writes every reply and every judgement to a JSON
file.

### Measuring the judge

A judge is a model too: one that calls a clean reply faulty stops a good assistant, and one
that misses an invented fact lets a bad one through. So the judge is measured before it is
trusted, against replies written by hand whose faults are known:

```json
{"id": "CLEAN-04", "ask": "Is there a swimming pool?", "reply": "I don't have information about a swimming pool. The school office can tell you: call 01234 567890.", "language": "en"}
{"id": "INVENTED-05", "ask": "What's the phone number?", "reply": "You can call the office on 01234 567899.", "language": "en", "invented": ["567899"]}
```

```sh
uv run --env-file .env citedesk calibrate \
  examples/riverside-academy/deployment.json examples/riverside-academy/judge-samples.jsonl
```

Each sample is read three times. A reading is right when the judge finds every invented
fact, flags nothing else and names the language. The command exits with 0 only if every
reading is right, so it can run whenever the judge's instructions or model change.

On the 27 samples of the example, Claude Sonnet 5.5 got 81 readings out of 81 right. Claude
Haiku 5.5, the model under examination, got 68: it raised false alarms on clean replies and
missed the same invented fact on every reading, which is why the judge is a different and
stronger model.

Passing its own cases does not prove an assistant: instructions tuned against a set of
cases fit that set. Keep adding the questions real people ask, and re-run the exam whenever
the entries, the rules or the model change.

## The service

`citedesk serve` puts a deployment's assistant behind an HTTP interface. It is meant to sit
behind the organisation's own web server, never to be reached straight from a browser:

```sh
CITEDESK_SERVICE_KEY=... uv run --env-file .env citedesk serve examples/riverside-academy/deployment.json
```

```sh
curl http://127.0.0.1:8000/v1/replies \
  -H "X-Citedesk-Key: $CITEDESK_SERVICE_KEY" -H "X-Citedesk-Client: 203.0.113.7" \
  -H "Content-Type: application/json" \
  -d '{"turns": [{"role": "user", "text": "What time does school start?"}]}'
# {"kind":"answer","text":"Lessons run from 8:45 to 15:30, Monday to Friday. The gates open at 8:15.",
#  "entry_ids":["DAY-01"],"language":"en","reason":null}
```

The service holds no conversations in memory: the browser sends the whole one each time,
ending with the person's message.

### Behind a web server

The browser talks to the organisation's website, and the web server passes the request on
with two headers the browser cannot be trusted to set:

| Header | What it carries |
| --- | --- |
| `X-Citedesk-Key` | The secret in `CITEDESK_SERVICE_KEY`. Without it, `401`. |
| `X-Citedesk-Client` | A value that tells one visitor from another, such as their address. Requests are rate-limited by it. |

The web server has to set both, replacing whatever the request brought: a browser that
could choose its own client value would have no rate limit. With Caddy:

```caddyfile
@assistant {
	method POST
	path /assistant/v1/replies
}
handle @assistant {
	request_body {
		max_size 64KB
	}
	uri strip_prefix /assistant
	reverse_proxy 127.0.0.1:8000 {
		# Set, not added: whatever the browser sent under these names is replaced.
		header_up X-Citedesk-Client {client_ip}
		header_up X-Citedesk-Key {$CITEDESK_SERVICE_KEY}
	}
}
```

### Limits and budget

What stands between the public and the bill is in the deployment file:

```json
"limits": {
  "message_chars": 600,
  "turns": 20,
  "client_requests_per_minute": 6,
  "requests_per_minute": 60,
  "daily_budget_usd": 1.0
},
"prices": {"input": 0.10, "output": 0.50, "cache_read": 0.01, "cache_write": 0.125}
```

Every reply's cost is worked out from its token usage at the deployment's `prices`, in US
dollars per million tokens, and added to the day's total. Once the total reaches
`daily_budget_usd`, the model is not called again until the next UTC day: abuse can switch
the assistant off for a day, not run up a bill. The limits live in memory, so the service
runs as a single process, and the provider's own spend limit stays as the backstop.

### Restricting who may use it

A deployment is open to whoever its web server lets in, unless it has an `access` section.
With one, only people signed in with an identity provider and named on a list get a reply:

```json
"access": {
  "issuer": "https://id.example/auth",
  "jwks_url": "https://id.example/auth/.well-known/jwks.json",
  "emails": ["staff@riverside-academy.example"]
}
```

The person signs in on the organisation's website, and the browser sends the token the
provider gave it as `Authorization: Bearer ...`. The service checks the token's signature
against the provider's published keys, its issuer and its expiry, and then looks for its
`email` or its `sub` on the list (`emails` and `subjects`). Tokens signed with a shared
secret are refused, whatever their header says. This is how an assistant is tried by its
own staff before anyone else sees it.

### Keeping what is said

By default the service keeps nothing: only the log line of each reply, without its text. A
deployment that wants to read what people ask, to see what its entries are missing, says
where each exchange goes:

```json
"records": {
  "url": "https://records.example/exchanges",
  "headers": {"apikey": "a-public-key"},
  "key_header": "X-Records-Key",
  "fields": {"asked": "question", "replied": "reply"}
}
```

After each reply, the service posts one JSON object there with `at`, `conversation`, `turn`,
`asked`, `replied`, `kind`, `entry_ids`, `reason`, `language`, `usd` and `ms`. `fields` gives
them other names when the receiver has its own, and the secret for `key_header` comes from
`CITEDESK_RECORDS_KEY`. That is enough for a database with an HTTP interface.

- `conversation` is whatever the browser sends under that name with the conversation: a
  random value, new for each one, so that its exchanges can be read together. It identifies
  nobody, and the client's address is never part of a record.
- A record is sent once the person has their reply, and one that cannot be delivered is
  logged and lost: a reply never waits for its record or fails with it.
- What people write is personal data wherever it ends up. How long records are kept, and
  who may read them, is for the organisation to decide and to tell the people who write.

### Responses

| Situation | Response |
| --- | --- |
| No key, or a wrong one | `401`, code `wrong_key` |
| A message or a conversation over the limits, or turns out of order | `422` with a `code` |
| A client over its allowance, or all clients over theirs | `429` with `Retry-After` |
| Access is restricted and there is no valid token | `401`, code `sign_in_required` |
| Access is restricted and the person is not on the list | `403`, code `not_allowed` |
| The day's budget is spent | `200` with the fallback and `"reason": "budget_spent"` |
| The model's draft cannot be trusted, or the model fails | `200` with the fallback and the reason |

The log has one line per reply with its kind, its cost and how long it took, and never the
text of a message. `GET /healthz` answers without a key, for whatever watches the service.

## Roadmap

- [x] Project scaffolding: packaging, linting, typing, tests and continuous integration
- [x] Core: answer from a knowledge file with cited entries, or hand off
- [x] Exam runner: cases, repeated runs, a judge and a pass mark
- [x] Judge calibration as a command, with its samples in the repository
- [x] HTTP service with rate limits and a daily budget
- [ ] Web chat widget
- [x] Access restricted to signed-in people on a list
- [ ] Adapters: lead creation, analytics
- [x] Records of each exchange, with its cost, sent to the organisation's own store

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

# Contributing

Thanks for taking the time. citedesk is at an early stage, so the most useful contributions
right now are issues: a use case the design does not cover, or a flaw in it.

## Setting up

You need [uv](https://docs.astral.sh/uv/getting-started/installation/). It installs the right
Python for you.

```sh
git clone https://github.com/sergiooriola/citedesk.git
cd citedesk
uv sync
uv run pre-commit install
```

## Before you open a pull request

Continuous integration runs these same commands and all of them have to pass:

```sh
uv run ruff format --check
uv run ruff check
uv run mypy
uv run pytest --cov
```

## Conventions

- **One concern per pull request**, with tests for what it changes.
- **Commit messages** follow [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/):
  `feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `chore:`, `ci:`.
- **Code, comments and documentation are in English.**
- **Public functions and classes have type hints and a docstring** in
  [Google style](https://google.github.io/styleguide/pyguide.html#38-comments-and-docstrings).
- **Dependencies change through `uv add` and `uv remove`**, so `uv.lock` stays in step.
- **User-visible changes get a line in [CHANGELOG.md](CHANGELOG.md)** under "Unreleased".

## What never goes in the repository

- Secrets. `.env` is ignored; `.env.example` lists the variables without their values.
- Data or content of a real organisation. Examples and tests use invented data.

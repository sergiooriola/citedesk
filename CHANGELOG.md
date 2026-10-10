# Changelog

All notable changes to this project are recorded in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- The core assistant: it answers from a file of reviewed entries, the model returns the
  entries behind each reply, and a reply whose citations do not hold is replaced by a fixed
  fallback message. Claude is the first supported model, through Anthropic's API.
- Project scaffolding: packaging with uv, linting and formatting with Ruff, strict type
  checking with mypy, tests with pytest and continuous integration on GitHub Actions.

[Unreleased]: https://github.com/sergiooriola/citedesk/commits/main

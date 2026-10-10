# Changelog

All notable changes to this project are recorded in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- The service: `citedesk serve` puts a deployment behind an HTTP interface with a key, a
  rate limit for each client and for all of them, bounds on messages and conversations, and
  a daily budget in dollars after which every reply is the fallback. The limits and the
  model's prices are part of the deployment file.
- Judge calibration: `citedesk calibrate` has the judge read replies with known faults and
  reports every invented fact it missed and every false alarm it raised. The example
  deployment has 27 samples.
- The exam: `citedesk exam` puts every case of a cases file to the assistant several times,
  grades each reply by rule and with a second model that checks it claim by claim against
  the entries, and passes only with no forbidden or invented content and a pass rate over
  the pass mark.
- Deployment files: one JSON file holds where the entries are, the office entries, the
  fallback message, the organisation's rules, and the model and effort. `citedesk ask` puts
  one question to a deployment.

- The core assistant: it answers from a file of reviewed entries, the model returns the
  entries behind each reply, and a reply whose citations do not hold is replaced by a fixed
  fallback message. Claude is the first supported model, through Anthropic's API.
- Project scaffolding: packaging with uv, linting and formatting with Ruff, strict type
  checking with mypy, tests with pytest and continuous integration on GitHub Actions.

### Changed

- The judge accepts a claim that applies an entry to the person's own case when the case
  falls within what the entry says, and still rejects one that stretches the entry.
- The model now states the language of the person's message before it writes, and
  `Reply.language` carries it. With the entries in one language, a small model otherwise
  tends to reply in that language whatever the person wrote in.
- The instructions are stricter about what the exam showed going wrong: a hand-off does
  not explain who decides or why, conditions keep the entries' own words, nothing is
  denied because the entries are silent about it, and every entry behind a passing remark
  is cited.

[Unreleased]: https://github.com/sergiooriola/citedesk/commits/main

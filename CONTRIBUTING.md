# Contributing Guide for DreamHouse

Thank you for your interest in **DreamHouse**, a benchmark for evaluating AI
models on timber-frame structure generation. This document describes the
governance model for the project and how to engage with it.

## Governance Model

### Published but not supported

DreamHouse is open-sourced because it may contain useful or interesting
code and ideas for the broader research and open-source community.
Occasional work may happen on the repository, but we are not actively
soliciting contributions, and there is no commitment to reviewing or
merging external pull requests on a particular timeline.

Issues and pull requests may be read but will not necessarily receive a
response. If a PR is clearly valuable and self-contained we may merge it,
but in general the primary way to adapt DreamHouse to your needs is to
fork it.

## Getting in touch

- **Bugs, questions, and discussion:** please open a
  [GitHub Issue](https://github.com/SalesforceAIResearch/DreamHouse/issues).

Before filing a new issue, please search existing issues (open and closed)
in case the topic has already been discussed.

## Issues

- **Bug reports:** describe what you expected, what happened, and the
  exact steps and environment (OS, Python version, Blender version)
  needed to reproduce it. Small reproducible examples are always
  appreciated.
- **Enhancement requests / ideas:** feel free to open an issue to describe
  the problem you're trying to solve. Given the project's published-but-
  not-supported model, please understand that requests may not be acted
  on even if they are reasonable.
- **Security-sensitive reports:** do not open a public issue. Contact the
  maintainers privately via the email address in [SECURITY.md](SECURITY.md).

## Pull requests

PRs are welcome but not guaranteed to be reviewed or merged. If you would
like to submit a change:

1. **Open an issue first** describing what you intend to change, unless
   the fix is obviously trivial (typos, small documentation fixes).
2. **Fork** the repository and create a topic branch off `main`.
3. Keep the change **small and focused**; avoid mixing unrelated changes
   into a single PR.
4. **Commit** with clear, descriptive messages and reference any related
   issue number.
5. **Open a pull request** against `main` in
   `SalesforceAIResearch/DreamHouse` and describe the motivation and
   scope of the change.
6. **Sign the Salesforce CLA.** You will be prompted to do so the first
   time you open a PR. This is required before any contribution can be
   merged (see below).

### Contribution expectations

- Follow the style and conventions of the surrounding code.
- Do not introduce heavy new dependencies without discussion. Prefer
  Apache-2.0, BSD-3-Clause, MIT, ISC, and MPL-licensed libraries.
- If you change behavior that is documented in `README.md`, update the
  documentation in the same PR.
- Smoke-test your change against the local server and the bundled
  examples under [`examples/`](examples/). There is no formal test
  suite in this repository at this time.

## Contributor License Agreement ("CLA")

In order for us to accept your pull request, we need you to submit a CLA.
You only need to do this once to contribute to any Salesforce open source
project.

Complete your CLA here: https://cla.salesforce.com/sign-cla

## Code of Conduct

All interactions in this project — issues, pull requests, discussions,
and chat — are governed by our
[Code of Conduct](CODE_OF_CONDUCT.md). Please take a moment to read it.

## License

By contributing your code, you agree to license your contribution under
the terms of the project [LICENSE](LICENSE.txt) and to have signed the
[Salesforce CLA](https://cla.salesforce.com/sign-cla).

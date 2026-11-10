# Contributing to GhostMind

First off — thank you. Every bug report, idea, and line of code makes
GhostMind better. This guide explains how to get involved smoothly.

By participating, you agree to the [Code of Conduct](CODE_OF_CONDUCT.md).

## Ways to contribute

| You want to… | Do this |
|---|---|
| **Report a bug** | Use the in-app **Feedback** tab (Settings → Feedback) for quick reports, or [open an issue](https://github.com/dasunjlk/GhostMind/issues) for anything you want to track. |
| **Suggest a feature** | [Open an issue](https://github.com/dasunjlk/GhostMind/issues) starting with "Suggestion:" — describe the problem it solves, not just the solution. |
| **Fix or improve code** | Read the workflow below and open a pull request against `dev`. |
| **Improve docs** | PRs against `dev` are welcome — keep the tone friendly and non-technical where possible. |
| **Report a security issue** | **Never** in a public issue — use the [Security tab](https://github.com/dasunjlk/GhostMind/security). See [SECURITY.md](SECURITY.md). |

## Reporting a bug well

A great bug report includes:

1. **GhostMind version** — Settings → About, or from the release tag
2. **Windows version**
3. **What you did** and **what you expected** vs **what happened**
4. **Relevant logs** — `ghostmind.log` lives in
   `%LOCALAPPDATA%\GhostMind\data` (installed) or the repository root
   (source runs). Remove anything sensitive before pasting.

The in-app Feedback tab already scrubs API keys and personal paths — but
please double-check anything you paste publicly.

## Development setup

Full details live in the README's **Developer setup** section. In short:

1. **Requirements**: Python 3.11+, Git, and Tesseract OCR on `PATH`
   (`choco install tesseract`).
2. Clone, create a virtual environment, and install:
   `pip install -r requirements.txt`
3. Run the app: `python main.py`
4. Before you finish: `ruff check .` and `pytest -q` must both pass.

## How this repository works

- **Branches**: feature work happens on `feat/*` branches created from
  `dev`; fixes use `fix/*`, build/CI changes use `build/*` or `chore/*`,
  and docs use `docs/*`. Pull requests target **`dev`** — `main` receives
  releases only.
- **Commits**: small and focused, imperative style — e.g.
  `feat(settings): add a model discovery dropdown`,
  `fix(ui): stop late answers from painting into the next bubble`.
- **Quality gates**: every PR must keep `ruff check .` clean and
  `pytest -q` green. The suite is fully offline — tests never touch the
  network, real keyrings, or the file system outside temp directories.
  Follow the existing patterns (fake transports, monkeypatched capture,
  temp state files).
- **Style**: the ruff configuration in `pyproject.toml` is the source of
  truth (line length 100, Python 3.11 target). The deliberately broad
  exception handling is a documented resilience policy — a desktop app must
  never crash on a background failure.

## Ground rules for changes

- **Never commit secrets**: no `.env`, no API keys, no tokens — not even
  examples that look real. `.env` is gitignored; keys belong in Windows
  Credential Manager at runtime.
- **Respect the privacy stance**: no new telemetry, no data collection, and
  anything sent to Sentry must go through the existing scrubbing path in
  `utils/error_reporter.py`.
- **Keep the offline test discipline**: if your change needs a network call
  in a test, fake it (see `tests/test_updater.py` and
  `tests/test_error_reporter.py` for the patterns).
- **Don't re-enable hidden subsystems casually** — hidden features (like the
  audio stack) are disabled deliberately and excluded from the installer
  build; changes to them should keep that state unless the maintainer agrees
  otherwise.

## Pull requests

1. Fork (or branch) from the latest `dev`.
2. Make your change with tests that prove it.
3. Update `README.md` / docs if user-facing behavior changed.
4. Open the PR against `dev` with a short description of the **what** and
   the **why**.

Small, focused PRs get reviewed and merged fastest.

## Licensing

By contributing, you agree that your contributions are licensed under the
MIT License that covers this project.

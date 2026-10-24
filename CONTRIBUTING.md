# Contributing to pi-wave-kit

This repo extracts hard-won, production-tested orchestration code (budget-capped concurrency,
real cost reading from `pi` session files, escalation protocol). Changes here affect every
project that depends on it, so the bar is: **don't regress a real production fix that's already
in a test or a docstring** (several modules have comments like "real bug fixed 2026-10-16" --
those are load-bearing, not incidental).

## When to open an issue vs. just fixing it

- **Open an issue first** for anything that is more than a one-file, low-risk fix: a new
  capability (a new module, a new CLI, a new wrapper), a behavior change to `wave.py`,
  `run_pi.py`, `escalate.py`, or `coordinator.py` (the stable, documented API other projects
  import), or anything that will take more than one commit to land.
- **Just fix it directly** (one commit, reference it in the message) for: typos, docstring
  fixes, a clearly-isolated test bug, a one-line defensive fix with an obvious correct answer.
- **Group related work under a milestone** when you're about to do several issues that only
  make sense together (e.g. "add isolation + a CLI + document the workflow" as one body of
  work). Create the milestone first, then file each piece as its own issue under it, so
  progress is visible issue-by-issue rather than only at the end.

## Commits and PRs

- Trunk-based: this repo has a single `master` branch and does not currently require PRs for
  solo work. Commit directly to `master`, but commit **as you go** (one commit per coherent
  change), never one giant commit for a whole body of work.
- Every commit that finishes an issue references it: `Fixes #N` / `Closes #N` in the commit
  message body, so pushing the commit closes the issue automatically.
- Write real commit messages (what changed and why), not just "fix stuff".
- End commits made by an AI agent with the attribution trailer it was given for the session
  (e.g. `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>` plus a `Claude-Session:` line).

### Commit message format (checked by a hook, not just hoped for)

```
<Imperative, capitalized subject, no trailing period, <= 72 chars>

<Body: why this change, not just what -- the real bugs this project's own history fixes
read like "real bug fixed 2026-10-16: ..." for a reason; a future reader needs the why more
than the diff.>

Fixes #N        <- only if this commit closes an issue
Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>   <- only for AI-agent commits
Claude-Session: https://claude.ai/code/session_...
```

- Subject: imperative mood ("Add", "Fix", "Document", not "Added"/"Adding"), a heading not a
  sentence (no trailing period), <= 72 characters. A `module: ` prefix is fine when the change
  is scoped to one file/module (e.g. `run_wave: accumulate a retried job's cost across attempts`).
- Blank line, then a body explaining why whenever the subject alone doesn't make that obvious.
- The mechanical parts of this (non-empty subject, <= 72 chars, no trailing period, blank line
  before the body) are enforced by `scripts/check_commit_message.py`, wired in as a
  `pre-commit` `commit-msg` hook -- see "Local pre-commit checks" below. The "why, not just
  what" part isn't mechanically checkable; that's on the author/reviewer.

## What a change needs before it's mergeable / "done"

1. **Tests pass**: `pytest` from the repo root (there is a `.venv`; use it, or `uv pip install
   -e .[dev]` into your own). New behavior needs new tests, following the patterns already
   established in `tests/` -- in particular the `fake_pi` fixture in `tests/conftest.py`
   (a fake `pi` executable on `PATH` that writes a real session JSONL) is the standard way to
   exercise anything that spawns a `pi` process. Don't mock around it; use it.
2. **README updated** if the change is user-visible (a new public function, a new CLI, a new
   parameter on an existing one). The README's "Quick start" and "Status" sections should stay
   accurate.
3. **Smoke-tested manually, not just unit-tested**, for anything that actually spawns a real
   process or touches the real filesystem/cgroup machinery (a CLI entrypoint, the
   `systemd-run` wrapper). Unit tests here use a fake `pi`; that's necessary but not
   sufficient -- actually invoke the real thing once against a trivial case before calling it
   done. This mirrors the sibling `agentic-reasoning-translator` project's rule: a wrapper
   around process-spawning that silently does nothing (see that project's issue #1 / ERRATA
   #43) is worse than no wrapper, because it looks like it's running.
4. **CI is green**: `.github/workflows/ci.yml` runs on every push and PR -- installs with `uv`
   (not `pip`, this project family's standing rule), runs `ruff check .`, then the full `pytest`
   suite, and fails the build on either. Check the Actions tab (or `gh run list`) before
   considering a push done; a red run is not a merged/finished change just because it's on
   `master`.
5. **Lint is clean**: `ruff check .` (config in `pyproject.toml`'s `[tool.ruff]` -- `line-length
   = 160`, chosen to match this codebase's own already-long narrative lines rather than forcing
   a disruptive repo-wide reformat; rule set is `E`/`F`/`I` -- pycodestyle + pyflakes + import
   sorting -- real-bug-catching, not opinionated style). `ruff format` is installed and
   available (`ruff format .`) but **not** enforced in CI or pre-commit: a first real run
   reformats ~18 files against this project's intentionally dense, comment-heavy style, and
   that's a decision for the repo owner to make deliberately, not a side effect of adding CI.

## Local pre-commit checks

Before a commit is allowed locally (not just after pushing, in CI): the same `ruff check` and
the full `pytest` suite, plus the commit-message format check above. Uses the
[`pre-commit`](https://pre-commit.com) framework (config: `.pre-commit-config.yaml`, tracked in
git) rather than a hand-written `.git/hooks/pre-commit` script, because the framework's config
is a normal tracked file every clone gets automatically -- a raw hook script lives only in
`.git/` and has to be manually copied into each working copy, which defeats the point for a repo
other agents and the owner both clone fresh.

**Install once per clone:**
```bash
uv venv && uv pip install -e ".[dev]"         # needed anyway; the hooks run THIS venv's ruff/pytest
uv tool install pre-commit                     # or: uv pip install pre-commit
pre-commit install                            # runs ruff + pytest before each commit
pre-commit install --hook-type commit-msg     # checks the commit message format
```
The lint/test hooks call `.venv/bin/ruff`/`.venv/bin/pytest` directly (not whatever `ruff`/
`pytest` happens to be first on `PATH`) so they run against this project's real dependencies,
not a bare global install missing `llm-ledger-client` etc.

**Run without committing:** `pre-commit run --all-files`.

## Issue labels / milestones conventions

- No custom labels are enforced yet; use GitHub's defaults (`bug`, `enhancement`, etc.) where
  they fit, or none.
- A milestone represents one body of related work with a clear finish line, not a time-box.
  Close the milestone only once every issue under it is closed.

## For future agents working in this repo

Follow this document. If you find yourself about to add a capability without an issue, or
skip the fake-`pi` test pattern, or batch several unrelated changes into one commit, stop and
reread the relevant section above first.

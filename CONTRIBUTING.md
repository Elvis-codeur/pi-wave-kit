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
4. **No CI is configured yet** -- until one exists, the author running `pytest` locally before
   pushing is the gate. Add CI as its own issue if you want it; don't block on it existing.

## Issue labels / milestones conventions

- No custom labels are enforced yet; use GitHub's defaults (`bug`, `enhancement`, etc.) where
  they fit, or none.
- A milestone represents one body of related work with a clear finish line, not a time-box.
  Close the milestone only once every issue under it is closed.

## For future agents working in this repo

Follow this document. If you find yourself about to add a capability without an issue, or
skip the fake-`pi` test pattern, or batch several unrelated changes into one commit, stop and
reread the relevant section above first.

# pi-wave-kit v0.2.0

**Released:** 2026-11-23
**Previous:** v0.1.0 (2026-10-26)

## New: native Claude Code background sessions

`pi_wave_kit.claude_sessions` and the new `pi-wave-claude` console script cover Claude Code's
native lifecycle, alongside the existing one-shot/resume support in `pi_wave_kit.agents`:

```bash
pi-wave-claude job review prompt.md --cwd ~/repo --model sonnet
pi-wave-claude start audit-bg --prompt-file audit.md --cwd ~/repo --model sonnet
pi-wave-claude list [--all] [--cwd DIR]
pi-wave-claude status <id|name>
pi-wave-claude logs <id|name> [--raw]
pi-wave-claude attach <id|name>
pi-wave-claude steer <id|name> "change of plan"
pi-wave-claude wait <id|name> --timeout 900
pi-wave-claude stop <id|name>
pi-wave-claude rm <id|name>
```

Also exposes `--allowed-tools`, `--permission-mode`, `--add-dir` and arbitrary `--extra-arg`
passthrough to Claude.

## Safety and correctness

- `--bg` and `-p/--print` are kept separate; the wrapper rejects impossible combinations up front.
- Exact session resolution by short id, full `sessionId` or exact name; ambiguous names refuse
  mutations; `stop`/`rm` re-resolve and pass only the short id.
- Workspace-trust failures preserve Claude's own message; `agents --json` is never used to guess.
- Screen typing sends Ctrl-U, escaped text and Enter, and audits the injected text to
  `<jobs-dir>/<name>/inject.jsonl`.
- Typed steering may queue or interrupt depending on Claude's state; `attach`/`steer` require a
  TTY (the CLI supplies one via `screen`). `logs` is ANSI TUI output; use `job` for clean JSON.
- A session still held by Claude as a background process cannot be resumed with `-p` directly:
  stop it first or pass `--extra-arg=--fork-session`.

## Verification

- 205 tests passing (33 focused Claude-session tests using fake `claude`/`screen`, no paid calls).
- `ruff check .` clean.
- Live-tested against Claude Code 2.1.330: one-shot JSON, resume, background start/logs/status,
  attach and mid-run steering (including stopping an in-flight shell task), stop/rm.

## Compatibility

- No breaking changes to `pi-wave-job`, `pi-wave-run`, `pi-wave-session`, or `pi_wave_kit.agents`.
- New console script: `pi-wave-claude`.
- Install/update with `uv tool install --editable .` from this repository.

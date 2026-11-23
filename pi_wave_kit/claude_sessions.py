"""Claude Code's native BACKGROUND sessions (`claude --bg`), as a lifecycle: start, list/status,
read logs, attach and steer through a real pty, wait, stop/remove -- then resume the same
conversation later with `claude -p --resume`.

This is deliberately a separate module from `pi_wave_kit.agents`, which owns the one-shot
`claude -p --output-format json` path. The two Claude modes cannot be mixed: `--bg` and
`-p/--print` are mutually exclusive (Claude refuses with "--bg and --print conflict"), and they
answer different questions. `-p` is a single request whose final text, session id, token counts and
reported cost arrive as one JSON object -- use `agents.run_agent("claude", ...)` /
`pi-wave-job --agent claude` for that. `--bg` is a session that outlives the launching process,
reports progress only as a TUI, and is steered by typing into its terminal. Both are supported
here: `run_job()` delegates to the one-shot path for callers that want clean JSON output and cost.

Verified live on this machine, 2026-11-23, against Claude Code 2.1.330:

- `claude --bg -n NAME --model haiku "PROMPT"` prints exactly:
      backgrounded · 1efcedf4 · reformation-bg-test
      claude agents             list sessions
      claude attach 1efcedf4    open in this terminal
      claude logs 1efcedf4      show recent output
      claude stop 1efcedf4      stop this session
  and no longer occupies the terminal. `--bg` MUST NOT be combined with -p/--print; this module
  rejects that combination before spawning anything instead of letting Claude's own parse error be
  the first thing a caller sees.
- `claude agents --json` is a JSON array of active sessions; `--all` adds completed background
  sessions. Observed fields: id (the short id used on the command line), name, cwd,
  kind ("background" | "interactive"), status ("idle" | "busy"), state ("working" | "done"),
  sessionId (the full id `-p --resume` takes), startedAt, pid.
- `claude logs <id>` dumps recent TUI output WITH ANSI escape sequences; `claude stop <id>` stops
  and `claude rm <id>` removes a finished session from the list (the conversation itself is kept).
- `claude attach <id>` opens the live TUI and requires a real TTY. There is no non-TTY `send`
  command. This module therefore wraps `claude attach` in a detached `screen` session and types
  into it with `screen -X stuff` -- the same pty technique `pi_wave_kit.interactive` uses for pi.

The dangerous part of this API is that `claude agents --json` lists EVERY Claude session on the
machine, including the user's own interactive sessions. Nothing here guesses: an identifier must
match an exact short id, full sessionId, or exact name; an ambiguous name is an error; stop/remove
re-resolve the session by its short id and pass only that resolved id to Claude. A stale or
made-up id is never "close enough".

Background sessions also require an accepted workspace trust. A fresh `--bg` in an untrusted
directory fails with "Workspace not trusted"; `-p` skips trust. That failure is raised as
`WorkspaceNotTrustedError` with Claude's own stderr preserved verbatim, so the caller can show it
and let the owner accept trust once.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only, keeps the ledger client an optional import
    from .agents import AgentResult

# Subprocess timeouts. `claude --bg` should hand the session off and return almost immediately;
# the other commands are small JSON/TUI reads. A hung `claude` must never hang the caller forever
# (the same reason run_pi and interactive.py put timeouts on every subprocess call).
START_TIMEOUT_SECONDS = 60.0
LIST_TIMEOUT_SECONDS = 30.0
LOGS_TIMEOUT_SECONDS = 30.0
ACTION_TIMEOUT_SECONDS = 30.0
SCREEN_TIMEOUT_SECONDS = 10.0
VERSION_TIMEOUT_SECONDS = 15.0

# Variables a parent Claude Code session sets that change how a child `claude` behaves -- the same
# set agents.py strips for one-shot jobs (a child that inherits them can silently stop saving its
# transcript). They are removed for a background child too: `--bg` is a new top-level session, not
# a nested turn of whatever launched it.
_CLAUDE_PARENT_VARS = ("CLAUDECODE", "CLAUDE_CODE_CHILD_SESSION", "CLAUDE_CODE_ENTRYPOINT")

#: "backgrounded · 1efcedf4 · reformation-bg-test"; the middle dot is U+00B7, with a bullet
#: accepted defensively because terminals/fonts sometimes render it differently in copied output.
BACKGROUNDED_RE = re.compile(r"^backgrounded\s*[·•]\s*(?P<id>\S+)\s*[·•]\s*(?P<name>\S+)\s*$", re.MULTILINE)

# CSI colours/cursor movement, OSC titles/hyperlinks, DCS-style strings, and two-byte escapes. TUI
# output is full of these; `logs()` strips them by default so a caller can read what happened.
_ANSI_RE = re.compile(
    r"""
    \x1B
    (?:
        \][^\x07\x1B]*(?:\x07|\x1B\\)   # OSC ... BEL or ST
      | [PX^_][^\x1B]*(?:\x1B\\)?        # DCS / SOS / PM / APC ... ST
      | \[[0-?]*[ -/]*[@-~]              # CSI ... final byte
      | [@-Z\\-_]                        # two-byte escape (e.g. ESC ( B)
    )
    """,
    re.VERBOSE,
)

#: A session is considered finished when Claude marks it done, or when it is back to idle with no
#: work in flight. `state` is the finer signal ("working"/"done"), `status` the coarser one
#: ("busy"/"idle"); tolerate the synonyms newer releases may use rather than treating only the two
#: exact strings observed on 2.1.330 as success.
_DONE_STATES = frozenset({"done", "completed", "exited", "stopped"})
_DONE_STATUSES = frozenset({"idle", "done", "completed", "exited", "stopped"})


class ClaudeError(RuntimeError):
    """Base class for every failure raised by this module."""


class ClaudeUnavailableError(ClaudeError):
    """The `claude` executable could not be found or run."""


class ClaudeUnsupportedError(ClaudeError):
    """The installed Claude Code is too old for a subcommand/flag this module needs."""


class ClaudeCommandError(ClaudeError):
    """A `claude` command exited non-zero (or printed something unparseable)."""

    def __init__(self, message: str, *, argv: list[str] | None = None, returncode: int | None = None,
                 stdout: str = "", stderr: str = "") -> None:
        super().__init__(message)
        self.argv = list(argv or [])
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class WorkspaceNotTrustedError(ClaudeCommandError):
    """`claude --bg` refused because the working directory's workspace trust was never accepted.

    Kept as its own type because it is not a bug and not a transient failure: the fix is a one-time
    interactive trust decision in that directory. `stderr` holds Claude's message verbatim."""


class ClaudeSessionNotFoundError(ClaudeError):
    """No Claude session matched the given short id, full sessionId, or exact name."""

    def __init__(self, identifier: str, message: str | None = None) -> None:
        super().__init__(message or f"no Claude session matches {identifier!r}")
        self.identifier = identifier


class ClaudeSessionAmbiguousError(ClaudeError):
    """An exact name matched more than one session, so acting on it would risk the wrong one."""

    def __init__(self, identifier: str, matches: list[ClaudeSession]) -> None:
        ids = ", ".join(s.short_id or "?" for s in matches)
        super().__init__(
            f"{identifier!r} matches {len(matches)} Claude sessions ({ids}); "
            f"use the short id or full sessionId instead"
        )
        self.identifier = identifier
        self.matches = matches


class ClaudeWaitTimeoutError(ClaudeError):
    """`wait_for()` reached its deadline before the session reported done/idle."""

    def __init__(self, identifier: str, timeout: float, last: ClaudeSession | None) -> None:
        seen = "not listed" if last is None else f"status={last.status or '?'} state={last.state or '?'}"
        super().__init__(f"{identifier!r} did not finish within {timeout:g}s (last known: {seen})")
        self.identifier = identifier
        self.timeout = timeout
        self.last = last


class ScreenError(ClaudeError):
    """A `screen` operation failed."""


class ScreenNotFoundError(ScreenError):
    """`screen` is not installed, but attach/steer needs a real pty."""


class ScreenNotAttachedError(ScreenError):
    """The session is not currently attached in a screen session (call attach_in_screen first)."""


@dataclass
class ClaudeSession:
    """One entry from `claude agents --json` (or the minimal record `--bg` prints at launch).

    `short_id` is the id every `claude` subcommand uses (`claude attach <short_id>`); `session_id`
    is the full `sessionId` that `claude -p --resume` takes for a deterministic follow-up. `raw`
    keeps the whole JSON object, so fields added by newer Claude Code versions are not lost.
    """

    short_id: str
    name: str = ""
    cwd: str = ""
    session_id: str = ""
    kind: str = ""
    status: str = ""
    state: str = ""
    pid: int | None = None
    started_at: str = ""
    raw: dict = field(default_factory=dict)

    @classmethod
    def from_raw(cls, raw: dict) -> ClaudeSession:
        """Build from one `agents --json` object, accepting snake_case aliases defensively.

        A field that is absent stays empty rather than being invented: `start_background()` only
        knows the short id and name Claude printed, and it must not pretend to know a pid/state it
        never saw.
        """
        pid = raw.get("pid")
        try:
            pid = int(pid) if pid is not None else None
        except (TypeError, ValueError):
            pid = None
        return cls(
            short_id=str(raw.get("id") or raw.get("shortId") or raw.get("short_id") or ""),
            name=str(raw.get("name") or ""),
            cwd=str(raw.get("cwd") or ""),
            session_id=str(raw.get("sessionId") or raw.get("session_id") or ""),
            kind=str(raw.get("kind") or ""),
            status=str(raw.get("status") or ""),
            state=str(raw.get("state") or ""),
            pid=pid,
            started_at=str(raw.get("startedAt") or raw.get("started_at") or ""),
            raw=raw,
        )

    @property
    def id(self) -> str:
        """Alias for `short_id`, the field's own name in Claude's output and CLI arguments."""
        return self.short_id

    @property
    def label(self) -> str:
        """A human-facing "name (id)" without ever being used as an action target."""
        if self.name and self.short_id:
            return f"{self.name} ({self.short_id})"
        return self.name or self.short_id

    @property
    def is_done(self) -> bool:
        """True once Claude reports the session done or idle (see `_DONE_STATES`/`_DONE_STATUSES`)."""
        return (self.state or "").lower() in _DONE_STATES or (self.status or "").lower() in _DONE_STATUSES

    def to_dict(self) -> dict:
        """JSON-safe form for the CLI's `--json` output and the `<jobs-dir>/<name>/session.json`."""
        return {
            "id": self.short_id,
            "short_id": self.short_id,
            "name": self.name,
            "cwd": self.cwd,
            "session_id": self.session_id,
            "kind": self.kind,
            "status": self.status,
            "state": self.state,
            "pid": self.pid,
            "started_at": self.started_at,
            "raw": self.raw,
        }


def claude_command() -> str:
    """The absolute path to `claude`, or a clear error telling the caller where to look.

    `~/.local/bin` is a common Claude Code install location but is not on every non-login PATH
    (this machine's bash tool, for example, does not have it). Falling back to that well-known
    path means a library caller does not have to mutate PATH just to reach an installed Claude.
    """
    found = shutil.which("claude")
    if found:
        return found
    for candidate in (Path.home() / ".local" / "bin" / "claude", Path.home() / ".claude" / "local" / "claude"):
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    raise ClaudeUnavailableError(
        "claude executable not found on PATH (also checked ~/.local/bin/claude and "
        "~/.claude/local/claude). Install Claude Code, or put its install directory on PATH, e.g. "
        'export PATH="$HOME/.local/bin:$PATH".'
    )


def claude_version(command: str | None = None, *, timeout: float = VERSION_TIMEOUT_SECONDS) -> str:
    """`claude --version`, first line -- an availability check and the version to quote in errors."""
    cmd = command or claude_command()
    proc = _run([cmd, "--version"], timeout=timeout)
    if proc.returncode != 0:
        raise ClaudeCommandError(_failure("claude --version", proc, [cmd, "--version"]),
                                 argv=[cmd, "--version"], returncode=proc.returncode,
                                 stdout=proc.stdout or "", stderr=proc.stderr or "")
    lines = (proc.stdout or "").strip().splitlines()
    return lines[0].strip() if lines else ""


def start_background(name: str, prompt: str, *, cwd: str | Path = ".", model: str | None = None,
                     extra_args: list[str] | None = None, env: dict | None = None) -> ClaudeSession:
    """Start a detached Claude Code session with `claude --bg -n NAME ... PROMPT`.

    Returns the session as Claude reported it (`short_id`, `name`, resolved `cwd`, `kind="background"`).
    The launch output does not include pid/status/state, so those stay empty until `get_session()`
    or `wait_for()` refreshes the record from `claude agents --json` -- a guessed "busy" here could
    be wrong before the caller's first poll, and this module never invents state.

    `extra_args` are inserted after `--model` and before the prompt, exactly the argv shape the
    installed 2.1.330 accepts. `-p`/`--print` is rejected up front: `--bg` and print mode conflict,
    and a caller who wants a one-shot JSON answer wants `run_job()` instead. `env` adds variables
    for this one process (a client's `CLAUDE_CONFIG_DIR`, for example) and the usual parent-session
    variables are removed.
    """
    name = (name or "").strip()
    if not name:
        raise ValueError("a background session needs a non-empty name")
    if not isinstance(prompt, str):
        raise TypeError("prompt must be a string")
    cwd_path = Path(cwd).expanduser()
    if not cwd_path.is_dir():
        raise ClaudeError(f"working directory does not exist: {cwd_path}")

    extra = list(extra_args or [])
    conflict = [arg for arg in extra if arg in ("-p", "--print") or arg.startswith("--print=")]
    if conflict:
        raise ClaudeError(
            f"claude --bg cannot be combined with {', '.join(conflict)}: Claude refuses with "
            "'--bg and --print conflict'. Use start_background() for a live session, or "
            "run_job()/pi-wave-job --agent claude for one-shot JSON output."
        )

    cmd = [claude_command(), "--bg", "-n", name]
    if model:
        cmd += ["--model", model]
    cmd += extra + [prompt]

    proc = _run(cmd, cwd=cwd_path, env=_child_env(env), timeout=START_TIMEOUT_SECONDS)
    stdout, stderr = proc.stdout or "", proc.stderr or ""
    if proc.returncode != 0:
        detail = stderr.strip() or stdout.strip() or "(no output)"
        message = f"claude --bg failed (exit {proc.returncode}): {detail}"
        if "workspace not trusted" in f"{stdout}\n{stderr}".lower():
            raise WorkspaceNotTrustedError(message, argv=cmd, returncode=proc.returncode,
                                           stdout=stdout, stderr=stderr) from None
        raise ClaudeCommandError(message, argv=cmd, returncode=proc.returncode,
                                 stdout=stdout, stderr=stderr)

    match = BACKGROUNDED_RE.search(stdout) or BACKGROUNDED_RE.search(f"{stdout}\n{stderr}")
    if match is None:
        shown = (stdout.strip() or stderr.strip() or "(no output)")[:500]
        raise ClaudeCommandError(
            "claude --bg exited 0 but did not print a 'backgrounded · <id> · <name>' line; "
            f"cannot identify the session it started. Output: {shown}",
            argv=cmd, returncode=proc.returncode, stdout=stdout, stderr=stderr,
        )
    return ClaudeSession(
        short_id=match.group("id"),
        name=match.group("name"),
        cwd=str(cwd_path.resolve()),
        kind="background",
        raw={"start": {"stdout": stdout, "stderr": stderr}},
    )


def list_sessions(*, include_completed: bool = False, cwd: str | Path | None = None) -> list[ClaudeSession]:
    """`claude agents --json` (plus `--all` when `include_completed`) as a list of sessions.

    This lists every Claude session on the machine, including the user's own interactive ones --
    that is Claude's API, not something this wrapper can narrow safely on the CLI side. Use `cwd=`
    to scope by resolved working directory and `get_session()` to resolve one exact session.

    Parsing is deliberately tolerant of a warning line before the JSON: Claude may print startup
    noise to stdout, and a caller should not lose the whole list because of it. A version too old
    for `--all` raises `ClaudeUnsupportedError` rather than a generic exit-code error.
    """
    cmd = [claude_command(), "agents", "--json"]
    if include_completed:
        cmd.append("--all")
    proc = _run(cmd, timeout=LIST_TIMEOUT_SECONDS)
    if proc.returncode != 0:
        stdout, stderr = proc.stdout or "", proc.stderr or ""
        if (include_completed and _looks_like_unknown_option(stderr)) or _looks_like_unknown_command(stderr):
            detail = stderr.strip() or stdout.strip()
            raise ClaudeUnsupportedError(
                "this Claude Code version does not support the `claude agents --json` form this "
                f"module needs (--all lists completed sessions); upgrade Claude Code. stderr: {detail}"
            )
        raise ClaudeCommandError(_failure("claude agents --json", proc, cmd), argv=cmd,
                                 returncode=proc.returncode, stdout=stdout, stderr=stderr)

    sessions = [ClaudeSession.from_raw(item) for item in _parse_agents_json(proc.stdout or "")]
    sessions = [s for s in sessions if s.short_id]  # a record without an id cannot be acted on safely
    if cwd is not None:
        target = Path(cwd).expanduser().resolve()
        sessions = [s for s in sessions if _same_cwd(s.cwd, target)]
    return sessions


def get_session(identifier: str, *, include_completed: bool = True) -> ClaudeSession:
    """Resolve exactly one session by short id, full sessionId, or exact name.

    Exact ids win over names. A name that matches more than one session raises
    `ClaudeSessionAmbiguousError` instead of picking one -- names are chosen by users and are not a
    safe action target. Completed background sessions count by default, because that is where a
    just-finished session goes before `claude rm`.
    """
    key = str(identifier or "").strip()
    if not key:
        raise ClaudeSessionNotFoundError(key, "an empty string is not a Claude session identifier")
    sessions = list_sessions(include_completed=include_completed)
    for session in sessions:
        if session.short_id == key:
            return session
    for session in sessions:
        if session.session_id and session.session_id == key:
            return session
    by_name = [s for s in sessions if s.name and s.name == key]
    if len(by_name) == 1:
        return by_name[0]
    if len(by_name) > 1:
        raise ClaudeSessionAmbiguousError(key, by_name)
    scope = "active and completed" if include_completed else "active"
    raise ClaudeSessionNotFoundError(
        key, f"no {scope} Claude session matches {key!r} (tried short id, sessionId and exact name)"
    )


def wait_for(session_or_identifier: ClaudeSession | str, *, timeout: float = 600, poll: float = 2,
             include_completed: bool = True) -> ClaudeSession:
    """Poll `claude agents --json` until the session reports done/idle, or raise on timeout.

    Returns the last session record, not just True, so the caller keeps the final state/pid.
    `ClaudeWaitTimeoutError.last` carries the last known record when the deadline passes. The
    default includes completed sessions: a background job that just finished may already have left
    the active list, and that is success, not "session disappeared".
    """
    if poll <= 0:
        raise ValueError("poll must be greater than 0 seconds")
    identifier = _identifier_for(session_or_identifier)
    deadline = time.monotonic() + max(0.0, float(timeout))
    last: ClaudeSession | None = None
    while True:
        last = get_session(identifier, include_completed=include_completed)
        if last.is_done:
            return last
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ClaudeWaitTimeoutError(identifier, timeout, last)
        time.sleep(min(poll, remaining))


def strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences (CSI colours/cursor moves, OSC titles/hyperlinks, DCS, ESC)."""
    return _ANSI_RE.sub("", text or "")


def logs(session_or_identifier: ClaudeSession | str, *, raw: bool = False) -> str:
    """`claude logs <short id>`; ANSI-stripped terminal text by default, exact output with `raw=True`.

    The underlying command shows recent TUI frames, not a machine-readable transcript. It is useful
    for a human or for a coarse "is it doing anything?" check, but not for typed results. For clean
    JSON output and token/cost numbers, use `run_job()` / `pi-wave-job --agent claude`.
    """
    target = _action_target(session_or_identifier, read_only=True)
    cmd = [claude_command(), "logs", target]
    proc = _run(cmd, timeout=LOGS_TIMEOUT_SECONDS)
    if proc.returncode != 0:
        raise ClaudeCommandError(_failure("claude logs", proc, cmd), argv=cmd,
                                 returncode=proc.returncode, stdout=proc.stdout or "",
                                 stderr=proc.stderr or "")
    text = proc.stdout or ""
    return text if raw else strip_ansi(text)


def attach_in_screen(session_or_identifier: ClaudeSession | str, *, screen_name: str | None = None,
                     wait: float = 1.0) -> str:
    """Attach a session's TUI inside a detached `screen`, returning the screen session's name.

    `claude attach` needs a real TTY; a headless caller has none, so this starts
    `screen -dmS <name> <claude> attach <short_id>`. Idempotent: if that screen session is already
    alive it is reused, never duplicated. `wait` sleeps briefly after a fresh launch so the TUI can
    draw before the first keystroke. Raises `ScreenNotFoundError` with an install hint when screen
    is missing.
    """
    resolved = _resolve_session(session_or_identifier)
    screen = _screen_executable()
    name = _screen_name(resolved, screen_name)
    if _screen_alive(screen, name):
        return name
    cmd = [screen, "-dmS", name, claude_command(), "attach", resolved.short_id]
    proc = _run(cmd, timeout=SCREEN_TIMEOUT_SECONDS)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip() or "(no output)"
        raise ScreenError(f"screen -dmS {name} failed (exit {proc.returncode}): {detail}")
    if wait:
        time.sleep(wait)
    return name


def type_into(session_or_identifier: ClaudeSession | str, text: str, *, enter: bool = True,
              screen_name: str | None = None, audit_path: str | Path | None = None) -> dict:
    """Type `text` into an ALREADY ATTACHED session's screen, preceded by Ctrl-U and optionally Enter.

    Ctrl-U is sent first so a half-typed prompt already sitting in the TUI does not get prefixed to
    the new instruction. The text is passed through `screen -X stuff`, escaping literal `^` (screen
    would otherwise turn `^C` into a real Ctrl-C) and backslashes (screen's own escape character).
    These are KEYSTROKES: they land wherever the TUI cursor is, so a session that is generating
    receives them mid-stream and Claude may queue, interrupt, or simply ignore them depending on
    its state. That is why `steer()` documents itself as PTY-based rather than as a message API.

    Every injection is appended to `audit_path` (JSONL, type "inject") when supplied -- keystrokes
    otherwise leave no trace.
    """
    resolved = _resolve_session(session_or_identifier)
    if "\x00" in (text or ""):
        raise ValueError("text cannot contain a NUL byte (argv cannot carry one)")
    screen = _screen_executable()
    name = _screen_name(resolved, screen_name)
    if not _screen_alive(screen, name):
        raise ScreenNotAttachedError(
            f"no screen session {name!r} for Claude session {resolved.label}; call "
            f"attach_in_screen() first (or steer(), which attaches automatically)"
        )
    _stuff(screen, name, "\x15")  # Ctrl-U: clear whatever is on the prompt line
    if text:
        _stuff(screen, name, _stuff_escape(text))
    if enter:
        _stuff(screen, name, "\r")
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "type": "inject",
        "via": "screen",
        "screen": name,
        "target": resolved.short_id,
        "name": resolved.name,
        "session_id": resolved.session_id,
        "enter": bool(enter),
        "text": text,
    }
    _write_audit(audit_path, record)
    return record


def steer(session_or_identifier: ClaudeSession | str, text: str, *, enter: bool = True,
          audit_path: str | Path | None = None) -> dict:
    """Attach (if needed) and type text into the session -- the reliable mid-run steering path.

    This is PTY-based, not a protocol message: the keystrokes may queue behind Claude's current
    turn or interrupt it, depending on the session's state at that instant, and delivery is not
    confirmed by Claude. There is no non-TTY `claude send` command to do better. Use it to redirect
    a background session; use `run_job(... --resume)` when a deterministic next instruction and a
    clean JSON answer are what is wanted.
    """
    resolved = _resolve_session(session_or_identifier)
    name = attach_in_screen(resolved)
    return type_into(resolved, text, enter=enter, screen_name=name, audit_path=audit_path)


def stop(session_or_identifier: ClaudeSession | str) -> None:
    """`claude stop <resolved short id>`. Exact session only; never a name that might be ambiguous."""
    _run_action("stop", session_or_identifier)


def remove(session_or_identifier: ClaudeSession | str) -> None:
    """`claude rm <resolved short id>`: drop a finished session from the list, conversation kept."""
    _run_action("rm", session_or_identifier)


def run_job(job_id: str, *, prompt: str, model: str = "", cwd: str | Path = ".",
            out_dir: str | Path | None = None, session_id: str = "", extra_args: list[str] | None = None,
            env: dict | None = None, timeout_seconds: float | None = None, ledger=None,
            run_pk: int | None = None, call_purpose: str = "") -> AgentResult:
    """One-shot `claude -p --output-format json` through `pi_wave_kit.agents`, for clean output/cost.

    This is the counterpart to `start_background()`: same agent family, different process shape.
    `session_id` resumes an earlier session (`claude -p --resume <sessionId>`) for a deterministic
    follow-up. Delegation is lazy so importing this module does not require the ledger client.
    """
    from .agents import run_agent

    command = claude_command()  # fail with ClaudeUnavailableError here, not a bare FileNotFoundError from Popen
    cwd_path = Path(cwd).expanduser()
    if not cwd_path.is_dir():
        raise ClaudeError(f"working directory does not exist: {cwd_path}")
    # agents.build_command() spells the executable as plain "claude" (which keeps its argv API stable
    # and its existing tests honest). If claude_command() found the binary through the ~/.local/bin
    # fallback rather than PATH, put that directory first for this one process so the one-shot job
    # actually finds the same executable this function just verified.
    job_env = dict(env or {})
    if os.sep in command:
        search = job_env.get("PATH", os.environ.get("PATH", ""))
        entries = [entry for entry in search.split(os.pathsep) if entry]
        binary_dir = str(Path(command).parent)
        if not entries or entries[0] != binary_dir:
            entries.insert(0, binary_dir)
        job_env["PATH"] = os.pathsep.join(entries)
    out = Path(out_dir) if out_dir is not None else cwd_path / "pi-wave-jobs" / job_id
    return run_agent(
        "claude", job_id, prompt=prompt, model=model, cwd=cwd_path, out_dir=out,
        session_id=session_id, extra_args=extra_args, env=job_env, timeout_seconds=timeout_seconds,
        ledger=ledger, run_pk=run_pk, call_purpose=call_purpose,
    )


# --------------------------------------------------------------------------------------------------
# Internals: subprocess helpers, JSON parsing, identifier resolution, screen plumbing, audit.
# --------------------------------------------------------------------------------------------------


def _child_env(env: dict | None) -> dict:
    merged = {**os.environ, **(env or {})}
    for name in _CLAUDE_PARENT_VARS:
        merged.pop(name, None)
    return merged


def _run(argv: list[str], *, timeout: float, cwd: str | Path | None = None,
         env: dict | None = None) -> subprocess.CompletedProcess:
    """Run one command with no shell, a timeout, and decoded output.

    All subprocess calls in this module go through here: `shell=True` is never used, stdin is
    closed (a headless `claude` must not wait on a terminal that does not exist), and a timeout is
    mandatory so a hung CLI cannot hang the caller.
    """
    try:
        return subprocess.run(
            argv, cwd=str(cwd) if cwd is not None else None, stdin=subprocess.DEVNULL,
            capture_output=True, text=True, encoding="utf-8", errors="replace", env=env,
            timeout=timeout, check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ClaudeError(f"{Path(argv[0]).name} did not finish within {timeout:g}s: {' '.join(argv[:4])}") from exc
    except OSError as exc:
        raise ClaudeError(f"could not run {argv[0]!r}: {exc}") from exc


def _failure(what: str, proc: subprocess.CompletedProcess, argv: list[str]) -> str:
    detail = (proc.stderr or "").strip() or (proc.stdout or "").strip() or "(no output)"
    return f"{what} failed (exit {proc.returncode}): {detail}"


def _parse_agents_json(stdout: str) -> list[dict]:
    """Parse `agents --json`, tolerating a warning line before the array and an object wrapper."""
    text = (stdout or "").strip()
    if not text:
        return []
    candidates = [text]
    start, end = text.find("["), text.rfind("]")
    if start != -1 and end > start:
        candidates.append(text[start:end + 1])
    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(data, dict):
            for key in ("sessions", "agents", "data", "items"):
                if isinstance(data.get(key), list):
                    data = data[key]
                    break
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
    shown = text[:300]
    raise ClaudeError(f"could not parse the JSON array from `claude agents --json`; output began: {shown!r}")


def _looks_like_unknown_option(stderr: str) -> bool:
    text = (stderr or "").lower()
    return "--all" in text and any(token in text for token in (
        "unknown option", "unknown flag", "unrecognized argument", "unexpected argument", "invalid option",
    ))


def _looks_like_unknown_command(stderr: str) -> bool:
    text = (stderr or "").lower()
    return any(token in text for token in (
        "unknown command", "unknown subcommand", "unrecognized command", "invalid command",
    ))


def _same_cwd(raw_cwd: str, target: Path) -> bool:
    if not raw_cwd:
        return False
    try:
        return Path(raw_cwd).expanduser().resolve() == target
    except (OSError, RuntimeError):
        return False


def _identifier_for(session_or_identifier: ClaudeSession | str) -> str:
    if isinstance(session_or_identifier, ClaudeSession):
        identifier = session_or_identifier.short_id or session_or_identifier.session_id or session_or_identifier.name
        if not identifier:
            raise ValueError("ClaudeSession has no short_id, session_id or name to identify it")
        return identifier
    identifier = str(session_or_identifier or "").strip()
    if not identifier:
        raise ValueError("an empty string is not a Claude session identifier")
    return identifier


def _resolve_session(session_or_identifier: ClaudeSession | str) -> ClaudeSession:
    """Turn either form into a `ClaudeSession` for read-only/pty use.

    A record that already carries a short id is used as-is (no extra `agents --json` call);
    a string identifier is resolved exactly, with the same ambiguity protection as `get_session`.
    """
    if isinstance(session_or_identifier, ClaudeSession) and session_or_identifier.short_id:
        return session_or_identifier
    return get_session(_identifier_for(session_or_identifier), include_completed=True)


def _resolve_for_action(session_or_identifier: ClaudeSession | str) -> ClaudeSession:
    """Re-resolve a session against the live list before stop/remove -- even an object carrying an
    id is checked to still exist, so a stale record cannot make us act on a recycled/missing id."""
    if isinstance(session_or_identifier, ClaudeSession) and session_or_identifier.short_id:
        return get_session(session_or_identifier.short_id, include_completed=True)
    return get_session(_identifier_for(session_or_identifier), include_completed=True)


def _action_target(session_or_identifier: ClaudeSession | str, *, read_only: bool) -> str:
    """Resolve to the exact short id. A read-only command may accept a freshly started record as-is."""
    resolved = _resolve_session(session_or_identifier) if read_only else _resolve_for_action(session_or_identifier)
    return resolved.short_id


def _run_action(verb: str, session_or_identifier: ClaudeSession | str) -> None:
    # Always act on a live record's short id; the name-based identifier is resolved first, and an
    # ambiguous name raises before any `claude stop`/`claude rm` process exists.
    resolved = _resolve_for_action(session_or_identifier)
    if not resolved.short_id:
        raise ClaudeSessionNotFoundError(_identifier_for(session_or_identifier),
                                         "resolved Claude session has no short id; refusing to act on a guess")
    cmd = [claude_command(), verb, resolved.short_id]
    proc = _run(cmd, timeout=ACTION_TIMEOUT_SECONDS)
    if proc.returncode != 0:
        raise ClaudeCommandError(_failure(f"claude {verb}", proc, cmd), argv=cmd,
                                 returncode=proc.returncode, stdout=proc.stdout or "",
                                 stderr=proc.stderr or "")


def _screen_executable() -> str:
    found = shutil.which("screen")
    if not found:
        raise ScreenNotFoundError(
            "screen executable not found on PATH; `claude attach` needs a real TTY and this library "
            "uses GNU screen to provide one. Install screen (e.g. `sudo apt install screen`) or run "
            "`claude attach <id>` yourself in a terminal."
        )
    return found


def _screen_name(session: ClaudeSession, requested: str | None) -> str:
    """Use a requested screen name exactly, or a stable `claude-<short id>` default.

    Screen accepts dots in session names (and `_screen_alive` escapes the whole name), so only
    whitespace/control characters -- which would break `screen -ls` parsing and argv hygiene -- are
    rejected for a caller-supplied name. The default replaces anything outside `[A-Za-z0-9_-]` so a
    session id can never introduce its own `-ls` noise.
    """
    if requested is not None:
        name = requested.strip()
        if not name or re.search(r"[\s\x00-\x1f]", name):
            raise ScreenError(f"invalid screen session name {requested!r} (empty or contains whitespace/control characters)")
        return name
    safe = re.sub(r"[^A-Za-z0-9_-]+", "-", f"claude-{session.short_id}").strip("-")
    if not safe:
        raise ScreenError(f"cannot derive a usable screen session name from {session.label!r}")
    return safe


def _screen_alive(screen: str, name: str) -> bool:
    """True when `screen -ls` lists this session; `screen -ls` exits 1 when there are none, which is
    a normal "not attached" answer, not an error."""
    proc = _run([screen, "-ls"], timeout=SCREEN_TIMEOUT_SECONDS)
    output = f"{proc.stdout or ''}\n{proc.stderr or ''}"
    return re.search(rf"(?:^|\n)\s*\d+\.{re.escape(name)}(?=\s|\t|$)", output) is not None


def _stuff_escape(text: str) -> str:
    """Escape text for screen's `stuff`: backslash is screen's escape character, and `^X` is a
    control-key notation (`^C` would become a real interrupt) -- both must be escaped literally."""
    return text.replace("\\", "\\\\").replace("^", "\\^")


def _stuff(screen: str, name: str, data: str) -> None:
    cmd = [screen, "-S", name, "-X", "stuff", data]
    proc = _run(cmd, timeout=SCREEN_TIMEOUT_SECONDS)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip() or "(no output)"
        raise ScreenError(f"could not type into screen session {name!r} (exit {proc.returncode}): {detail}")


def _write_audit(audit_path: str | Path | None, record: dict) -> None:
    if audit_path is None:
        return
    path = Path(audit_path)
    if path.is_dir():  # accept a directory as "append to inject.jsonl in here"
        path = path / "inject.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

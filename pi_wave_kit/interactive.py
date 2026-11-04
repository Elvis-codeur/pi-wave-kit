"""Launch, inspect, and stop a long-lived INTERACTIVE `pi` session wrapped in `screen`, so it stays
alive and reachable the way `pi -p` and a backgrounded interactive session with no real pty cannot.

Confirmed live, 2026-10-24 (re-verifying `pi-gatekeeper`'s own earlier finding, not just trusting the
note): `pi -p` processes one prompt and exits -- it has no "stay alive, idle, listening" state.
Backgrounding an *interactive* session with stdin pointed at `/dev/null` doesn't work either: without a
real pty, `pi` reads EOF on its next input and exits after one turn, indistinguishable from `-p` mode. A
real pty is required. This machine has `screen` but not `tmux`, so this module uses `screen -dmS`
(detached, named) the same way `pi-gatekeeper/launch_gatekeeper.sh` does.

**Sending a message** needs another `pi` agent: pi-messenger has no sending CLI (its npm package's only
`bin` entry is an installer, `install.mjs`), so the only way to DM a running session from "elsewhere" is a
one-shot courier `pi -p` that calls the `pi_messenger` tool itself. `send_message()` (CLI:
`pi-wave-session send`, issue #15) does exactly that with a verbatim-preserving prompt, and confirms
delivery from pi-messenger's own `feed.jsonl`, never from the courier's report. Confirmed live together
with this module's launch path: a session started here, with `.pi/pi-messenger.json` set to
`{"autoRegister": true}` in its working directory, received a DM from a separate one-shot `pi -p`
process and replied 1.3 s later -- verified from `feed.jsonl`, not the model's self-report.
`type_into()` (CLI: `pi-wave-session type`, issue #16) is the other way in: keystrokes into the pty.

**Real constraint, not papered over**: a session is only remotely reachable at all if it (1) runs
under a real pty (`screen`/`tmux`, this module's whole point) and (2) has joined the pi-messenger mesh
(`autoRegister` in that project's `.pi/pi-messenger.json`, or an explicit `join` call) -- this module
starts the process but does not write that config; it's the caller's project setting, same as
`run_pi.start_pi` doesn't write `.pi/settings.json` either. An owner who wants remote control over an
interactive session must launch it this specific way (this module, with that config already in place)
for remote control to be possible at all; an arbitrary session started by hand some other way is not
reachable from outside."""

from __future__ import annotations

import json
import os
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

# agent-watch-daemon's local-only HTTP API (127.0.0.1, never exposed beyond the laptop --
# see that repo's local_api.rs). Owner directive 2026-10-26: once that daemon exists, every
# session this module launches should register with it by default, so it's immediately
# steerable from the web app -- not just reachable via a hand-typed `screen -r` later.
AGENT_WATCH_LOCAL_PORT = 7890
_DAEMON_REQUEST_TIMEOUT_SECONDS = 1.5  # short: this must never make a normal launch feel slow
# when the daemon (very commonly) isn't running -- a failed/refused connection returns almost
# instantly, this timeout only matters if something is listening but hung.


#: agent-watch-daemon itself shells out to `pi-wave-session launch` to actually fulfill a `pi`
#: `/local/create` request (confirmed in that repo's `pi_wave.rs`) -- without this guard, that
#: inner invocation would recurse into THIS same function and try to contact the daemon again,
#: forever. The daemon must set this exact env var on that one subprocess call (a small,
#: separate follow-up on that repo, not yet done as of this comment being written); until it
#: does, `register_with_daemon=True` is only safe to call directly, never from inside something
#: the daemon itself launched.
DAEMON_SPAWNED_ENV_VAR = "PI_WAVE_KIT_SKIP_DAEMON"


def _try_daemon_create(
    *, tool: str, cwd: str, args: list[str], prompt: str | None
) -> dict | None:
    """Best-effort: ask agent-watch-daemon's local API to create this session instead of doing
    it ourselves. Returns its JSON response (`{"external_id", "tmux_session_name"}`) on success,
    or None for ANY failure -- daemon not running (the common case, almost every project using
    this library has nothing to do with agent-watch), daemon running but rejected the request,
    network hiccup, malformed response, OR this process was itself spawned BY the daemon
    (`DAEMON_SPAWNED_ENV_VAR` set) -- that last case isn't a failure, it's the recursion guard:
    the daemon is already in the middle of creating this exact session, asking it again would
    loop forever. None here always means "fall back to the direct screen launch below, exactly
    as if this function didn't exist" -- this is an enhancement, never a new hard dependency a
    caller's launch can fail because of."""
    if os.environ.get(DAEMON_SPAWNED_ENV_VAR):
        return None
    payload = json.dumps({"tool": tool, "cwd": cwd, "args": args, "prompt": prompt}).encode("utf-8")
    req = urllib.request.Request(
        f"http://127.0.0.1:{AGENT_WATCH_LOCAL_PORT}/local/create",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=_DAEMON_REQUEST_TIMEOUT_SECONDS) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return None


@dataclass(frozen=True)
class ScreenSession:
    """A `pi` interactive session running inside a detached, named `screen` scope. `screen -dmS` execs
    `pi` in place (same as `systemd-run --scope`, see `run_pi.CgroupLimits`'s docstring for the
    general pattern), so the screen session exists for exactly as long as `pi` does -- `is_alive()`
    reflects that."""

    name: str
    log_path: Path | None


def launch_screen_session(
    name: str,
    *,
    provider: str,
    model: str,
    thinking: str,
    cwd: str | Path,
    session_dir: str | Path,
    initial_prompt: str | None = None,
    extra_args: list[str] | None = None,
    log_path: str | Path | None = None,
    approve: bool = True,
    register_with_daemon: bool = True,
) -> ScreenSession:
    """Start a real interactive `pi` session inside a detached `screen` scope named `name`.
    `initial_prompt`, if given, is passed to `pi` as its first message, the same way `pi "do X"` works
    when run directly. `approve` passes `--approve` (trust project-local files, e.g.
    `.pi/pi-messenger.json`'s `autoRegister`) -- set False if that trust isn't wanted for this run.

    **Default behavior, owner directive 2026-10-26**: tries `agent-watch-daemon`'s local API
    first (`register_with_daemon=True`, the default) -- if that laptop daemon is running, the
    session it creates is immediately visible/steerable from the web app, not just reachable via
    a hand-typed `screen -r` later. If the daemon isn't running (by far the common case -- most
    projects using this library have nothing to do with `agent-watch`), this falls straight
    through to the direct `screen` launch below, completely unchanged from before this feature
    existed -- the session is still screen-wrapped and resumable, it's just not immediately
    daemon-registered (the daemon's own normal directory scan will still pick it up later, once
    it's running). Pass `register_with_daemon=False` to always skip the daemon attempt and go
    straight to the direct launch (useful for testing, or when daemon visibility genuinely isn't
    wanted for this one session). **For a session that should never be steerable/resumable at
    all** -- no screen wrapping, no daemon, nothing -- that's a different function entirely:
    `pi_wave_kit.run_pi.run_pi()` (CLI: `pi-wave-job`), which already runs a single one-shot
    process with no multiplexer. This function's whole purpose is the opposite of that.

    Sets `PI_AGENT_NAME=<name>` on the launched process -- a real bug found by this function's own
    manual smoke test (2026-10-25): `--name` alone only sets the session's display title, NOT its
    pi-messenger mesh identity, so without this env var a peer sees a random auto-generated name
    (e.g. `QuickRaven`) instead of `name`, making the whole point of calling this with a chosen,
    known `name` -- being reachable at a name the caller picked -- silently not true."""
    session_dir = Path(session_dir)
    session_dir.mkdir(parents=True, exist_ok=True)

    if register_with_daemon:
        daemon_result = _try_daemon_create(
            tool="pi", cwd=str(cwd), args=extra_args or [], prompt=initial_prompt
        )
        if daemon_result is not None:
            return ScreenSession(
                name=daemon_result.get("tmux_session_name", name),
                log_path=Path(log_path) if log_path else None,
            )

    pi_cmd = ["pi", "--provider", provider, "--model", model, "--thinking", thinking,
              "--session-dir", str(session_dir), "--name", name, *(extra_args or [])]
    if approve:
        pi_cmd.append("--approve")
    if initial_prompt is not None:
        pi_cmd.append(initial_prompt)

    cmd = ["screen"]
    if log_path:
        cmd += ["-L", "-Logfile", str(log_path)]
    cmd += ["-dmS", name, *pi_cmd]

    env = os.environ.copy()
    env["PI_AGENT_NAME"] = name
    subprocess.run(cmd, cwd=str(cwd), stdin=subprocess.DEVNULL, check=True, env=env)
    return ScreenSession(name=name, log_path=Path(log_path) if log_path else None)


def is_alive(session: ScreenSession) -> bool:
    """True if `screen -ls` still lists this session name -- false once `pi` inside it has exited (the
    screen scope ends with it, confirmed live: a `sleep 2` test scope vanished from `screen -ls` the
    moment `sleep` finished, with no separate teardown needed)."""
    out = subprocess.run(["screen", "-ls"], capture_output=True, text=True).stdout
    return f".{session.name}\t" in out


def hardcopy(session: ScreenSession, out_path: str | Path) -> str:
    """Dump the session's current terminal contents to `out_path` (screen's own `hardcopy`) and return
    its text -- the real, independently-checkable way to see what a live session actually did, instead
    of trusting a peer's or the session's own self-report of what happened.

    `errors="replace"`: a real TUI frame can contain box-drawing bytes that aren't valid UTF-8 (hit
    live, 2026-10-24, decoding a real pi screen's hardcopy -- 0x91 at a fixed byte offset, not a
    transient glitch); never let a bad byte raise instead of returning the text that IS readable."""
    subprocess.run(["screen", "-S", session.name, "-X", "hardcopy", str(out_path)], check=True)
    return Path(out_path).read_text(encoding="utf-8", errors="replace")


def stop(session: ScreenSession) -> None:
    """Ask the screen scope to quit (and `pi` inside it with it). Not an error if it already exited on
    its own."""
    subprocess.run(["screen", "-S", session.name, "-X", "quit"], check=False)


# --------------------------------------------------------------------------------------------------
# Reaching a running session: send (a mesh DM, issue #15) and type (keystrokes into its pty, issue #16).
# hardcopy() above is the third, read-only way.
# --------------------------------------------------------------------------------------------------

SEND_BEGIN = "<<<BEGIN-MESSAGE>>>"
SEND_END = "<<<END-MESSAGE>>>"


def send_prompt(to: str, text: str) -> str:
    """The courier's prompt. The payload sits between fixed markers and the courier is told to send it
    byte for byte: a courier that paraphrases the message is worse than no delivery at all."""
    return (
        f"Use the pi_messenger tool: join the mesh if you have not, then send ONE direct message to the peer "
        f"named exactly {to}. The message text is everything between the line {SEND_BEGIN} and the line "
        f"{SEND_END} below, copied EXACTLY: same words, punctuation, line breaks and case; add nothing, remove "
        f"nothing, do not translate, summarise or rephrase, do not include the marker lines. Do nothing else. "
        f"Then reply with exactly SENT or FAILED.\n{SEND_BEGIN}\n{text}\n{SEND_END}"
    )


def feed_candidates(cwd: str | Path) -> list[Path]:
    """Where pi-messenger's `feed.jsonl` can be: the project's `.pi/messenger/` (what the live tests in the
    README and issue #15 observed), `$PI_MESSENGER_DIR`, and the extension's global default."""
    paths = [Path(cwd) / ".pi" / "messenger" / "feed.jsonl"]
    if os.environ.get("PI_MESSENGER_DIR"):
        paths.append(Path(os.environ["PI_MESSENGER_DIR"]) / "feed.jsonl")
    paths.append(Path.home() / ".pi" / "agent" / "messenger" / "feed.jsonl")
    return paths


def _feed_offsets(paths: list[Path]) -> dict[Path, int]:
    return {p: (p.stat().st_size if p.is_file() else 0) for p in paths}


def find_delivery(offsets: dict[Path, int], *, to: str, sender: str) -> dict | None:
    """The first `{"type": "message", "agent": sender, "target": to}` line written to any feed AFTER the
    recorded offsets -- the independently checkable proof of delivery, never the courier's own report."""
    for path, start in offsets.items():
        if not path.is_file():
            continue
        with open(path, "rb") as f:
            f.seek(start if path.stat().st_size >= start else 0)
            for raw in f:
                try:
                    line = json.loads(raw)
                except ValueError:
                    continue
                if line.get("type") == "message" and line.get("target") == to and line.get("agent") == sender:
                    return {**line, "_feed": str(path)}
    return None


@dataclass
class SendResult:
    delivered: bool
    feed_line: dict | None
    returncode: int | None
    timed_out: bool
    cost_usd: float
    session_file: Path | None


def send_message(
    to: str,
    text: str,
    *,
    cwd: str | Path,
    sender: str = "Dispatcher",
    provider: str = "deepseek",
    model: str = "deepseek-flash",
    thinking: str = "low",
    timeout_seconds: float = 300,
    session_dir: str | Path | None = None,
    feed_paths: list[Path] | None = None,
    cap_usd: float | None = None,
) -> SendResult:
    """Deliver `text` as a pi-messenger DM to the running session named `to` (issue #15). pi-messenger has
    no sending CLI, so this runs a one-shot courier `pi -p` (cheap model by default) as `PI_AGENT_NAME=sender`
    with stdin closed (an open stdin makes `pi -p` hang) and a verbatim-preserving prompt, then checks
    pi-messenger's own `feed.jsonl` for the message line. `delivered` is True only if that line appeared.

    The DM reaches the recipient at its next tool boundary, not as an interrupt (docs/pi-messenger-and-
    subagents-tested-claims.md, M2). The recipient must have joined the mesh (`pi-wave-session launch` does
    that). `cwd` must be the recipient's project directory (where its `.pi/messenger/` lives)."""
    from .run_pi import run_pi  # lazy: keeps this module importable without the ledger client

    paths = feed_paths or feed_candidates(cwd)
    offsets = _feed_offsets(paths)
    result = run_pi(
        f"send-{sender}-to-{to}", provider=provider, model=model, thinking=thinking, prompt=send_prompt(to, text),
        cwd=cwd, session_dir=session_dir or Path(cwd) / "pi-wave-jobs" / sender / "sessions",
        timeout_seconds=timeout_seconds, env={"PI_AGENT_NAME": sender}, cap_usd=cap_usd, poll_seconds=1.0,
    )
    line = find_delivery(offsets, to=to, sender=sender)
    return SendResult(delivered=line is not None, feed_line=line, returncode=result.returncode,
                      timed_out=result.timed_out, cost_usd=result.cost_usd, session_file=result.session_file)


def _multiplexer(name: str) -> str:
    """"screen" if a screen session of that name is alive, else "tmux" if tmux has it (agent-watch-daemon
    launches use tmux), else ""."""
    try:
        if is_alive(ScreenSession(name=name, log_path=None)):
            return "screen"
    except FileNotFoundError:
        pass
    try:
        if subprocess.run(["tmux", "has-session", "-t", name], capture_output=True).returncode == 0:
            return "tmux"
    except FileNotFoundError:
        pass
    return ""


def _snapshot(name: str, mux: str, scratch: Path) -> str:
    if mux == "tmux":
        return subprocess.run(["tmux", "capture-pane", "-p", "-t", name], capture_output=True, text=True,
                              errors="replace").stdout
    return hardcopy(ScreenSession(name=name, log_path=None), scratch)


class NotIdleError(RuntimeError):
    pass


def type_into(
    name: str,
    text: str,
    *,
    enter: bool = True,
    if_idle: bool = False,
    idle_seconds: float = 3.0,
    audit_path: str | Path | None = None,
    scratch_dir: str | Path | None = None,
) -> dict:
    """Type `text` into the terminal of the running session `name`, as if a human attached and typed it
    (issue #16); `enter` appends a carriage return (the Enter key). These are KEYSTROKES, not a message:
    they land wherever the cursor is, immediately -- a session that is generating receives them mid-stream.
    Use `send_message` (a mesh DM, read at the next tool boundary) unless the session is wedged or not on
    the mesh.

    The text is handed over through a file and screen's `readreg` + `paste` (tmux: `load-buffer` +
    `paste-buffer -r`), so no character of it is interpreted by the multiplexer (`stuff` would parse `^X`
    and backslash escapes). Newlines inside `text` are typed as newlines; a TUI may treat them as Enter.

    `if_idle`: refuse (NotIdleError) unless two snapshots `idle_seconds` apart are identical -- a heuristic
    (a streaming answer or a spinner changes the screen), not a guarantee: a session silently waiting on a
    long tool call also looks idle. Every injection is appended to `audit_path` (JSONL, type "inject"), the
    auditable record a keystroke otherwise never leaves; it is NOT written into pi-messenger's own feed,
    which belongs to that extension."""
    mux = _multiplexer(name)
    if not mux:
        raise LookupError(f"no running screen or tmux session named {name!r}")
    scratch = Path(scratch_dir) if scratch_dir else Path(os.environ.get("TMPDIR", "/tmp"))
    scratch.mkdir(parents=True, exist_ok=True)
    tag = f"pwk-{os.getpid()}-{name}"
    if if_idle:
        import time

        first = _snapshot(name, mux, scratch / f"{tag}-a.txt")
        time.sleep(idle_seconds)
        second = _snapshot(name, mux, scratch / f"{tag}-b.txt")
        if first != second:
            raise NotIdleError(f"{name}: terminal changed within {idle_seconds:g}s (still working?); not typing")
    payload = scratch / f"{tag}-payload.txt"
    payload.write_bytes(text.encode("utf-8") + (b"\r" if enter else b""))
    try:
        if mux == "screen":
            subprocess.run(["screen", "-S", name, "-X", "readreg", "p", str(payload)], check=True)
            subprocess.run(["screen", "-S", name, "-X", "paste", "p"], check=True)
        else:
            subprocess.run(["tmux", "load-buffer", "-b", tag, str(payload)], check=True)
            subprocess.run(["tmux", "paste-buffer", "-d", "-r", "-b", tag, "-t", name], check=True)
    finally:
        payload.unlink(missing_ok=True)
    from datetime import datetime, timezone

    record = {"ts": datetime.now(timezone.utc).isoformat(), "type": "inject", "target": name, "via": mux,
              "enter": enter, "if_idle": if_idle, "text": text}
    if audit_path:
        audit_path = Path(audit_path)
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        with open(audit_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record

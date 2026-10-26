"""Launch, inspect, and stop a long-lived INTERACTIVE `pi` session wrapped in `screen`, so it stays
alive and reachable the way `pi -p` and a backgrounded interactive session with no real pty cannot.

Confirmed live, 2026-10-24 (re-verifying `pi-gatekeeper`'s own earlier finding, not just trusting the
note): `pi -p` processes one prompt and exits -- it has no "stay alive, idle, listening" state.
Backgrounding an *interactive* session with stdin pointed at `/dev/null` doesn't work either: without a
real pty, `pi` reads EOF on its next input and exits after one turn, indistinguishable from `-p` mode. A
real pty is required. This machine has `screen` but not `tmux`, so this module uses `screen -dmS`
(detached, named) the same way `pi-gatekeeper/launch_gatekeeper.sh` does.

**This module does NOT send messages to the session.** There is no sending CLI for pi-messenger --
its npm package's only `bin` entry is an installer (`install.mjs`), confirmed by reading its own
`package.json`. The only real way to message an already-running session from "elsewhere" is to run
ANOTHER `pi` agent that calls the `pi_messenger` tool itself, which is just
`pi_wave_kit.run_pi.run_pi()` with a prompt telling it to do that -- no new wrapper code is needed for
sending, only for launching/inspecting/stopping the long-lived target. Confirmed live together with
this module's launch path: a session started here, with `.pi/pi-messenger.json` set to
`{"autoRegister": true}` in its working directory, received a DM from a separate one-shot `pi -p`
process and replied 1.3 s later -- verified from pi-messenger's own `feed.jsonl`, not the model's
self-report of what happened.

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

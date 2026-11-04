"""Console-script CLI (`pi-wave-session`) over `pi_wave_kit.interactive`: launch, check, inspect, and
stop a long-lived, remotely-reachable interactive `pi` session -- without writing any Python.

A separate entrypoint from `pi_wave_kit.cli` (`pi-wave-job`) on purpose: that one is for a single
ad-hoc, run-to-completion job; this is a different process shape -- a session that stays alive and
is meant to be reached again later, from elsewhere (see `interactive.py`'s module docstring for the
real mechanism and its real constraint: screen for a pty, pi-messenger `autoRegister` for the mesh).

`launch` does one thing `pi_wave_kit.interactive.launch_screen_session()` alone does not: it also
ensures the one piece of config that function deliberately leaves to the caller (pi-messenger's own
`autoRegister`) is actually in place in the target working directory, so the session this command
starts is really remotely reachable, not just alive in a pty. See the README's "Launching a
remotely-reachable session" section for the exact equivalent by-hand terminal command and how to
message a launched session from elsewhere.

By default, `launch` tries `agent-watch-daemon`'s local API first, so the session is immediately
steerable from the agent-watch web app if that laptop daemon is running -- falling straight through
to the plain screen launch, unchanged, if it isn't. See `launch_screen_session()`'s own docstring
for the exact fallback behavior and the recursion guard that stops the daemon's own internal
`pi-wave-session launch` call from looping back into itself.

Usage:
  pi-wave-session launch <name> <model> <workdir> (--prompt-file FILE | --prompt TEXT)
      [--provider P] [--thinking T] [--jobs-dir DIR] [--no-mesh] [--no-approve] [--no-watch]
  pi-wave-session status <name>
  pi-wave-session hardcopy <name> [--jobs-dir DIR] [-o OUT]
  pi-wave-session stop <name>
  pi-wave-session send <name> (TEXT | --text-file F) [--from NAME] [--workdir DIR] [--model M] [--timeout S]
  pi-wave-session type <name> (TEXT | --text-file F) [--no-enter] [--if-idle] [--jobs-dir DIR]

`send` (issue #15) and `type` (issue #16) are the two ways to reach a running session; see
`pi_wave_kit.interactive.send_message` / `type_into` for how each works and when to use which.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .interactive import NotIdleError, ScreenSession, is_alive, launch_screen_session, send_message, type_into
from .interactive import hardcopy as _hardcopy
from .interactive import stop as _stop


def _ensure_mesh_autoregister(workdir: Path) -> None:
    """Write `{"autoRegister": true}` into `<workdir>/.pi/pi-messenger.json` if that file doesn't
    already exist. Never overwrites an existing file -- a project with its own pi-messenger config
    keeps it untouched; this only fills the gap for a workdir that has none, so `launch` alone is
    enough to produce a reachable session instead of just an alive one."""
    cfg_path = workdir / ".pi" / "pi-messenger.json"
    if cfg_path.exists():
        return
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(json.dumps({"autoRegister": True}, indent=1) + "\n", encoding="utf-8")


def _cmd_launch(args: argparse.Namespace) -> int:
    workdir = Path(args.workdir)
    if args.prompt_file:
        prompt_path = Path(args.prompt_file)
        if not prompt_path.is_file():
            print(f"pi-wave-session: no such prompt file: {prompt_path}", file=sys.stderr)
            return 2
        initial_prompt = prompt_path.read_text(encoding="utf-8")
    else:
        initial_prompt = args.prompt

    out = Path(args.jobs_dir) / args.name
    out.mkdir(parents=True, exist_ok=True)
    session_dir = out / "sessions"
    log_path = out / "screen.log"

    if not args.no_mesh:
        _ensure_mesh_autoregister(workdir)

    session = launch_screen_session(
        args.name, provider=args.provider, model=args.model, thinking=args.thinking,
        cwd=workdir, session_dir=session_dir, initial_prompt=initial_prompt,
        log_path=log_path, approve=not args.no_approve,
        register_with_daemon=not args.no_watch,
    )
    print(f"pi-wave-session: launched {session.name!r} (screen -ls will show it), "
          f"cwd={workdir}, session_dir={session_dir}")
    print(f"pi-wave-session: attach by hand any time with: screen -r {session.name}")
    print(f"pi-wave-session: check from here with:          pi-wave-session status {session.name}")
    print(f"pi-wave-session: message it later with:         pi-wave-session send {session.name} 'text' --workdir {workdir}")
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    alive = is_alive(ScreenSession(name=args.name, log_path=None))
    print(f"{args.name}: {'alive' if alive else 'not running'}")
    return 0 if alive else 1


def _cmd_hardcopy(args: argparse.Namespace) -> int:
    out_path = Path(args.out) if args.out else Path(args.jobs_dir) / args.name / "hardcopy.txt"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    text = _hardcopy(ScreenSession(name=args.name, log_path=None), out_path)
    print(text)
    print(f"pi-wave-session: written to {out_path}", file=sys.stderr)
    return 0


def _cmd_stop(args: argparse.Namespace) -> int:
    _stop(ScreenSession(name=args.name, log_path=None))
    print(f"pi-wave-session: stop requested for {args.name!r}")
    return 0


def _read_text(args: argparse.Namespace, prog: str) -> str | None:
    if args.text_file:
        path = Path(args.text_file)
        if not path.is_file():
            print(f"{prog}: no such text file: {path}", file=sys.stderr)
            return None
        text = path.read_text(encoding="utf-8")
    else:
        text = args.text or ""
    if not text.strip():
        print(f"{prog}: nothing to send (empty text)", file=sys.stderr)
        return None
    return text


def _cmd_send(args: argparse.Namespace) -> int:
    text = _read_text(args, "pi-wave-session send")
    if text is None:
        return 2
    result = send_message(
        args.name, text, cwd=Path(args.workdir), sender=args.sender, provider=args.provider, model=args.model,
        thinking=args.thinking, timeout_seconds=args.timeout, cap_usd=args.cap_usd,
        session_dir=Path(args.jobs_dir) / args.sender / "sessions",
    )
    if result.delivered:
        print(f"pi-wave-session: delivered to {args.name} (feed: {result.feed_line.get('_feed')}, "
              f"ts {result.feed_line.get('ts', '?')}), courier cost ${result.cost_usd:.4f}")
        return 0
    print(f"pi-wave-session: NOT confirmed: no message line from {args.sender} to {args.name} appeared in "
          f"pi-messenger's feed.jsonl (courier returncode={result.returncode}, timed_out={result.timed_out}, "
          f"cost ${result.cost_usd:.4f}, session {result.session_file}). Is {args.name} on the mesh, and is "
          f"--workdir its project directory?", file=sys.stderr)
    return 1


def _cmd_type(args: argparse.Namespace) -> int:
    text = _read_text(args, "pi-wave-session type")
    if text is None:
        return 2
    try:
        record = type_into(args.name, text, enter=not args.no_enter, if_idle=args.if_idle,
                           idle_seconds=args.idle_seconds,
                           audit_path=Path(args.jobs_dir) / args.name / "inject.jsonl",
                           scratch_dir=Path(args.jobs_dir) / args.name)
    except LookupError as exc:
        print(f"pi-wave-session type: {exc}", file=sys.stderr)
        return 1
    except NotIdleError as exc:
        print(f"pi-wave-session type: refused: {exc}", file=sys.stderr)
        return 3
    print(f"pi-wave-session: typed {len(text)} characters into {args.name} via {record['via']}"
          f"{' + Enter' if record['enter'] else ''}; logged to {Path(args.jobs_dir) / args.name / 'inject.jsonl'}")
    return 0


DESCRIPTION = """\
Launch, reach and stop long-lived INTERACTIVE pi sessions that stay alive in a real pty (screen)
and are joined to the pi-messenger mesh, so they can be steered later from anywhere.

A headless `pi -p` answers one prompt and exits; an interactive session without a real pty dies
after one turn. A session is only reachable later if it was LAUNCHED this way: screen for the pty,
PI_AGENT_NAME=<name> for its mesh identity, autoRegister in <workdir>/.pi/pi-messenger.json.

Three ways to reach a running session, and when each is right:
  send      a pi-messenger DM (the default). The agent reads it at its next tool boundary, as a
            message it can reason about. Needs the session on the mesh. Confirmed from
            pi-messenger's own feed.jsonl, never from the courier's report. Costs one cheap
            courier call (deepseek-flash by default).
  type      raw keystrokes into its terminal, immediately, wherever the cursor is. For a wedged or
            unjoined session. Lands mid-stream if it is generating: use --if-idle. Free; logged to
            <jobs-dir>/<name>/inject.jsonl (it leaves no trace in the mesh feed).
  hardcopy  read its current screen. Read-only, always safe, free.

For a one-shot job that should NOT stay alive, use pi-wave-job; for a capped batch, pi-wave-run."""

EPILOG = """\
examples:
  pi-wave-session launch Home deepseek-flash ~/proj --prompt "Standby." --provider deepseek
  pi-wave-session status Home
  pi-wave-session send Home "Correction: use the 2nd edition." --workdir ~/proj
  pi-wave-session type Home "/compact" --if-idle
  pi-wave-session hardcopy Home
  pi-wave-session stop Home

by hand, without this library (README, "Launching a remotely-reachable session"):
  PI_AGENT_NAME=Home screen -dmS Home pi --provider deepseek --model deepseek-flash --name Home --approve "Standby."

Python: pi_wave_kit.interactive.launch_screen_session / send_message / type_into / hardcopy / stop."""


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="pi-wave-session", description=DESCRIPTION, epilog=EPILOG,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True, metavar="{launch,status,send,type,hardcopy,stop}")
    raw = argparse.RawDescriptionHelpFormatter

    launch = sub.add_parser(
        "launch", help="start a new screen-wrapped, mesh-joined session", formatter_class=raw,
        description="Start pi interactively inside `screen -dmS <name>`, with PI_AGENT_NAME=<name>, after "
                    "writing {\"autoRegister\": true} to <workdir>/.pi/pi-messenger.json if that file is missing "
                    "(never overwritten). Tries agent-watch-daemon's local API first so the session is steerable "
                    "from its web app; falls back to the plain screen launch when the daemon is not running.",
        epilog="to message this session later:  pi-wave-session send <name> 'text' --workdir <workdir>\n"
               "to type into its terminal:      pi-wave-session type <name> 'text' --if-idle\n"
               "to watch it:                    pi-wave-session hardcopy <name>   (or: screen -r <name>)")
    launch.add_argument("name", help="session name: its screen name, its pi-messenger name and its output subdir")
    launch.add_argument("model", help="model name passed to pi --model")
    launch.add_argument("workdir", help="pi's working directory -- also where .pi/pi-messenger.json is ensured")
    prompt_group = launch.add_mutually_exclusive_group(required=True)
    prompt_group.add_argument("--prompt-file", help="path to a file whose content is the session's initial message")
    prompt_group.add_argument("--prompt", help="the session's initial message, given directly")
    launch.add_argument("--provider", default="deepseek", help="default: deepseek")
    launch.add_argument("--thinking", default="low", help="default: low")
    launch.add_argument("--jobs-dir", default="pi-wave-jobs", metavar="DIR",
                        help="parent directory for this session's output: sessions/, screen.log (default: ./pi-wave-jobs)")
    launch.add_argument("--no-mesh", action="store_true",
                        help="don't ensure pi-messenger autoRegister config -- the launched session "
                             "will be alive but not remotely reachable unless workdir already has its own config")
    launch.add_argument("--no-approve", action="store_true", help="don't pass --approve to pi")
    launch.add_argument("--no-watch", action="store_true",
                        help="don't try agent-watch-daemon's local API first -- always go straight to "
                             "the direct screen launch, even if the daemon is running. The session is "
                             "still screen-wrapped and resumable either way (for a session with no "
                             "multiplexer at all, use pi-wave-job instead, not this flag).")
    launch.set_defaults(func=_cmd_launch)

    status = sub.add_parser("status", help="check whether a session is still running (exit 0 alive, 1 not)")
    status.add_argument("name")
    status.set_defaults(func=_cmd_status)

    send = sub.add_parser(
        "send", help="DM a running session over pi-messenger, confirmed from feed.jsonl", formatter_class=raw,
        description="Deliver a message to a running, mesh-joined session. A one-shot courier `pi -p` runs as "
                    "PI_AGENT_NAME=<--from>, stdin closed, with the text quoted verbatim between markers, and "
                    "is told to send it unchanged with the pi_messenger tool. Exit 0 only if pi-messenger's own "
                    "feed.jsonl (in <workdir>/.pi/messenger/, $PI_MESSENGER_DIR or ~/.pi/agent/messenger/) gets "
                    "a message line from the courier to <name>; 1 otherwise. The recipient reads it at its next "
                    "tool boundary, not as an interrupt. Paid: one courier call on --model.")
    send.add_argument("name", help="the recipient's pi-messenger name (the name it was launched with)")
    send_text = send.add_mutually_exclusive_group(required=True)
    send_text.add_argument("text", nargs="?", help="the message text")
    send_text.add_argument("--text-file", metavar="FILE", help="read the message text from FILE")
    send.add_argument("--from", dest="sender", default="Dispatcher", metavar="NAME",
                      help="the courier's mesh name (default: Dispatcher)")
    send.add_argument("--workdir", default=".", metavar="DIR",
                      help="the recipient's project directory, where its .pi/messenger/ lives (default: .)")
    send.add_argument("--provider", default="deepseek", help="courier provider (default: deepseek)")
    send.add_argument("--model", default="deepseek-flash", help="courier model, the cheapest is enough (default: deepseek-flash)")
    send.add_argument("--thinking", default="low", help="courier thinking level (default: low)")
    send.add_argument("--timeout", type=float, default=300, metavar="SECONDS", help="kill the courier after this (default: 300)")
    send.add_argument("--cap-usd", type=float, default=0.05, metavar="USD",
                      help="live cost cap for the courier (default: 0.05)")
    send.add_argument("--jobs-dir", default="pi-wave-jobs", metavar="DIR",
                      help="the courier's sessions go to <jobs-dir>/<--from>/sessions (default: ./pi-wave-jobs)")
    send.set_defaults(func=_cmd_send)

    typ = sub.add_parser(
        "type", help="type keystrokes into a running session's terminal (screen/tmux)", formatter_class=raw,
        description="Type text into the session's terminal as if you had attached and typed it, then press Enter. "
                    "These are keystrokes, NOT a message: they land immediately, wherever the cursor is; a session "
                    "that is generating receives them mid-stream and its input can be corrupted. Prefer `send`; "
                    "use this for a wedged session or one that is not on the mesh. The text goes through a file "
                    "(screen readreg/paste, tmux load-buffer/paste-buffer), so no character is interpreted. Every "
                    "injection is logged to <jobs-dir>/<name>/inject.jsonl. Exit 0 typed, 1 no such session, "
                    "3 refused by --if-idle.")
    typ.add_argument("name", help="the screen (or tmux) session name")
    typ_text = typ.add_mutually_exclusive_group(required=True)
    typ_text.add_argument("text", nargs="?", help="the text to type")
    typ_text.add_argument("--text-file", metavar="FILE", help="read the text from FILE")
    typ.add_argument("--no-enter", action="store_true", help="do not press Enter after the text")
    typ.add_argument("--if-idle", action="store_true",
                     help="refuse unless the terminal is unchanged over --idle-seconds (a heuristic: a streaming "
                          "answer changes the screen; a silent long tool call also looks idle)")
    typ.add_argument("--idle-seconds", type=float, default=3.0, metavar="S", help="default: 3")
    typ.add_argument("--jobs-dir", default="pi-wave-jobs", metavar="DIR",
                     help="audit log and scratch files under <jobs-dir>/<name>/ (default: ./pi-wave-jobs)")
    typ.set_defaults(func=_cmd_type)

    hardcopy = sub.add_parser("hardcopy", help="dump a session's current terminal contents (read-only)")
    hardcopy.add_argument("name")
    hardcopy.add_argument("--jobs-dir", default="pi-wave-jobs", metavar="DIR")
    hardcopy.add_argument("-o", "--out", help="where to write the dump (default: <jobs-dir>/<name>/hardcopy.txt)")
    hardcopy.set_defaults(func=_cmd_hardcopy)

    stop = sub.add_parser("stop", help="stop a running session (screen quit)")
    stop.add_argument("name")
    stop.set_defaults(func=_cmd_stop)

    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

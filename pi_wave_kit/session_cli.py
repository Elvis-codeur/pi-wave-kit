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

Usage:
  pi-wave-session launch <name> <model> <workdir> (--prompt-file FILE | --prompt TEXT)
      [--provider P] [--thinking T] [--jobs-dir DIR] [--no-mesh] [--no-approve]
  pi-wave-session status <name>
  pi-wave-session hardcopy <name> [--jobs-dir DIR] [-o OUT]
  pi-wave-session stop <name>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .interactive import ScreenSession, is_alive, launch_screen_session
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
    )
    print(f"pi-wave-session: launched {session.name!r} (screen -ls will show it), "
          f"cwd={workdir}, session_dir={session_dir}")
    print(f"pi-wave-session: attach by hand any time with: screen -r {session.name}")
    print(f"pi-wave-session: check from here with:          pi-wave-session status {session.name}")
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


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="pi-wave-session",
        description="Launch/inspect/stop a long-lived, remotely-reachable interactive pi session "
                    "(a real pty via screen, joined to the pi-messenger mesh).",
    )
    sub = p.add_subparsers(dest="command", required=True)

    launch = sub.add_parser("launch", help="start a new screen-wrapped, mesh-joined session")
    launch.add_argument("name", help="session name -- also its screen scope name and output subdir")
    launch.add_argument("model", help="model name passed to pi --model")
    launch.add_argument("workdir", help="pi's working directory -- also where .pi/pi-messenger.json is ensured")
    prompt_group = launch.add_mutually_exclusive_group(required=True)
    prompt_group.add_argument("--prompt-file", help="path to a file whose content is the session's initial message")
    prompt_group.add_argument("--prompt", help="the session's initial message, given directly")
    launch.add_argument("--provider", default="deepseek", help="default: deepseek")
    launch.add_argument("--thinking", default="low", help="default: low")
    launch.add_argument("--jobs-dir", default="pi-wave-jobs", metavar="DIR",
                         help="parent directory for this session's output (default: ./pi-wave-jobs)")
    launch.add_argument("--no-mesh", action="store_true",
                         help="don't ensure pi-messenger autoRegister config -- the launched session "
                             "will be alive but not remotely reachable unless workdir already has its own config")
    launch.add_argument("--no-approve", action="store_true", help="don't pass --approve to pi")
    launch.set_defaults(func=_cmd_launch)

    status = sub.add_parser("status", help="check whether a session is still running")
    status.add_argument("name")
    status.set_defaults(func=_cmd_status)

    hardcopy = sub.add_parser("hardcopy", help="dump a session's current terminal contents")
    hardcopy.add_argument("name")
    hardcopy.add_argument("--jobs-dir", default="pi-wave-jobs", metavar="DIR")
    hardcopy.add_argument("-o", "--out", help="where to write the dump (default: <jobs-dir>/<name>/hardcopy.txt)")
    hardcopy.set_defaults(func=_cmd_hardcopy)

    stop = sub.add_parser("stop", help="stop a running session")
    stop.add_argument("name")
    stop.set_defaults(func=_cmd_stop)

    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

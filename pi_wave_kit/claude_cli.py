"""Console-script CLI (`pi-wave-claude`) over `pi_wave_kit.claude_sessions`: drive Claude Code's
NATIVE background sessions without writing Python -- start with `claude --bg`, list/status, read
logs, attach and steer through screen, wait, stop/remove, plus one clean one-shot JSON job.

A separate entrypoint from `pi-wave-job`, `pi-wave-session` and `pi-wave-run` because this is a
different process shape and a different Claude mode:

- `pi-wave-job --agent claude` runs `claude -p --output-format json`: one request, one JSON answer,
  real token counts and reported cost. The prompt is read once and passed as argv.
- `pi-wave-claude start` runs `claude --bg`: a detached session that survives the launching shell,
  reports progress as a TUI, and is steered by typing into its terminal. `--bg` and `-p/--print`
  conflict, so this CLI never adds `-p`.
- `pi-wave-claude job` is the clean one-shot path inside this CLI (a thin wrapper over
  `pi_wave_kit.agents.run_agent("claude", ...)`), writing text/session_id/model/usage/cost.

Identifier safety: every command that takes `<id|name>` resolves it through
`claude_sessions.get_session()` -- short id, full sessionId, or exact name -- and every mutating
command then re-resolves the live record and passes only its short id to `claude stop`/`claude rm`.
An unknown or ambiguous name is an error; it is never "close enough", because `claude agents --json`
lists every Claude session on the machine, including the owner's interactive ones.

Logs are recent TUI output with ANSI escapes; the CLI strips them unless `--raw` is passed. For
clean output and cost, use `job` (or `pi-wave-job --agent claude`), and `--model` + an earlier
job's `session_id` with `agents.run_agent(..., session_id=...)` for deterministic follow-ups.

Exit codes: 0 success; 1 command/session failure (not found, Claude error, stop/rm refused); 2 bad
input/options; 3 workspace not trusted (accept trust once in that directory; `-p` skips trust);
4 `wait` timed out. `job` exits 0 only if Claude exited 0 and was not killed.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from . import claude_sessions
from .claude_sessions import (
    ClaudeError,
    ClaudeSessionAmbiguousError,
    ClaudeSessionNotFoundError,
    ClaudeUnavailableError,
    ClaudeUnsupportedError,
    ClaudeWaitTimeoutError,
    WorkspaceNotTrustedError,
)

DESCRIPTION = """\
Start, inspect, steer and stop Claude Code BACKGROUND sessions (`claude --bg`), or run one clean
one-shot Claude job (`claude -p --output-format json`) -- without writing Python.

`--bg` starts a session that outlives this command and prints a short id; `-p` runs one prompt and
exits with JSON. They cannot be combined (Claude: "--bg and --print conflict"), so this CLI keeps
them apart: `start` uses --bg, `job` uses -p.

A background session needs an accepted workspace trust. In an untrusted directory `start` fails
with Claude's own "Workspace not trusted" message and exit 3; opening `claude` once in that
directory and accepting trust fixes it. `claude agents --json` lists ALL sessions on the machine,
including your interactive ones, so every <id|name> is resolved exactly and stop/rm use the
resolved short id -- never a guessed or ambiguous name.

Logs and attach are TUI-oriented: `logs` is ANSI-heavy terminal output (stripped by default), and
`attach`/`steer` need a real TTY, which this CLI provides with a detached screen session. Typed
input may queue or interrupt depending on Claude's state; there is no non-TTY send command. For
clean JSON output and deterministic follow-ups, use `job` (or pi-wave-job --agent claude) and pass
the earlier session_id to the Python API's `session_id=`/`--session`.

Output records: `start` writes <jobs-dir>/<name>/session.json; `job` writes
<jobs-dir>/<name>/result.json; `steer` appends to <jobs-dir>/<id-or-name>/inject.jsonl."""

EPILOG = """\
examples:
  pi-wave-claude job review review.md --cwd ~/repo --model haiku
  pi-wave-claude job review-2 review-2.md --cwd ~/repo --session <session_id from result.json>
  pi-wave-claude start audit-bg --prompt "Audit the test suite" --cwd ~/repo --model haiku
  pi-wave-claude start docs-bg --prompt-file docs-task.md --cwd ~/repo --jobs-dir work
  pi-wave-claude list --cwd ~/repo                    # active sessions in this directory
  pi-wave-claude list --all --json                    # include completed background sessions
  pi-wave-claude status audit-bg
  pi-wave-claude logs audit-bg
  pi-wave-claude logs audit-bg --raw                  # keep ANSI TUI escapes
  pi-wave-claude attach audit-bg                      # opens screen; detach with Ctrl-A d
  pi-wave-claude steer audit-bg "Also check the docs" # screen attach + keystrokes + Enter
  pi-wave-claude wait audit-bg --timeout 600
  pi-wave-claude stop audit-bg
  pi-wave-claude rm audit-bg                          # finished session, conversation kept

Related commands: pi-wave-job (one-shot job, any agent), pi-wave-run (capped wave over prompt
files), pi-wave-session (long-lived interactive pi session). Python API:
pi_wave_kit.claude_sessions (background lifecycle) and pi_wave_kit.agents (one-shot/resume)."""


# --------------------------------------------------------------------------------------------------
# Shared helpers
# --------------------------------------------------------------------------------------------------


def _safe_record_name(name: str) -> str:
    """A filename-safe component for <jobs-dir>/<name>/: session names are user-chosen, and a name
    like `../../x` must never be able to escape the jobs directory."""
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", name or "").strip("._-")
    return safe or "session"


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8")


def _read_prompt(path: str, prog: str) -> str | None:
    prompt_path = Path(path)
    if not prompt_path.is_file():
        print(f"{prog}: no such prompt file: {prompt_path}", file=sys.stderr)
        return None
    prompt = prompt_path.read_text(encoding="utf-8")
    if not prompt.strip():
        print(f"{prog}: empty prompt file: {prompt_path}", file=sys.stderr)
        return None
    return prompt


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


def _claude_extra_args(args: argparse.Namespace) -> list[str]:
    """The Claude argv options a caller asked for, in a stable order.

    `--extra-arg` is the escape hatch; the typed options above it are conveniences for the flags
    this repo's own security/automation sessions need. Any value that itself starts with `--` must
    use the `--extra-arg=--flag` form, because argparse would otherwise treat it as one of its own.
    """
    extra = list(getattr(args, "extra_args", None) or [])
    if getattr(args, "allowed_tools", None):
        extra += ["--allowedTools", args.allowed_tools]
    if getattr(args, "permission_mode", None):
        extra += ["--permission-mode", args.permission_mode]
    for directory in getattr(args, "add_dirs", None) or []:
        extra += ["--add-dir", str(directory)]
    return extra


def _add_claude_options(parser: argparse.ArgumentParser) -> None:
    """Claude-side flags shared by `job` (print mode) and `start` (background mode)."""
    parser.add_argument("--allowed-tools", default=None, metavar="LIST",
                        help="passed to Claude as --allowedTools, e.g. 'Read,Grep,Glob,Write,Edit,WebFetch'")
    parser.add_argument("--permission-mode", default=None,
                        choices=["acceptEdits", "auto", "bypassPermissions", "manual", "dontAsk", "plan"],
                        help="passed to Claude as --permission-mode")
    parser.add_argument("--add-dir", dest="add_dirs", action="append", default=[], metavar="DIR",
                        help="extra directory Claude may access (repeatable; passed as --add-dir)")
    parser.add_argument("--extra-arg", dest="extra_args", action="append", default=[], metavar="ARG",
                        help="raw Claude argument (repeatable); use --extra-arg=--flag for values starting with --")


def _session_line(session: claude_sessions.ClaudeSession) -> str:
    return (f"id={session.short_id} name={session.name or '-'} kind={session.kind or '-'} "
            f"status={session.status or '-'} state={session.state or '-'} cwd={session.cwd}")


# --------------------------------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------------------------------


def _cmd_job(args: argparse.Namespace) -> int:
    prompt = _read_prompt(args.prompt_file, "pi-wave-claude job")
    if prompt is None:
        return 2
    cwd = Path(args.cwd).expanduser()
    if not cwd.is_dir():
        print(f"pi-wave-claude job: no such working directory: {cwd}", file=sys.stderr)
        return 2
    out = Path(args.jobs_dir) / _safe_record_name(args.name)
    result = claude_sessions.run_job(
        args.name, prompt=prompt, model=args.model or "", cwd=cwd, out_dir=out,
        session_id=args.session, timeout_seconds=args.timeout,
        extra_args=_claude_extra_args(args),
    )
    payload = {
        "job_id": result.job_id,
        "agent": result.agent,
        "returncode": result.returncode,
        "wall_seconds": result.wall_seconds,
        "session_id": result.session_id,
        "text": result.text,
        "error": result.error,
        "provider": result.provider,
        "model": result.model,
        "billing": result.billing,
        "cost_usd": result.reported_cost_usd,
        "cost": result.reported_cost_usd,
        "timed_out": result.timed_out,
        "usage": {
            "prompt_tokens": result.prompt_tokens,
            "completion_tokens": result.completion_tokens,
            "cache_read_tokens": result.cache_read_tokens,
            "cache_creation_tokens": result.cache_creation_tokens,
            "reasoning_tokens": result.reasoning_tokens,
            "reported_cost_usd": result.reported_cost_usd,
            "usage_extra": result.usage_extra,
        },
        "output_path": str(result.output_path) if result.output_path else None,
        "extra": result.extra,
    }
    result_path = out / "result.json"
    _write_json(result_path, payload)
    print(f"pi-wave-claude job: {args.name} agent=claude returncode={result.returncode} "
          f"cost_usd={result.reported_cost_usd:.4f} wall_seconds={result.wall_seconds:.1f} "
          f"session_id={result.session_id or '-'}"
          f"{' error=' + result.error[:200] if result.error else ''}")
    print(f"pi-wave-claude job: result written to {result_path}")
    return 0 if result.ok else 1


def _cmd_start(args: argparse.Namespace) -> int:
    if args.prompt_file:
        prompt = _read_prompt(args.prompt_file, "pi-wave-claude start")
        if prompt is None:
            return 2
    else:
        prompt = args.prompt or ""
        if not prompt.strip():
            print("pi-wave-claude start: empty prompt", file=sys.stderr)
            return 2
    cwd = Path(args.cwd).expanduser()
    if not cwd.is_dir():
        print(f"pi-wave-claude start: no such working directory: {cwd}", file=sys.stderr)
        return 2

    session = claude_sessions.start_background(
        args.name, prompt, cwd=cwd, model=args.model, extra_args=_claude_extra_args(args)
    )
    record_path = Path(args.jobs_dir) / _safe_record_name(args.name) / "session.json"
    payload = session.to_dict()
    payload["prompt_chars"] = len(prompt)
    _write_json(record_path, payload)
    print(f"pi-wave-claude: started background session {session.label} in {session.cwd}")
    print(f"pi-wave-claude: attach: pi-wave-claude attach {session.short_id}    "
          f"logs: pi-wave-claude logs {session.short_id}    "
          f"wait: pi-wave-claude wait {session.short_id}")
    print(f"pi-wave-claude: record written to {record_path}")
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    sessions = claude_sessions.list_sessions(include_completed=args.all, cwd=args.cwd)
    if args.json:
        print(json.dumps([s.to_dict() for s in sessions], indent=1, ensure_ascii=False))
        return 0
    if not sessions:
        print("pi-wave-claude: no matching Claude sessions")
        return 0
    for session in sessions:
        print(f"{session.short_id:<10} {session.name or '-':<24} {session.kind or '-':<11} "
              f"{session.state or session.status or '-':<9} {session.cwd}")
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    session = claude_sessions.get_session(args.identifier)
    if args.json:
        print(json.dumps(session.to_dict(), indent=1, ensure_ascii=False))
    else:
        print(_session_line(session))
        print(f"session_id={session.session_id or '-'} pid={session.pid if session.pid is not None else '-'} "
              f"started_at={session.started_at or '-'} done={session.is_done}")
    return 0


def _cmd_logs(args: argparse.Namespace) -> int:
    text = claude_sessions.logs(args.identifier, raw=args.raw)
    sys.stdout.write(text)
    if text and not text.endswith("\n"):
        sys.stdout.write("\n")
    return 0


def _cmd_attach(args: argparse.Namespace) -> int:
    session = claude_sessions.get_session(args.identifier)
    screen_name = claude_sessions.attach_in_screen(session)
    print(f"pi-wave-claude: attached {session.label} in screen session {screen_name!r}")
    print(f"pi-wave-claude: reattach from a terminal with: screen -r {screen_name}")
    return 0


def _cmd_steer(args: argparse.Namespace) -> int:
    text = _read_text(args, "pi-wave-claude steer")
    if text is None:
        return 2
    session = claude_sessions.get_session(args.identifier)
    audit_path = Path(args.jobs_dir) / _safe_record_name(session.name or session.short_id) / "inject.jsonl"
    record = claude_sessions.steer(session, text, enter=not args.no_enter, audit_path=audit_path)
    print(f"pi-wave-claude: typed {len(text)} characters into {session.label} via screen "
          f"{record['screen']!r}{' + Enter' if record['enter'] else ''}")
    print(f"pi-wave-claude: audit written to {audit_path}")
    return 0


def _cmd_wait(args: argparse.Namespace) -> int:
    session = claude_sessions.wait_for(args.identifier, timeout=args.timeout, poll=args.poll)
    print(f"pi-wave-claude: {session.label} finished: {_session_line(session)}")
    return 0


def _cmd_stop(args: argparse.Namespace) -> int:
    claude_sessions.stop(args.identifier)
    print(f"pi-wave-claude: stop requested for {args.identifier!r}")
    return 0


def _cmd_rm(args: argparse.Namespace) -> int:
    claude_sessions.remove(args.identifier)
    print(f"pi-wave-claude: removed {args.identifier!r} from the session list (conversation kept)")
    return 0


# --------------------------------------------------------------------------------------------------
# Argument parsing and top-level error mapping
# --------------------------------------------------------------------------------------------------


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="pi-wave-claude", description=DESCRIPTION, epilog=EPILOG,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True,
                           metavar="{job,start,list,status,logs,attach,steer,wait,stop,rm}")
    raw = argparse.RawDescriptionHelpFormatter

    job = sub.add_parser(
        "job", help="run one clean one-shot Claude job (claude -p) and write result.json", formatter_class=raw,
        description="Run `claude -p --output-format json` on the prompt file, write "
                    "<jobs-dir>/<name>/result.json with text, session_id, model, token usage and "
                    "cost, and exit 0 only if Claude exited 0 and was not killed. For a background "
                    "session that stays alive, use `start`.")
    job.add_argument("name", help="job id -- also the output subdirectory name under --jobs-dir")
    job.add_argument("prompt_file", help="file whose content is the prompt (read once, passed as argv, never copied)")
    job.add_argument("--cwd", required=True, metavar="DIR", help="Claude's working directory")
    job.add_argument("--model", default=None, help="Claude model name, e.g. haiku or sonnet (default: Claude's own)")
    job.add_argument("--session", default="", metavar="ID",
                     help="resume this earlier job's session_id with this prompt (claude -p --resume)")
    job.add_argument("--timeout", type=float, default=None, metavar="SECONDS", help="kill the job after this (default: none)")
    job.add_argument("--jobs-dir", default="pi-wave-jobs", metavar="DIR",
                     help="parent directory for this job's output (default: ./pi-wave-jobs)")
    _add_claude_options(job)
    job.set_defaults(func=_cmd_job)

    start = sub.add_parser(
        "start", help="start a detached background session (claude --bg)", formatter_class=raw,
        description="Run `claude --bg -n <name> [--model M] <prompt>` and record the session under "
                    "<jobs-dir>/<name>/session.json. The session outlives this command. Claude "
                    "requires an accepted workspace trust for --bg; an untrusted directory fails "
                    "with exit 3 and Claude's own message. --bg cannot be combined with -p/--print.")
    start.add_argument("name", help="the session name Claude shows in `claude agents`")
    start_prompt = start.add_mutually_exclusive_group(required=True)
    start_prompt.add_argument("--prompt-file", metavar="F", help="file whose content is the first prompt")
    start_prompt.add_argument("--prompt", metavar="TEXT", help="the first prompt, given directly")
    start.add_argument("--cwd", required=True, metavar="DIR", help="Claude's working directory (must be trusted)")
    start.add_argument("--model", default=None, help="Claude model name, e.g. haiku (default: Claude's own)")
    start.add_argument("--jobs-dir", default="pi-wave-jobs", metavar="DIR",
                       help="parent directory for this session's record (default: ./pi-wave-jobs)")
    _add_claude_options(start)
    start.set_defaults(func=_cmd_start)

    lst = sub.add_parser("list", help="list Claude sessions (active; --all adds completed)")
    lst.add_argument("--all", action="store_true", help="include completed background sessions (claude agents --all)")
    lst.add_argument("--cwd", default=None, metavar="DIR", help="only sessions whose cwd resolves to DIR")
    lst.add_argument("--json", action="store_true", help="print the raw JSON array instead of one line per session")
    lst.set_defaults(func=_cmd_list)

    status = sub.add_parser("status", help="show one session resolved by id, sessionId or exact name")
    status.add_argument("identifier", metavar="id|name")
    status.add_argument("--json", action="store_true", help="print the session as JSON")
    status.set_defaults(func=_cmd_status)

    log = sub.add_parser("logs", help="show a session's recent TUI output (ANSI stripped unless --raw)")
    log.add_argument("identifier", metavar="id|name")
    log.add_argument("--raw", action="store_true", help="keep ANSI escape sequences")
    log.set_defaults(func=_cmd_logs)

    attach = sub.add_parser(
        "attach", help="open a session's TUI in a detached screen (idempotent)", formatter_class=raw,
        description="Start `screen -dmS <name> claude attach <short id>` if it is not already "
                    "running, so the TUI has a real TTY. Re-running it reuses the existing screen. "
                    "Detach with Ctrl-A d; reattach later with `screen -r <screen name>`.")
    attach.add_argument("identifier", metavar="id|name")
    attach.set_defaults(func=_cmd_attach)

    steer = sub.add_parser(
        "steer", help="type into a session's TUI (attach first if needed), then Enter", formatter_class=raw,
        description="Attach the session in screen if needed, send Ctrl-U to clear the prompt line, "
                    "type the text and press Enter. These are KEYSTROKES, not a message: they may "
                    "queue behind Claude's current turn or interrupt it, depending on its state, "
                    "and delivery is not confirmed. The injection is audited to "
                    "<jobs-dir>/<name>/inject.jsonl. For a deterministic follow-up with clean "
                    "output and cost, use `job` with the prior session_id via the Python API.")
    steer.add_argument("identifier", metavar="id|name")
    steer_text = steer.add_mutually_exclusive_group(required=True)
    steer_text.add_argument("text", nargs="?", help="the text to type")
    steer_text.add_argument("--text-file", metavar="F", help="read the text from FILE")
    steer.add_argument("--no-enter", action="store_true", help="type the text without pressing Enter")
    steer.add_argument("--jobs-dir", default="pi-wave-jobs", metavar="DIR",
                       help="audit log under <jobs-dir>/<name>/inject.jsonl (default: ./pi-wave-jobs)")
    steer.set_defaults(func=_cmd_steer)

    wait = sub.add_parser("wait", help="poll until the session reports done/idle (exit 4 on timeout)")
    wait.add_argument("identifier", metavar="id|name")
    wait.add_argument("--timeout", type=float, default=600, metavar="SECONDS", help="deadline (default: 600)")
    wait.add_argument("--poll", type=float, default=2, metavar="SECONDS", help="poll interval (default: 2)")
    wait.set_defaults(func=_cmd_wait)

    stop = sub.add_parser("stop", help="stop a session (exact resolved short id only)")
    stop.add_argument("identifier", metavar="id|name")
    stop.set_defaults(func=_cmd_stop)

    rm = sub.add_parser("rm", help="remove a finished session from the list (conversation kept)")
    rm.add_argument("identifier", metavar="id|name")
    rm.set_defaults(func=_cmd_rm)

    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        return args.func(args)
    except WorkspaceNotTrustedError as exc:
        print(f"pi-wave-claude: {exc}", file=sys.stderr)
        print("pi-wave-claude: open `claude` once in that working directory and accept the workspace trust "
              "prompt, then retry. (`-p`, used by `job`/pi-wave-job, does not need trust.)", file=sys.stderr)
        return 3
    except ClaudeWaitTimeoutError as exc:
        print(f"pi-wave-claude: wait timed out: {exc}", file=sys.stderr)
        return 4
    except ClaudeSessionAmbiguousError as exc:
        print(f"pi-wave-claude: ambiguous session: {exc}", file=sys.stderr)
        return 2
    except (ClaudeSessionNotFoundError, ClaudeUnavailableError, ClaudeUnsupportedError) as exc:
        print(f"pi-wave-claude: {exc}", file=sys.stderr)
        return 1
    except ClaudeError as exc:
        print(f"pi-wave-claude: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"pi-wave-claude: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

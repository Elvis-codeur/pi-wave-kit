"""Console-script CLI for a single ad-hoc `pi` job -- the CLI equivalent of the sibling
`agentic-reasoning-translator` project's ad-hoc `pi_job.sh <name> <model> <workdir> <prompt_file>
[mem]`, built on the tested `run_pi()` path instead of staging the prompt to a file first.

That staging step is exactly what caused `agentic-reasoning-translator` issue #1 / ERRATA #43:
`pi_job.sh` does `cp "$prompt" "$out/prompt.md"` before launching `pi`, and when a caller had
already written the prompt directly at that exact destination path, `cp` failed ("are the same
file") and `set -euo pipefail` killed the whole job silently, before `pi` was ever launched. This
CLI reads the prompt file's content once and passes it straight to `pi` as a real subprocess argv
string -- exactly what `start_pi`/`run_pi` always did (`cmd.append(prompt)`, never a staged file)
-- so that exact bug class is structurally impossible here: there is no file-staging step to fail.

Usage: pi-wave-job <name> <model> <workdir> <prompt_file>
           [--agent pi|opencode|codex|claude] [--session ID]
           [--provider P] [--thinking T] [--mem-max 2500M] [--mem-high H]
           [--cap-usd USD] [--timeout SECONDS] [--jobs-dir DIR]

`--agent` (default pi) runs the job on another coding agent through pi_wave_kit.agents (issue #13);
`model` is then that agent's own model name ("deepseek/deepseek-flash" for opencode, "gpt-5.6-luna"
for codex, "haiku" for claude). `--session` resumes an earlier job's session (its result.json's
session_id) with this prompt instead of starting fresh.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import agents
from .run_pi import CgroupLimits, run_pi

DESCRIPTION = """\
Run ONE ad-hoc coding-agent job (default: pi) to completion and write its result.

The prompt file is read once and passed as a real argv string (never copied/staged), so the
"cp: are the same file" bug class of the old pi_job.sh cannot happen. Output goes to
<jobs-dir>/<name>/: sessions/ (pi's session files), log.txt, result.json. Exit code 0 only if
the job exited 0 and was not killed (timeout or cost cap); 2 for a bad prompt file or options.

Cost: result.json's cost_usd is pi's OWN figure, summed from the job's session file(s). For
DeepSeek pi always prices at the PEAK rate; off-peak is half, so the recorded cost is an upper
bound (conservative for caps). --cap-usd is a LIVE cap: spend is re-read every few seconds and
the job's whole process group is killed once it goes over (result.json: kill_reason =
"cost cap: ..."); it can overshoot by one poll's worth of spend.

Memory: --mem-max runs the job under `systemd-run --user --scope -p MemoryMax=...` so an
out-of-memory kill takes only this job, never your terminal session.

Related commands: pi-wave-run (a capped wave over a directory of prompt files),
pi-wave-session (a long-lived, remotely reachable interactive session)."""

EPILOG = """\
examples:
  pi-wave-job my-job deepseek-flash . prompt.md --cap-usd 0.30 --timeout 1800 --mem-max 2500M
  pi-wave-job fix-1 deepseek-flash ~/repo task.md --provider deepseek --thinking medium
  pi-wave-job fix-1b deepseek-flash ~/repo follow-up.md --session <session_id from result.json>
  pi-wave-job review gpt-5.6-luna ~/repo review.md --agent codex
  pi-wave-job q haiku ~/repo q.md --agent claude

Python equivalents: pi_wave_kit.run_pi.run_pi(..., cap_usd=, cgroup=CgroupLimits(...)) and
pi_wave_kit.agents.run_agent(...). Full documentation: README.md, "Capabilities at a glance"."""


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="pi-wave-job", description=DESCRIPTION, epilog=EPILOG,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("name", help="job id -- also the output subdirectory name under --jobs-dir")
    p.add_argument("model", help="model name: pi --model (e.g. deepseek-flash); for --agent opencode "
                                 "'provider/model', for codex/claude the agent's own model name")
    p.add_argument("workdir", help="the agent's working directory (cwd)")
    p.add_argument("prompt_file", help="file whose content is the prompt (read once, passed as argv, never copied)")
    p.add_argument("--agent", default="pi", choices=agents.AGENTS, help="coding agent to run (default: pi)")
    p.add_argument("--session", default="", metavar="ID",
                   help="continue this earlier session (result.json's session_id) with this prompt instead of starting fresh")
    p.add_argument("--provider", default="deepseek", help="pi provider (default: deepseek)")
    p.add_argument("--thinking", default="low", help="pi thinking level: off, minimal, low, medium, high, xhigh, max (default: low)")
    p.add_argument("--cap-usd", type=float, default=None, metavar="USD",
                   help="live cost cap for this job: kill it once pi's reported spend (peak-priced) exceeds USD. "
                        "Fresh pi jobs only (not --session, not other agents)")
    p.add_argument("--timeout", type=float, default=None, metavar="SECONDS",
                   help="kill the job (whole process group) if it runs longer than this")
    p.add_argument("--mem-max", default=None, metavar="LIMIT",
                   help="memory isolation: run under systemd-run with MemoryMax=LIMIT, e.g. 2500M (default: none)")
    p.add_argument("--mem-high", default=None, metavar="LIMIT",
                   help="systemd-run MemoryHigh, the throttle point (default: 90%% of --mem-max)")
    p.add_argument("--jobs-dir", default="pi-wave-jobs", metavar="DIR",
                   help="parent directory for this job's output (default: ./pi-wave-jobs)")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    prompt_path = Path(args.prompt_file)
    if not prompt_path.is_file():
        print(f"pi-wave-job: no such prompt file: {prompt_path}", file=sys.stderr)
        return 2
    prompt = prompt_path.read_text(encoding="utf-8")
    if not prompt.strip():
        print(f"pi-wave-job: empty prompt file: {prompt_path}", file=sys.stderr)
        return 2

    out = Path(args.jobs_dir) / args.name
    out.mkdir(parents=True, exist_ok=True)
    session_dir = out / "sessions"
    log_path = out / "log.txt"
    result_path = out / "result.json"

    cgroup = CgroupLimits(mem_max=args.mem_max, mem_high=args.mem_high) if args.mem_max else None

    if args.cap_usd is not None and (args.agent != "pi" or args.session):
        print("pi-wave-job: --cap-usd needs a fresh pi job (no --session, --agent pi): other agents report "
              "their cost only when they finish, so it cannot be capped live", file=sys.stderr)
        return 2
    if args.cap_usd is not None and args.cap_usd <= 0:
        print("pi-wave-job: --cap-usd must be greater than 0", file=sys.stderr)
        return 2
    if args.agent != "pi" or args.session:
        return _run_other_agent(args, prompt, out, result_path, cgroup)

    result = run_pi(
        args.name,
        provider=args.provider, model=args.model, thinking=args.thinking,
        prompt=prompt, cwd=args.workdir, session_dir=session_dir, log_path=log_path,
        timeout_seconds=args.timeout, cgroup=cgroup, cap_usd=args.cap_usd,
    )
    killed_for = result.extra.get("kill_reason", "")

    payload = {
        "job_id": result.job_id,
        "returncode": result.returncode,
        "wall_seconds": result.wall_seconds,
        "session_file": str(result.session_file) if result.session_file else None,
        "cost_usd": result.cost_usd,
        "prompt_tokens": result.prompt_tokens,
        "completion_tokens": result.completion_tokens,
        "cache_read_tokens": result.cache_read_tokens,
        "cache_creation_tokens": result.cache_creation_tokens,
        "provider": result.provider,
        "model": result.model,
        "timed_out": result.timed_out,
        "cap_usd": args.cap_usd,
        "kill_reason": killed_for or ("timeout" if result.timed_out else ""),
        "log_path": str(log_path),
        "extra": result.extra,
    }
    result_path.write_text(json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8")

    print(f"pi-wave-job: {args.name} returncode={result.returncode} cost_usd={result.cost_usd:.4f} "
          f"wall_seconds={result.wall_seconds:.1f} timed_out={result.timed_out}"
          + (f" killed: {killed_for}" if killed_for else ""))
    print(f"pi-wave-job: result written to {result_path}")
    return 0 if (result.returncode == 0 and not result.timed_out) else 1


def _run_other_agent(args: argparse.Namespace, prompt: str, out: Path, result_path: Path,
                     cgroup: CgroupLimits | None) -> int:
    model = args.model if args.agent != "pi" or "/" in args.model else f"{args.provider}/{args.model}"
    result = agents.run_agent(
        args.agent, args.name, prompt=prompt, model=model, cwd=args.workdir, out_dir=out,
        session_id=args.session, timeout_seconds=args.timeout, thinking=args.thinking, cgroup=cgroup,
    )
    payload = {
        "job_id": result.job_id, "agent": result.agent, "returncode": result.returncode,
        "wall_seconds": result.wall_seconds, "session_id": result.session_id, "text": result.text,
        "error": result.error, "cost_usd": result.reported_cost_usd, "billing": result.billing,
        "prompt_tokens": result.prompt_tokens, "completion_tokens": result.completion_tokens,
        "cache_read_tokens": result.cache_read_tokens, "cache_creation_tokens": result.cache_creation_tokens,
        "provider": result.provider, "model": result.model, "timed_out": result.timed_out,
        "output_path": str(result.output_path) if result.output_path else None, "extra": result.extra,
    }
    result_path.write_text(json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"pi-wave-job: {args.name} agent={result.agent} returncode={result.returncode} "
          f"cost_usd={result.reported_cost_usd:.4f} wall_seconds={result.wall_seconds:.1f} "
          f"timed_out={result.timed_out}{' error=' + result.error[:200] if result.error else ''}")
    print(f"pi-wave-job: result written to {result_path}")
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())

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
           [--provider P] [--thinking T] [--mem-max 2500M] [--mem-high H]
           [--timeout SECONDS] [--jobs-dir DIR]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .run_pi import CgroupLimits, run_pi


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="pi-wave-job",
        description="Run one ad-hoc pi job through pi_wave_kit.run_pi.run_pi(), optionally under "
                    "a systemd-run memory cap. Equivalent to the sibling project's pi_job.sh, "
                    "without its prompt-file-staging bug class.",
    )
    p.add_argument("name", help="job id -- also the output subdirectory name under --jobs-dir")
    p.add_argument("model", help="model name passed to pi --model")
    p.add_argument("workdir", help="pi's working directory (cwd)")
    p.add_argument("prompt_file", help="path to a file whose content is the prompt -- read once "
                                        "and passed as a real argv string, never staged/copied")
    p.add_argument("--provider", default="deepseek", help="default: deepseek")
    p.add_argument("--thinking", default="low", help="default: low")
    p.add_argument("--mem-max", default=None, metavar="LIMIT",
                    help="systemd-run MemoryMax, e.g. 2500M -- omit for no memory isolation")
    p.add_argument("--mem-high", default=None, metavar="LIMIT",
                    help="systemd-run MemoryHigh (default: 90%% of --mem-max)")
    p.add_argument("--timeout", type=float, default=None, metavar="SECONDS",
                    help="kill the job if it runs longer than this")
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

    result = run_pi(
        args.name,
        provider=args.provider, model=args.model, thinking=args.thinking,
        prompt=prompt, cwd=args.workdir, session_dir=session_dir, log_path=log_path,
        timeout_seconds=args.timeout, cgroup=cgroup,
    )

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
        "log_path": str(log_path),
        "extra": result.extra,
    }
    result_path.write_text(json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8")

    print(f"pi-wave-job: {args.name} returncode={result.returncode} cost_usd={result.cost_usd:.4f} "
          f"wall_seconds={result.wall_seconds:.1f} timed_out={result.timed_out}")
    print(f"pi-wave-job: result written to {result_path}")
    return 0 if (result.returncode == 0 and not result.timed_out) else 1


if __name__ == "__main__":
    sys.exit(main())

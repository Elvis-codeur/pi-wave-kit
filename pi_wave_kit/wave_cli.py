"""Console-script CLI (`pi-wave-run`): run a capped wave of headless `pi` jobs over a directory of prompt
files (or a job list) without writing any Python -- `run_wave` + `start_pi` + the live per-job cost cap,
wired the way production wave scripts wire them (language-correction-works/hardloop/wave.py was the
reference; issue #20).

A DRY RUN unless `--yes-spend` is given: it prints the plan, the projected cost and the worst case and
launches nothing (the owner's cost-consent rule: every paid wave needs an explicit yes for its projection).

Per job `<out-dir>/<job_id>/`: sessions/, log.txt, job.json (prompt file + sha256, model, cap, result).
Wave: `<out-dir>/wave-summary.json` (run_wave's resumable summary: re-running the same command skips jobs
that already succeeded and counts all earlier spend against the cap) and `<out-dir>/wave-result.json`.
`touch <out-dir>/STOP` stops new launches; running jobs finish.

`--budget-file F` keeps a cumulative ledger across waves: `{"total_usd": 10.0, "rounds": [{"spent_usd": ...}]}`.
The wave cap is clipped to what is left (minus `--budget-margin`), and a real run appends its spend as a round.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from .run_pi import CgroupLimits, collect_pi_result, kill_if_timed_out, start_pi, start_pi_resume
from .run_pi import PiResumeHandle as _PiResumeHandle
from .run_pi import collect_pi_resume_result as _collect_resume
from .wave import WaveJob, WaveJobResult, load_summary, run_wave

RESUME_PROMPT = ("You were stopped by a timeout before finishing. Continue the same task exactly where you "
                 "stopped; do not redo work that is already done.")

DESCRIPTION = """\
Run a WAVE of headless pi jobs, one per prompt file, N at a time, under a total dollar cap.

Dry run by default: prints the plan, projected cost and worst case, launches nothing.
Add --yes-spend to launch (paid model calls).

Budget control, three layers:
  wave cap     a job launches only if  spent so far + caps of running jobs + its cap <= --wave-cap-usd
               (so the wave cannot overshoot through launches)
  live job cap each running job's spend is re-read every --cost-poll-seconds; it is killed above its
               cap (on by default; --no-live-cap turns it off). A job can overshoot by one poll.
  budget file  optional cumulative ledger across waves (--budget-file): the wave cap is clipped to what
               is left, and the spend is appended as a round when the wave ends.

Cost figures are pi's own (session files). For DeepSeek pi always uses the PEAK price; off-peak is
half, so recorded spend is an upper bound.

Resumable: the summary JSON is the source of truth. Re-running the same command skips jobs that
already succeeded; their spend (and failed jobs' spend) still counts against the wave cap.
Stop file: `touch <out-dir>/STOP` (or --stop-file) stops new launches; running jobs finish."""

EPILOG = """\
job list format (--job-list): one job per line, '#' comments allowed, paths relative to the list file:
  prompts/a.md                 job id = file stem
  job-7  prompts/b.md          explicit job id
  job-8  prompts/c.md  0.50    explicit per-job cap in USD

examples:
  pi-wave-run --prompts-dir prompts --wave-cap-usd 2 --job-cap-usd 0.30           # dry run
  pi-wave-run --prompts-dir prompts --wave-cap-usd 2 --job-cap-usd 0.30 --yes-spend \\
      --concurrency 4 --timeout 1800 --mem-max 1500M --out-dir work/round-3
  pi-wave-run --job-list jobs.txt --wave-cap-usd 5 --job-cap-usd 0.5 --budget-file budget.json \\
      --per-job-workdir --require-output out.jsonl --max-resumes 1 --yes-spend

Python equivalent: pi_wave_kit.wave.run_wave(..., live_cost_cap=True). Single job: pi-wave-job.
Full documentation: README.md, "Capabilities at a glance"."""


@dataclass
class PlannedJob:
    job_id: str
    prompt_file: Path
    cap_usd: float


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="pi-wave-run", description=DESCRIPTION, epilog=EPILOG,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--prompts-dir", metavar="DIR", help="one job per *.md file in DIR (job id = file stem)")
    src.add_argument("--job-list", metavar="FILE", help="one job per line: [job_id] prompt_file [cap_usd]")
    p.add_argument("--wave-cap-usd", type=float, required=True, metavar="USD", help="total cap for the whole wave")
    p.add_argument("--job-cap-usd", type=float, required=True, metavar="USD",
                   help="per-job cap: reserved at launch, and enforced live unless --no-live-cap")
    p.add_argument("--projected-usd", type=float, default=None, metavar="USD",
                   help="expected cost per job, for the dry-run projection (default: half the job cap -- an assumption)")
    p.add_argument("--concurrency", type=int, default=4, help="max jobs running at once (default: 4)")
    p.add_argument("--timeout", type=float, default=1800, metavar="SECONDS", help="per-job wall timeout (default: 1800)")
    p.add_argument("--max-resumes", type=int, default=0, metavar="N",
                   help="on timeout, continue the job in its own pi session up to N times (default: 0, a timeout fails)")
    p.add_argument("--provider", default="deepseek", help="pi --provider (default: deepseek)")
    p.add_argument("--model", default="deepseek-flash", help="pi --model (default: deepseek-flash)")
    p.add_argument("--thinking", default="low", help="pi --thinking (default: low)")
    p.add_argument("--extra-arg", action="append", default=[], metavar="ARG",
                   help="extra argument passed to pi, repeatable (e.g. --extra-arg=--no-skills)")
    p.add_argument("--workdir", default=".", metavar="DIR", help="cwd of every job (default: current directory)")
    p.add_argument("--per-job-workdir", action="store_true",
                   help="run each job in its own <out-dir>/<job_id>/work/ instead of --workdir")
    p.add_argument("--require-output", default=None, metavar="RELPATH",
                   help="a job only succeeds if this file exists and is non-empty in its workdir")
    p.add_argument("--out-dir", default="pi-wave-out", metavar="DIR", help="wave output directory (default: ./pi-wave-out)")
    p.add_argument("--stop-file", default=None, metavar="PATH", help="stop file (default: <out-dir>/STOP)")
    p.add_argument("--budget-file", default=None, metavar="FILE",
                   help='cumulative budget JSON {"total_usd": X, "rounds": [{"spent_usd": Y}, ...]}: clips the wave cap')
    p.add_argument("--budget-margin", type=float, default=0.05, metavar="USD",
                   help="kept unspent from the budget file's remainder (default: 0.05)")
    p.add_argument("--round-name", default=None, help="name of this wave in the budget file (default: the out-dir name)")
    p.add_argument("--mem-max", default=None, metavar="LIMIT", help="per-job systemd-run MemoryMax, e.g. 1500M (default: none)")
    p.add_argument("--mem-high", default=None, metavar="LIMIT", help="per-job systemd-run MemoryHigh (default: 90%% of --mem-max)")
    p.add_argument("--no-live-cap", action="store_true", help="do not kill a running job above its cap (launch gate only)")
    p.add_argument("--cost-poll-seconds", type=float, default=10.0, metavar="S",
                   help="how often a running job's spend is re-read (default: 10)")
    p.add_argument("--poll-seconds", type=float, default=2.0, metavar="S", help=argparse.SUPPRESS)
    p.add_argument("--yes-spend", action="store_true", help="really launch (paid). Without it: dry run only")
    return p.parse_args(argv)


def load_jobs(args: argparse.Namespace) -> list[PlannedJob]:
    """The jobs to run, in a stable order. Raises ValueError on a bad list, a missing prompt or a duplicate id."""
    jobs: list[PlannedJob] = []
    if args.prompts_dir:
        d = Path(args.prompts_dir)
        if not d.is_dir():
            raise ValueError(f"no such prompts directory: {d}")
        jobs = [PlannedJob(f.stem, f, args.job_cap_usd) for f in sorted(d.glob("*.md"))]
    else:
        lst = Path(args.job_list)
        if not lst.is_file():
            raise ValueError(f"no such job list: {lst}")
        for n, line in enumerate(lst.read_text(encoding="utf-8").splitlines(), 1):
            parts = line.split("#", 1)[0].split()
            if not parts:
                continue
            if len(parts) > 3:
                raise ValueError(f"{lst}:{n}: expected '[job_id] prompt_file [cap_usd]', got {line!r}")
            if len(parts) == 1:
                job_id, path, cap = Path(parts[0]).stem, parts[0], args.job_cap_usd
            else:
                job_id, path = parts[0], parts[1]
                try:
                    cap = float(parts[2]) if len(parts) == 3 else args.job_cap_usd
                except ValueError:
                    raise ValueError(f"{lst}:{n}: cap_usd is not a number: {parts[2]!r}") from None
            f = Path(path) if Path(path).is_absolute() else lst.parent / path
            jobs.append(PlannedJob(job_id, f, cap))
    seen: set[str] = set()
    for j in jobs:
        if j.job_id in seen:
            raise ValueError(f"duplicate job id {j.job_id!r}")
        seen.add(j.job_id)
        if not j.prompt_file.is_file():
            raise ValueError(f"job {j.job_id}: no such prompt file: {j.prompt_file}")
        if not j.prompt_file.read_text(encoding="utf-8").strip():
            raise ValueError(f"job {j.job_id}: empty prompt file: {j.prompt_file}")
        if j.cap_usd <= 0:
            raise ValueError(f"job {j.job_id}: cap must be > 0")
    return jobs


def budget_left(budget_file: Path) -> float:
    data = json.loads(budget_file.read_text(encoding="utf-8"))
    return float(data["total_usd"]) - sum(float(r.get("spent_usd", 0)) for r in data.get("rounds", []))


def plan(args: argparse.Namespace, jobs: list[PlannedJob], out: Path) -> dict:
    """Everything the dry run prints, computed without launching anything."""
    raw = load_summary(out / "wave-summary.json")
    done = {k for k, v in raw.get("jobs", {}).items() if v.get("status") == "success"}
    prior = sum(v.get("cost_usd", 0.0) for v in raw.get("jobs", {}).values())
    todo = [j for j in jobs if j.job_id not in done]
    projected_each = args.projected_usd if args.projected_usd is not None else None
    projected = sum(projected_each if projected_each is not None else j.cap_usd / 2 for j in todo)
    wave_cap = args.wave_cap_usd
    left = None
    if args.budget_file:
        left = budget_left(Path(args.budget_file))
        # earlier invocations of THIS wave are already in both the summary and the budget file's rounds
        wave_cap = min(wave_cap, prior + left - args.budget_margin)
    room = wave_cap - prior
    worst = min(sum(j.cap_usd for j in todo), max(room, 0.0))
    max_cap = max((j.cap_usd for j in todo), default=0.0)
    eff_conc = min(args.concurrency, int(room // max_cap)) if max_cap else 0
    return {"jobs": len(jobs), "already_succeeded": sorted(done), "to_run": [j.job_id for j in todo],
            "prior_spend_usd": prior, "wave_cap_usd": wave_cap, "budget_left_usd": left,
            "projected_usd": projected, "projected_is_assumption": args.projected_usd is None,
            "worst_case_usd": worst, "effective_concurrency": max(eff_conc, 0),
            "fits_one_job": bool(todo) and prior + min(j.cap_usd for j in todo) <= wave_cap}


def print_plan(args: argparse.Namespace, jobs: list[PlannedJob], p: dict, out: Path) -> None:
    print(f"pi-wave-run: {p['jobs']} jobs, {len(p['to_run'])} to run, {len(p['already_succeeded'])} already succeeded")
    print(f"  model: {args.provider}/{args.model} thinking={args.thinking}  concurrency={args.concurrency} "
          f"timeout={args.timeout:.0f}s  max_resumes={args.max_resumes}  live cap={'off' if args.no_live_cap else 'on'}")
    caps = sorted({j.cap_usd for j in jobs if j.job_id in p["to_run"]})
    print(f"  job cap: {', '.join(f'${c:.2f}' for c in caps) or '-'}   wave cap: ${p['wave_cap_usd']:.2f}"
          + (f" (clipped by budget file: ${p['budget_left_usd']:.2f} left, margin ${args.budget_margin:.2f})"
             if p["budget_left_usd"] is not None else ""))
    if p["prior_spend_usd"]:
        print(f"  already spent by earlier runs of this wave: ${p['prior_spend_usd']:.4f} (counts against the wave cap)")
    print(f"  projected: ${p['projected_usd']:.2f}" + (" (ASSUMPTION: half of each job cap; pass --projected-usd)"
                                                       if p["projected_is_assumption"] else ""))
    print(f"  worst case: ${p['worst_case_usd']:.2f} (sum of job caps, bounded by what the wave cap leaves; "
          "plus at most one cost poll of overshoot per job)")
    if p["effective_concurrency"] < args.concurrency:
        print(f"  note: the wave cap allows only {p['effective_concurrency']} job(s) at once")
    print("  costs are pi's own figures: DeepSeek PEAK price at all hours (off-peak is half)")
    print(f"  output: {out}/  stop file: {args.stop_file or out / 'STOP'}")
    for j in jobs:
        if j.job_id in p["to_run"]:
            print(f"    {j.job_id}: {j.prompt_file} (cap ${j.cap_usd:.2f})")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.wave_cap_usd <= 0 or args.job_cap_usd <= 0 or args.concurrency < 1:
        print("pi-wave-run: --wave-cap-usd and --job-cap-usd must be > 0 and --concurrency >= 1", file=sys.stderr)
        return 2
    try:
        jobs = load_jobs(args)
        if args.budget_file and not Path(args.budget_file).is_file():
            raise ValueError(f"no such budget file: {args.budget_file} (create it with a total_usd first)")
    except ValueError as exc:
        print(f"pi-wave-run: {exc}", file=sys.stderr)
        return 2
    if not jobs:
        print("pi-wave-run: no jobs found", file=sys.stderr)
        return 2

    out = Path(args.out_dir)
    p = plan(args, jobs, out)
    print_plan(args, jobs, p, out)
    if not p["to_run"]:
        print("pi-wave-run: nothing to run (every job already succeeded)")
        return 0
    if not p["fits_one_job"]:
        print("pi-wave-run: refused: the wave cap leaves no room for even one job's cap", file=sys.stderr)
        return 1
    if not args.yes_spend:
        print("pi-wave-run: DRY RUN, nothing launched. Re-run with --yes-spend to launch (paid).")
        return 0
    return _run(args, jobs, p, out)


def _run(args: argparse.Namespace, jobs: list[PlannedJob], p: dict, out: Path) -> int:
    by_id = {j.job_id: j for j in jobs}
    cgroup = CgroupLimits(mem_max=args.mem_max, mem_high=args.mem_high) if args.mem_max else None
    common = dict(provider=args.provider, model=args.model, thinking=args.thinking, extra_args=args.extra_arg or None,
                  timeout_seconds=args.timeout, cgroup=cgroup)

    def job_dir(job_id: str) -> Path:
        return out / job_id

    def workdir(job_id: str) -> Path:
        return job_dir(job_id) / "work" if args.per_job_workdir else Path(args.workdir)

    def launch(job: WaveJob):
        pj = by_id[job.job_id]
        d = job_dir(job.job_id)
        d.mkdir(parents=True, exist_ok=True)
        workdir(job.job_id).mkdir(parents=True, exist_ok=True)
        (d / "job.json").write_text(json.dumps({
            "job_id": job.job_id, "prompt_file": str(pj.prompt_file), "prompt_sha256": _sha256(pj.prompt_file),
            "provider": args.provider, "model": args.model, "thinking": args.thinking, "cap_usd": job.cap_usd,
            "timeout_seconds": args.timeout, "workdir": str(workdir(job.job_id)), "started_utc": _now(),
        }, indent=1), encoding="utf-8")
        return start_pi(job.job_id, prompt=pj.prompt_file.read_text(encoding="utf-8"), cwd=workdir(job.job_id),
                        session_dir=d / "sessions", log_path=d / "log.txt", **common)

    def resume(job: WaveJob, handle, result: WaveJobResult):
        session = result.extra.get("session_file")
        if not session:
            raise RuntimeError("no session file to resume")
        n = result.extra.get("attempt", 0) + 1
        return start_pi_resume(job.job_id, session=session, prompt=RESUME_PROMPT, cwd=workdir(job.job_id),
                               log_path=job_dir(job.job_id) / f"log.resume{n}.txt", **common)

    def collect(handle, timed_out: bool) -> WaveJobResult:
        if isinstance(handle, _PiResumeHandle):
            r = _collect_resume(handle, timed_out=timed_out)
        else:
            r = collect_pi_result(handle, timed_out=timed_out)
        reason = ""
        ok = r.returncode == 0 and not timed_out
        if timed_out:
            reason = r.extra.get("kill_reason") or "timed out"
        elif r.returncode != 0:
            reason = f"pi exited {r.returncode}"
        elif args.require_output:
            target = workdir(handle.job_id) / args.require_output
            if not (target.is_file() and target.stat().st_size > 0):
                ok, reason = False, f"required output missing or empty: {target}"
        jf = job_dir(handle.job_id) / "job.json"
        info = json.loads(jf.read_text(encoding="utf-8")) if jf.is_file() else {}
        attempts = info.setdefault("attempts", [])
        attempts.append({"finished_utc": _now(), "returncode": r.returncode, "timed_out": timed_out,
                         "kill_reason": r.extra.get("kill_reason", ""), "cost_usd_peak_rate": round(r.cost_usd, 6),
                         "wall_seconds": round(r.wall_seconds, 1), "prompt_tokens": r.prompt_tokens,
                         "completion_tokens": r.completion_tokens, "cache_read_tokens": r.cache_read_tokens,
                         "session_file": str(r.session_file) if r.session_file else None})
        info.update({"status": "success" if ok else "failed", "reason": reason})
        jf.write_text(json.dumps(info, indent=1), encoding="utf-8")
        session = r.session_file or getattr(handle, "session_path", None)
        return WaveJobResult(handle.job_id, "success" if ok else "failed", cost_usd=r.cost_usd, reason=reason,
                             wall_seconds=r.wall_seconds,
                             extra={"session_file": str(session) if session else "", "attempt": len(attempts)})

    stop_file = Path(args.stop_file) if args.stop_file else out / "STOP"
    out.mkdir(parents=True, exist_ok=True)
    summary = run_wave(
        [WaveJob(j.job_id, cap_usd=j.cap_usd, projected_usd=j.cap_usd / 2) for j in jobs],
        launch_fn=launch, collect_fn=collect, is_timed_out=kill_if_timed_out, concurrency=args.concurrency,
        wave_cap_usd=p["wave_cap_usd"], summary_path=out / "wave-summary.json", stop_file=stop_file,
        poll_seconds=args.poll_seconds, on_event=lambda m: print(time.strftime("%H:%M:%S"), m, flush=True),
        resume_fn=resume if args.max_resumes > 0 else None, max_resumes=args.max_resumes,
        live_cost_cap=not args.no_live_cap, cost_poll_seconds=args.cost_poll_seconds,
    )
    spent_now = summary.committed_usd - p["prior_spend_usd"]
    result = {"finished_utc": _now(), "committed_usd": summary.committed_usd, "spent_this_run_usd": spent_now,
              "wave_cap_usd": p["wave_cap_usd"], "stop_reason": summary.stop_reason,
              "not_successful": summary.not_successful(), "not_launched": summary.not_launched,
              "jobs": {k: {"status": v.status, "cost_usd": v.cost_usd, "reason": v.reason}
                       for k, v in summary.finished.items()}}
    (out / "wave-result.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    if args.budget_file:
        bf = Path(args.budget_file)
        budget = json.loads(bf.read_text(encoding="utf-8"))
        budget.setdefault("rounds", []).append({"round": args.round_name or out.name, "spent_usd": round(spent_now, 6),
                                                "jobs": len(summary.launched), "finished_utc": _now()})
        bf.write_text(json.dumps(budget, indent=1), encoding="utf-8")
    print(f"pi-wave-run: committed ${summary.committed_usd:.4f} (this run ${spent_now:.4f}); "
          f"not successful: {summary.not_successful() or 'none'}; not launched: {summary.not_launched or 'none'}"
          + (f"; stopped: {summary.stop_reason}" if summary.stop_reason else ""))
    print(f"pi-wave-run: summary written to {out / 'wave-result.json'}")
    return 0 if not summary.not_successful() and not summary.not_launched else 1


if __name__ == "__main__":
    sys.exit(main())

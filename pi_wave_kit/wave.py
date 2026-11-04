"""The actual hard-won part of this library: a budget-AWARE rolling pool, not just a concurrency
semaphore. A job only launches if `committed + (sum of caps of jobs already running) + its own cap` is
still under the wave's cumulative budget -- so the wave can never overshoot, even though each job's real
cost isn't known until it finishes. Extracted from scripts/pi/run_wave.py (agentic-doc-treatement,
months of real DeepSeek-wave production use) and generalized: this module has no idea what a "document"
or a "cue" is -- `launch_fn`/`collect_fn` are the caller's own hooks (typically
pi_wave_kit.run_pi.start_pi/collect_pi_result, but a fake for testing, or something that isn't even
`pi`, works too).

Resumable: the summary JSON is the source of truth for what's already been launched/finished -- re-run
the same job list and already-finished jobs are skipped (same job_id). A stop file (its mere existence,
not its content) halts new launches without killing what's already running."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol


class _Handle(Protocol):
    job_id: str
    proc: Any  # has .poll() -> int | None


@dataclass
class WaveJob:
    job_id: str
    cap_usd: float
    projected_usd: float = 0.0
    extra: dict = field(default_factory=dict)


@dataclass
class WaveJobResult:
    job_id: str
    status: str  # "success" | "failed" | "not_launched"
    cost_usd: float = 0.0
    reason: str = ""
    wall_seconds: float = 0.0
    extra: dict = field(default_factory=dict)


@dataclass
class WaveSummary:
    launched: list[str] = field(default_factory=list)
    finished: dict[str, WaveJobResult] = field(default_factory=dict)
    not_launched: list[str] = field(default_factory=list)
    stop_reason: str = ""
    committed_usd: float = 0.0

    def not_successful(self) -> list[str]:
        return [j for j, r in self.finished.items() if r.status != "success"]


def load_summary(path: Path) -> dict:
    if not Path(path).is_file():
        return {"jobs": {}}
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_summary(path: Path, raw: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(raw, indent=1, ensure_ascii=False), encoding="utf-8")


def _cost_kill_reason(handle) -> str:
    """The reason a `run_pi.cost_capped` hook recorded when it killed this job for its spend ("" if none)."""
    reason = getattr(handle, "kill_reason", "") or getattr(getattr(handle, "pi_handle", None), "kill_reason", "")
    return reason if isinstance(reason, str) else ""


def run_wave(
    jobs: list[WaveJob],
    *,
    launch_fn: Callable[[WaveJob], _Handle],
    collect_fn: Callable[[_Handle, bool], WaveJobResult],  # (handle, timed_out) -> WaveJobResult
    is_timed_out: Callable[[_Handle], bool],
    concurrency: int,
    wave_cap_usd: float,
    summary_path: str | Path,
    stop_file: str | Path | None = None,
    poll_seconds: float = 2.0,
    on_event: Callable[[str], None] | None = None,
    resume_fn: Callable[[WaveJob, _Handle, WaveJobResult], _Handle] | None = None,
    max_resumes: int = 0,
    live_cost_cap: bool = False,
    cost_poll_seconds: float = 10.0,
) -> WaveSummary:
    """Blocking: runs until every job has launched-and-finished, been skipped as already-done, or the
    wave stopped launching new ones (wave cap reached, or the stop file appeared). Jobs already present
    in the summary file with status "success" are skipped entirely (resumable re-run).

    `resume_fn(job, handle, result)` + `max_resumes` (both optional; default off, so existing callers are unchanged): when a
    job hits its timeout while resumes remain, its spend so far is committed against the wave cap, `resume_fn` returns a NEW
    handle (typically `start_pi(..., extra_args=["--session", <the old session file>])` with a "continue where you stopped"
    prompt) and the job keeps running. After `max_resumes` resumes a further timeout is a failure, as before.

    `live_cost_cap=True` (optional; default off) also enforces each job's OWN `cap_usd` while it runs: its live
    session spend is re-read every `cost_poll_seconds` and the job's process group is killed once it exceeds the
    cap (what is left of it, for a resumed job). The launch gate above only RESERVES a running job's cap; without
    this, a runaway worker's spend is seen only when it ends. Needs pi handles (`start_pi`/`start_pi_resume`, or
    `agents.start_agent("pi", ...)`): see `pi_wave_kit.run_pi.cost_capped`, which you can also wrap around your
    own `is_timed_out` instead. A job killed for its cost is recorded `failed` with reason "cost cap: spent $x >
    cap $y" and is never resumed."""
    log = on_event or (lambda _msg: None)
    raw = load_summary(summary_path)
    raw.setdefault("jobs", {})
    # ALL recorded spend counts against the cap, whatever the job's status -- a failed job's money is still
    # gone (real gap found in review 2026-10-16: counting only "success" let repeated relaunches exceed the cap).
    committed = sum(r.get("cost_usd", 0.0) for r in raw["jobs"].values())

    queue = [j for j in jobs if raw["jobs"].get(j.job_id, {}).get("status") != "success"]
    skipped = [j.job_id for j in jobs if j not in queue]
    for job_id in skipped:
        log(f"skip {job_id}: already succeeded in a previous run of this wave")

    running: dict[str, tuple[_Handle, WaveJob]] = {}
    resumes: dict[str, int] = {}
    spent_before: dict[str, float] = {}  # spend already committed for a job that was resumed in this run
    stop_reason = ""
    summary = WaveSummary(committed_usd=committed)

    check_timed_out = is_timed_out
    if live_cost_cap:
        from .run_pi import cost_capped  # lazy: wave.py itself stays free of run_pi's dependencies

        def _remaining_cap(handle: _Handle) -> float | None:
            entry = running.get(handle.job_id)
            return None if entry is None else entry[1].cap_usd - spent_before.get(handle.job_id, 0.0)

        check_timed_out = cost_capped(is_timed_out, cap_for=_remaining_cap, min_interval_seconds=cost_poll_seconds)

    def _stopped() -> bool:
        return bool(stop_file) and Path(stop_file).is_file()

    while queue or running:
        for job_id, (handle, job) in list(running.items()):
            if check_timed_out(handle):
                result = collect_fn(handle, True)
                cost_kill = _cost_kill_reason(handle)
                if cost_kill:
                    # A cost-cap kill is final: resuming would only spend past the cap again.
                    result.status = "failed"
                    result.reason = cost_kill if not result.reason or result.reason == cost_kill else f"{cost_kill}; {result.reason}"
                    result.extra = {**(result.extra or {}), "kill_reason": cost_kill}
                    # Never count less than the live spend that triggered the kill (a collect_fn may read less).
                    from .run_pi import session_cost_usd
                    result.cost_usd = max(result.cost_usd, session_cost_usd(handle))
                elif resume_fn is not None and resumes.get(job_id, 0) < max_resumes:
                    # The spend so far is real money: commit it now, then keep the job running in its own session.
                    resumes[job_id] = resumes.get(job_id, 0) + 1
                    committed += result.cost_usd
                    spent_before[job_id] = spent_before.get(job_id, 0.0) + result.cost_usd
                    prior = raw["jobs"].get(job_id, {}).get("cost_usd", 0.0)
                    raw["jobs"][job_id] = {"status": "running", "cost_usd": prior + result.cost_usd,
                                           "reason": f"timed out; resumed {resumes[job_id]}/{max_resumes}"}
                    write_summary(summary_path, raw)
                    try:
                        running[job_id] = (resume_fn(job, handle, result), job)
                        log(f"resumed {job_id} after timeout ({resumes[job_id]}/{max_resumes}), committed ${committed:.4f}")
                        continue
                    except Exception as exc:
                        result = WaveJobResult(job_id=job_id, status="failed", cost_usd=0.0, reason=f"resume failed: {exc}")
            elif handle.proc.poll() is None:
                continue
            else:
                result = collect_fn(handle, False)
            committed += result.cost_usd
            summary.finished[job_id] = result
            summary.launched.append(job_id)
            # ACCUMULATE across attempts: a retried job's earlier spend is still real money (review 2026-10-16).
            prior = raw["jobs"].get(job_id, {}).get("cost_usd", 0.0)
            raw["jobs"][job_id] = {"status": result.status, "cost_usd": prior + result.cost_usd,
                                   "reason": result.reason}
            write_summary(summary_path, raw)
            del running[job_id]
            log(f"done {job_id}: {result.status}, ${result.cost_usd:.4f}, committed ${committed:.4f}")

        while queue and not stop_reason and len(running) < concurrency:
            if _stopped():
                stop_reason = f"stop file {stop_file} exists"
                break
            job = queue[0]
            reserved = sum(j.cap_usd for _, j in running.values())
            if committed + reserved + job.cap_usd > wave_cap_usd:
                if not running:
                    stop_reason = f"wave cap: committed ${committed:.4f} + next job's cap ${job.cap_usd:.2f} > ${wave_cap_usd:.2f}"
                break  # wait for a running job to finish and release its reservation
            queue.pop(0)
            try:
                handle = launch_fn(job)
            except Exception as exc:
                summary.finished[job.job_id] = WaveJobResult(job_id=job.job_id, status="failed", reason=f"did not start: {exc}")
                raw["jobs"][job.job_id] = {"status": "failed", "cost_usd": 0.0, "reason": str(exc)}
                write_summary(summary_path, raw)
                continue
            running[job.job_id] = (handle, job)
            log(f"launched {job.job_id} (cap ${job.cap_usd:.2f}, {len(running)} running, committed ${committed:.4f})")

        if stop_reason and not running:
            break
        if running:
            time.sleep(poll_seconds)

    for job in queue:
        summary.not_launched.append(job.job_id)
        raw["jobs"].setdefault(job.job_id, {})["status"] = "not_launched"
    summary.stop_reason = stop_reason
    summary.committed_usd = committed
    write_summary(summary_path, raw)
    return summary

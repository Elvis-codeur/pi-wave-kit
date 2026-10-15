"""Spawns `pi` processes (workers or a coordinator) and reports what they actually did: exit status,
wall time, and real token usage read from each one's own session file (via
llm_ledger_client.session_ingest's Pi adapter). `PiResult.cost_usd` is Pi's OWN reported figure --
evidence only, per this family of libraries' own rule (never trust a provider's self-reported cost as
the real one; a ledger service computes it from its own ModelPricing table). Pass `PiResult`'s
`prompt_tokens`/`completion_tokens`/etc. to `llm_ledger_client.LedgerClient.log_call()`, NOT `cost_usd`
-- a real gap found by actually logging a real run's cost into a live ledger service during
development: only the reported cost was being surfaced, which the ledger correctly never looks at, so
every real call was logged at a silent, wrong $0.00 until this was fixed.

Two layers: `start_pi()`/`collect_pi_result()` are non-blocking primitives (wave.py's scheduler polls
many processes at once, so it can never block on one). `run_pi()` is the blocking convenience wrapper
for running just one (a single ad-hoc task, or a test)."""

from __future__ import annotations

import subprocess
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from llm_ledger_client.session_ingest import read_usage


@dataclass
class PiHandle:
    """A running (or just-started) `pi` process -- opaque to the caller beyond what collect_pi_result()
    needs."""

    job_id: str
    proc: subprocess.Popen
    session_dir: Path
    session_files_before: set
    log_file: object  # the open file handle, closed by collect_pi_result()
    started_monotonic: float
    timeout_seconds: float | None


@dataclass
class PiResult:
    job_id: str
    returncode: int | None  # None if the process was killed for exceeding timeout_seconds
    wall_seconds: float
    session_file: Path | None
    cost_usd: float  # Pi's OWN reported cost -- evidence only, never the real recorded cost (see module docstring)
    prompt_tokens: int = 0  # real token counts, for a caller to get the ledger to compute REAL cost from ModelPricing
    completion_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    provider: str = ""
    model: str = ""
    timed_out: bool = False
    log_path: Path | None = None
    extra: dict = field(default_factory=dict)


def _build_command(provider: str, model: str, thinking: str, session_dir: Path, prompt: str | None, extra_args: list[str] | None) -> list[str]:
    cmd = ["pi", "--provider", provider, "--model", model, "--thinking", thinking, "--print",
           "--session-dir", str(session_dir), *(extra_args or [])]
    if prompt is not None:
        cmd.append(prompt)
    return cmd


def start_pi(
    job_id: str,
    *,
    provider: str,
    model: str,
    thinking: str,
    prompt: str | None = None,
    cwd: str | Path,
    session_dir: str | Path,
    extra_args: list[str] | None = None,
    timeout_seconds: float | None = None,
    log_path: str | Path | None = None,
) -> PiHandle:
    """Non-blocking: starts the process and returns a handle immediately. Caller is responsible for
    polling `handle.proc.poll()` and calling collect_pi_result() once it's not None, or killing it
    itself once `timeout_seconds` has elapsed (wave.py's scheduler does both)."""
    session_dir = Path(session_dir)
    session_dir.mkdir(parents=True, exist_ok=True)
    before = set(session_dir.glob("*.jsonl"))
    cmd = _build_command(provider, model, thinking, session_dir, prompt, extra_args)
    log_f = open(log_path, "w", encoding="utf-8") if log_path else subprocess.DEVNULL
    proc = subprocess.Popen(cmd, cwd=str(cwd), stdin=subprocess.DEVNULL, stdout=log_f, stderr=subprocess.STDOUT)
    return PiHandle(
        job_id=job_id, proc=proc, session_dir=session_dir, session_files_before=before,
        log_file=log_f, started_monotonic=time.monotonic(), timeout_seconds=timeout_seconds,
    )


def collect_pi_result(handle: PiHandle, *, timed_out: bool = False) -> PiResult:
    """Call once `handle.proc.poll() is not None` (or after killing it for a timeout). Reads the new
    session file for real cost -- never call this twice for the same handle, the before/after file diff
    is only valid once."""
    if handle.log_file is not subprocess.DEVNULL:
        handle.log_file.close()
    wall = time.monotonic() - handle.started_monotonic
    after = set(handle.session_dir.glob("*.jsonl"))
    new_files = sorted(after - handle.session_files_before)
    session_file = new_files[0] if len(new_files) == 1 else None
    cost = 0.0
    prompt_tokens = completion_tokens = cache_read_tokens = cache_creation_tokens = 0
    provider = model = ""
    if session_file is not None:
        try:
            records = read_usage("pi", session_file)
            cost = sum(r.reported_cost_usd or 0.0 for r in records)
            prompt_tokens = sum(r.prompt_tokens for r in records)
            completion_tokens = sum(r.completion_tokens for r in records)
            cache_read_tokens = sum(r.cache_read_tokens for r in records)
            cache_creation_tokens = sum(r.cache_creation_tokens for r in records)
            if records:
                provider, model = records[-1].provider, records[-1].model
        except Exception:
            cost = 0.0
    return PiResult(
        job_id=handle.job_id, returncode=handle.proc.returncode, wall_seconds=wall,
        session_file=session_file, cost_usd=cost, timed_out=timed_out,
        prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
        cache_read_tokens=cache_read_tokens, cache_creation_tokens=cache_creation_tokens,
        provider=provider, model=model,
        extra={"new_session_files": [str(f) for f in new_files]} if len(new_files) != 1 else {},
    )


def kill_if_timed_out(handle: PiHandle) -> bool:
    """True and kills the process if it has exceeded its timeout_seconds; False (no-op) otherwise or if
    no timeout was set."""
    if handle.timeout_seconds is None:
        return False
    if time.monotonic() - handle.started_monotonic <= handle.timeout_seconds:
        return False
    handle.proc.kill()
    handle.proc.wait()
    return True


def run_pi(job_id: str, **kwargs) -> PiResult:
    """Blocking convenience wrapper over start_pi()/collect_pi_result() for running just one process."""
    handle = start_pi(job_id, **kwargs)
    timed_out = False
    try:
        handle.proc.wait(timeout=handle.timeout_seconds)
    except subprocess.TimeoutExpired:
        handle.proc.kill()
        handle.proc.wait()
        timed_out = True
    return collect_pi_result(handle, timed_out=timed_out)


def new_run_id() -> str:
    return str(uuid.uuid4())

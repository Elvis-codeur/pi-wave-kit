"""Spawns `pi` processes (workers or a coordinator) and reports what they actually did: exit status,
wall time, and real token usage read from each one's own session file (via
llm_ledger_client.session_ingest's Pi adapter). `PiResult.cost_usd` is Pi's OWN reported figure --
evidence only, per this family of libraries' own rule (never trust a provider's self-reported cost as
the real one; a ledger service computes it from its own ModelPricing table).

Ledger logging is EMBEDDED here, not left to the caller: pass a `ledger` (a `LedgerClient`) and
`run_pk` to `collect_pi_result()`/`run_pi()` and the real token counts get logged automatically the
moment a process finishes -- no separate "now call log_call()" step for whatever is orchestrating
these calls to remember (a real, repeated gap this family of libraries kept finding: the calling code,
including an AI agent running a wave by hand, would get the tokens back in `PiResult` and then forget,
or be the thing responsible for not forgetting, to actually log them). Omit `ledger`/`run_pk` and
nothing changes -- logging is opt-in, not required, for a caller that wants to handle it itself.

Two layers: `start_pi()`/`collect_pi_result()` are non-blocking primitives (wave.py's scheduler polls
many processes at once, so it can never block on one). `run_pi()` is the blocking convenience wrapper
for running just one (a single ad-hoc task, or a test)."""

from __future__ import annotations

import logging
import os
import re
import signal
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from llm_ledger_client import LedgerClient
from llm_ledger_client.session_ingest import read_usage

_logger = logging.getLogger("pi_wave_kit.run_pi")


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


@dataclass(frozen=True)
class CgroupLimits:
    """Optional `systemd-run --user --scope` memory isolation for one `pi` process -- the same
    guard the sibling `agentic-reasoning-translator` project adopted as a standing rule after
    oomd killed an entire terminal session (the shell itself, plus every other job running in
    it, not just the one job that ran out of memory) twice in one week. `start_pi`/`run_pi`
    prefix the real `pi` command with `systemd-run`'s own argv when given one of these -- no
    subprocess logic is duplicated, this only changes what the first argv entries are.

    `mem_high`, if omitted, defaults to 90% of `mem_max` (the same ratio pi_job.sh used) when
    `mem_max` parses as a plain `<int><M|G>`; pass `mem_high` explicitly for any other unit.
    `systemd-run --scope` execs the target command in place (same PID), so the existing
    process-group kill path in `kill_if_timed_out`/`_kill_group` is unaffected."""

    mem_max: str
    mem_high: str | None = None

    def resolved_mem_high(self) -> str | None:
        if self.mem_high is not None:
            return self.mem_high
        m = re.match(r"^(\d+)([MG])$", self.mem_max)
        if not m:
            return None
        value, unit = m.groups()
        return f"{int(int(value) * 0.9)}{unit}"

    def systemd_run_prefix(self) -> list[str]:
        prefix = ["systemd-run", "--user", "--scope", "-q", "-p", f"MemoryMax={self.mem_max}"]
        high = self.resolved_mem_high()
        if high:
            prefix += ["-p", f"MemoryHigh={high}"]
        prefix.append("--")
        return prefix


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


def _build_command(provider: str, model: str, thinking: str, session_dir: Path, prompt: str | None,
                    extra_args: list[str] | None, cgroup: CgroupLimits | None = None) -> list[str]:
    cmd = ["pi", "--provider", provider, "--model", model, "--thinking", thinking, "--print",
           "--session-dir", str(session_dir), *(extra_args or [])]
    if prompt is not None:
        cmd.append(prompt)
    if cgroup is not None:
        cmd = cgroup.systemd_run_prefix() + cmd
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
    cgroup: CgroupLimits | None = None,
) -> PiHandle:
    """Non-blocking: starts the process and returns a handle immediately. Caller is responsible for
    polling `handle.proc.poll()` and calling collect_pi_result() once it's not None, or killing it
    itself once `timeout_seconds` has elapsed (wave.py's scheduler does both).

    Pass `cgroup` (a `CgroupLimits`) to run this one process under `systemd-run --user --scope`
    memory limits; omit it and nothing changes from before."""
    session_dir = Path(session_dir)
    session_dir.mkdir(parents=True, exist_ok=True)
    before = set(session_dir.glob("*.jsonl"))
    cmd = _build_command(provider, model, thinking, session_dir, prompt, extra_args, cgroup)
    log_f = open(log_path, "w", encoding="utf-8") if log_path else subprocess.DEVNULL
    # Own process group, so a timeout kill also reaches any child processes the agent spawned (subagents,
    # tools) -- proc.kill() alone only killed the parent (real gap found in review, 2026-10-16).
    proc = subprocess.Popen(cmd, cwd=str(cwd), stdin=subprocess.DEVNULL, stdout=log_f, stderr=subprocess.STDOUT,
                            start_new_session=True)
    return PiHandle(
        job_id=job_id, proc=proc, session_dir=session_dir, session_files_before=before,
        log_file=log_f, started_monotonic=time.monotonic(), timeout_seconds=timeout_seconds,
    )


def collect_pi_result(
    handle: PiHandle,
    *,
    timed_out: bool = False,
    ledger: LedgerClient | None = None,
    run_pk: int | None = None,
    call_purpose: str = "",
) -> PiResult:
    """Call once `handle.proc.poll() is not None` (or after killing it for a timeout). Reads the new
    session file for real cost -- never call this twice for the same handle, the before/after file diff
    is only valid once.

    If `ledger` and `run_pk` are both given, the real token counts are logged to that ledger run
    automatically before returning -- this is the embedded, under-the-hood logging: whatever called
    this function doesn't have to remember a separate step. Idempotent by `job_id` (passed as
    `external_id`), so a retried/duplicate collect for the same job can't double-log. A process that
    produced no usable session file (crashed before writing anything) logs nothing -- there is nothing
    real to record."""
    if handle.log_file is not subprocess.DEVNULL:
        handle.log_file.close()
    wall = time.monotonic() - handle.started_monotonic
    after = set(handle.session_dir.glob("*.jsonl"))
    new_files = sorted(after - handle.session_files_before)
    # Real bug fixed 2026-10-16: this used to read the session file only when EXACTLY ONE new file existed and
    # silently report $0 otherwise -- a relaunched/forked job leaves several, so the 2026-10-15 S2-correction
    # wave recorded $5.96 while its session files show $14.51 actually spent. Now: sum usage over ALL new files.
    session_file = new_files[0] if new_files else None
    cost = 0.0
    prompt_tokens = completion_tokens = cache_read_tokens = cache_creation_tokens = 0
    provider = model = ""
    for f in new_files:
        try:
            records = read_usage("pi", f)
        except Exception:
            _logger.warning("pi_wave_kit: could not read usage from %s (cost may be under-counted)", f)
            continue
        cost += sum(r.reported_cost_usd or 0.0 for r in records)
        prompt_tokens += sum(r.prompt_tokens for r in records)
        completion_tokens += sum(r.completion_tokens for r in records)
        cache_read_tokens += sum(r.cache_read_tokens for r in records)
        cache_creation_tokens += sum(r.cache_creation_tokens for r in records)
        if records:
            provider, model = records[-1].provider, records[-1].model
    result = PiResult(
        job_id=handle.job_id, returncode=handle.proc.returncode, wall_seconds=wall,
        session_file=session_file, cost_usd=cost, timed_out=timed_out,
        prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
        cache_read_tokens=cache_read_tokens, cache_creation_tokens=cache_creation_tokens,
        provider=provider, model=model,
        extra={"new_session_files": [str(f) for f in new_files], "ambiguous_attribution": True}
              if len(new_files) > 1 else ({"new_session_files": []} if not new_files else {}),
    )
    if len(new_files) > 1:
        # Cost above is the SUM over all new files -- conservative for cap accounting (never under-counts real
        # money). But the files may belong to another process sharing this session_dir, so the per-call ledger
        # entry is skipped rather than risk double-booking; the warning makes the gap visible.
        _logger.warning("pi_wave_kit: job %s left %d new session files; cost $%.4f counted for caps, ledger entry "
                        "skipped (ambiguous attribution) -- give every job its own session_dir", handle.job_id,
                        len(new_files), cost)
    elif ledger is not None and run_pk is not None:
        _log_to_ledger(ledger, run_pk, result, call_purpose)
    return result


def _log_to_ledger(ledger: LedgerClient, run_pk: int, result: PiResult, call_purpose: str) -> None:
    if not result.provider or not result.model:
        _logger.warning("pi_wave_kit: job %s produced no provider/model usage, nothing to log", result.job_id)
        return
    ledger.log_call(
        run_pk,
        provider=result.provider,
        model=result.model,
        prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens,
        cache_read_tokens=result.cache_read_tokens,
        cache_creation_tokens=result.cache_creation_tokens,
        billing="api",
        external_id=f"pi-wave-kit:{result.job_id}",
        call_purpose=call_purpose,
        # Pi's own reported cost, kept only as evidence alongside the real server-computed cost --
        # never read back as the actual spend (see module docstring).
        api_equivalent_cost_usd=round(result.cost_usd, 6),  # server field has 6 decimal places (400 otherwise)
    )


def _kill_group(proc: subprocess.Popen) -> None:
    """Kill the whole process group (the agent and any children it spawned), then reap the parent."""
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        proc.kill()
    proc.wait()


def kill_if_timed_out(handle: PiHandle) -> bool:
    """True and kills the process if it has exceeded its timeout_seconds; False (no-op) otherwise or if
    no timeout was set."""
    if handle.timeout_seconds is None:
        return False
    if time.monotonic() - handle.started_monotonic <= handle.timeout_seconds:
        return False
    _kill_group(handle.proc)
    return True


def run_pi(
    job_id: str,
    *,
    ledger: LedgerClient | None = None,
    run_pk: int | None = None,
    call_purpose: str = "",
    **kwargs,
) -> PiResult:
    """Blocking convenience wrapper over start_pi()/collect_pi_result() for running just one process.
    `ledger`/`run_pk`/`call_purpose` are forwarded to collect_pi_result() -- give them here and this
    one real call logs itself automatically, same as the wave path."""
    handle = start_pi(job_id, **kwargs)
    timed_out = False
    try:
        handle.proc.wait(timeout=handle.timeout_seconds)
    except subprocess.TimeoutExpired:
        _kill_group(handle.proc)
        timed_out = True
    return collect_pi_result(handle, timed_out=timed_out, ledger=ledger, run_pk=run_pk, call_purpose=call_purpose)


def new_run_id() -> str:
    return str(uuid.uuid4())

# pi-wave-kit

Orchestrate a "wave" of headless [Pi](https://github.com/badlogic/pi-mono) worker processes — or any
CLI coding-agent that can be scripted the same way — under a **concurrency AND cumulative-dollar-budget
cap**, with an escalation protocol and a generic stage-check framework. Extracted from a document-
translation pipeline's real, months-long production use orchestrating DeepSeek translation waves
(10 concurrent workers, hundreds of documents, real dollar caps that were never exceeded).

## What's generic here, and what isn't

The **hard part** — a rolling pool that only launches a new job if `committed + reserved-by-running-jobs
+ this job's cap` stays under the wave's total budget, even though each job's real cost isn't known
until it finishes — is fully generic and ported here (`pi_wave_kit.wave.run_wave`). So is the escalation
protocol (`pi_wave_kit.escalate`) and process spawning/cost-reading (`pi_wave_kit.run_pi`).

**Deliberately NOT ported**: the original project's concrete pipeline stages (chunk/translate/verify/
assemble — all document-translation-specific). `pi_wave_kit.stage_check` gives you the *framework*
(`Condition`, `evaluate()`, `reduce()`) with zero concrete stages — you write your own check functions
for your own pipeline and compose them with it. Porting the concrete stages here would make this
library useful for exactly one project; the framework is what actually generalizes.

## Quick start

```python
from pi_wave_kit.wave import WaveJob, run_wave
from pi_wave_kit.run_pi import start_pi, collect_pi_result, kill_if_timed_out

jobs = [WaveJob(job_id=doc_id, cap_usd=0.60, projected_usd=0.20) for doc_id in my_documents]

def launch(job):
    return start_pi(job.job_id, provider="deepseek", model="deepseek-flash", thinking="low",
                      cwd=".", session_dir=f"sessions/{job.job_id}",
                      prompt=my_prompt_for(job.job_id), timeout_seconds=1800)

summary = run_wave(
    jobs, launch_fn=launch, collect_fn=lambda h, timed_out: my_collect(h, timed_out),
    is_timed_out=kill_if_timed_out, concurrency=10, wave_cap_usd=15.0,
    summary_path="wave-summary.json", stop_file="STOP",
    on_event=print,
)
print(summary.committed_usd, summary.not_successful())
```

## Cost tracking is embedded, not a separate step

`run_pi`/`collect_pi_result` read real token counts from the worker's own Pi session file (via
[llm-ledger-client](https://github.com/Elvis-codeur/llm-ledger-client)'s Pi adapter), and — pass
`ledger`/`run_pk` — log them to that ledger run automatically before returning:

```python
from llm_ledger_client import LedgerClient
from pi_wave_kit.run_pi import collect_pi_result

ledger = LedgerClient("http://127.0.0.1:8090/api")
run = ledger.create_run("wave-2026-10-15", label="translation-wave")

def collect(handle, timed_out):
    # ledger+run_pk here means every job logs itself as it finishes -- no separate "now call
    # log_call()" step for whatever is running the wave to remember.
    return my_wrapper(collect_pi_result(handle, timed_out=timed_out, ledger=ledger, run_pk=run["id"]))
```

Omit `ledger`/`run_pk` and nothing changes from before — this is opt-in, not required. But wiring it in
once, here, means every job in every wave logs itself for the lifetime of the pipeline; nothing further
to remember per job, per wave, or per agent that happens to be the one running it that day.

## Optional memory isolation per job

Pass a `CgroupLimits` to `start_pi`/`run_pi` and that one process runs under `systemd-run --user
--scope -p MemoryMax=... -p MemoryHigh=...` instead of a bare `subprocess.Popen` -- oomd then kills
only that job's scope, never the whole terminal session (a real incident: a single job that ran
over budget took the entire shell, and every other job running in it, down twice):

```python
from pi_wave_kit.run_pi import run_pi, CgroupLimits

result = run_pi("job-1", provider="deepseek", model="deepseek-flash", thinking="low",
                 cwd=".", session_dir="sessions/job-1",
                 cgroup=CgroupLimits(mem_max="2500M"))  # mem_high defaults to 90% of mem_max
```

Omit `cgroup` and nothing changes. `systemd-run --scope` execs the target in place (same PID), so
timeout-kill (`kill_if_timed_out`) still reaches the real process group.

## The coordinator role doesn't have to be a Pi session

`pi_wave_kit.coordinator` assumes nothing about who's watching the wave — an interactive Pi session
(`pi_coordinator_command()` prints the command to start one) or a Claude Code / any other agent session
reading `pending_stop_escalations()`/`summarize_for_coordinator()` directly works identically. The
project this library came from originally assumed only the former; it was later confirmed, in real
production use, that an agent session playing this role from the main repo (reading escalation files and
the wave summary directly, with no need for Pi's own inter-agent messaging tool) produced correct,
verified output across real translation waves.

## Status

Freshly extracted (2026-10-15), 35 tests passing (including a real-subprocess integration test via a
fake `pi` executable on PATH — not a full real-money test yet, that's a separate, explicit step given
it costs real API money).

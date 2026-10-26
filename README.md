# pi-wave-kit

Orchestrate a "wave" of headless [Pi](https://github.com/badlogic/pi-mono) worker processes — or any
CLI coding-agent that can be scripted the same way — under a **concurrency AND cumulative-dollar-budget
cap**, with an escalation protocol and a generic stage-check framework. Extracted from a document-
translation pipeline's real, months-long production use orchestrating DeepSeek translation waves
(10 concurrent workers, hundreds of documents, real dollar caps that were never exceeded).

## Launching a remotely-reachable session (so you can steer it later, from elsewhere)

`pi -p` (headless) processes one prompt and exits; a backgrounded *interactive* session with no real
pty hits EOF on its next input and dies after one turn too -- confirmed live. The only way to leave an
interactive session alive and reachable is a real pty (`screen` or `tmux`), joined to the pi-messenger
mesh. This is confirmed, working, and has one real constraint that cannot be worked around: **the
session must be launched this way in the first place** -- one started by typing `pi` normally, with no
mesh auto-join, is not remotely reachable later, however long it keeps running.

### The exact by-hand terminal command (no app, no library -- freshly re-tested 2026-10-24)

```bash
# once per project directory, so the session is reachable by anyone who messages it by name:
mkdir -p .pi && echo '{"autoRegister": true}' > .pi/pi-messenger.json

PI_AGENT_NAME=Home screen -L -Logfile screen.log -dmS Home \
  pi --provider deepseek --model deepseek-flash --thinking low \
     --session-dir sessions --name Home --approve \
     "Standby. Remember the codeword TOUCAN-9. Reply ACK-TOUCAN-9-<message> to anything you receive."
```

`PI_AGENT_NAME=Home` is required, not optional: `--name` alone only sets the session's *display*
title, not its pi-messenger identity -- without the env var a peer sees a random generated name
(`QuickRaven`, etc.) instead of the name you chose, so a message addressed to "Home" would never
arrive. `screen -dmS Home ... pi ...` execs `pi` in place, so the screen scope lives exactly as long
as `pi` does.

**Confirm it worked:** `screen -ls` lists `<pid>.Home (Detached)` while it's alive; after about 10-15
seconds, `.pi/messenger/feed.jsonl` in that directory gets a `{"type":"join","agent":"Home"}` line --
that's the real, independently-checkable proof it joined the mesh (never trust a session's own
"I'm standing by" reply for this). `screen -S Home -X hardcopy out.txt` dumps its live terminal.

**Message it from elsewhere** (there is no sending CLI for pi-messenger -- the sender must itself be
another `pi` agent calling the `pi_messenger` tool; a plain script or `curl` cannot reach it this way):

```bash
PI_AGENT_NAME=Away pi -p --session-dir away-sessions \
  "Use pi_messenger to join the mesh if needed, then send a DM to the peer named Home with exactly \
this text: PING-FROM-AWAY. Report success or failure only." < /dev/null
```

Re-tested live end to end just before writing this: `Away`'s `PING-FROM-AWAY` was delivered and
`Home` replied `ACK-TOUCAN-9-...` 1.18 seconds later, both lines confirmed in `feed.jsonl`, not from
either agent's own report of what happened. Stop a session with `screen -S Home -X quit`.

### Doing the same thing with this library, one command

```bash
pi-wave-session launch Home deepseek-flash /path/to/project \
    --prompt "Standby. Remember the codeword TOUCAN-9. Reply ACK-TOUCAN-9-<message> to anything you receive." \
    --provider deepseek --thinking low
pi-wave-session status Home     # alive / not running
pi-wave-session hardcopy Home   # dump its live terminal
pi-wave-session stop Home
```

`launch` does the by-hand recipe above AND writes `.pi/pi-messenger.json` for you if that project
doesn't already have one (never overwrites an existing one) -- so the session it starts is really
reachable, not just alive. Pass `--no-mesh` to skip that if the project already manages its own
messenger config. Equivalent Python: `pi_wave_kit.interactive.launch_screen_session()` /
`is_alive()` / `hardcopy()` / `stop()`.

### Why there's no CLI for *sending* a message

Sending needs no new wrapper: it's just `pi_wave_kit.run_pi.run_pi()` (or a plain `pi -p` call, as
above) with a prompt telling a one-shot agent to use the `pi_messenger` tool -- that genuinely is
what sending requires, since pi-messenger has no sending CLI of its own.

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

## Resuming a closed session headlessly

A session closed after a one-shot `pi -p` run (clean exit, nothing kept alive) can be picked back up
later, in a brand-new headless process, and it really does have the prior context -- confirmed live
(2026-10-24): a fact given only in the earlier, closed run was correctly recalled.

```python
from pi_wave_kit.run_pi import run_pi, resume_pi_headless

first = run_pi("job-1", provider="deepseek", model="deepseek-flash", thinking="low",
                cwd=".", session_dir="sessions", prompt="Remember X for later.")

# ... later, maybe from a different process entirely ...
later = resume_pi_headless("job-1-resume", session=first.session_file, prompt="What was X?",
                            provider="deepseek", model="deepseek-flash", thinking="low", cwd=".")
```

`session` must be the earlier call's own session FILE PATH (not a bare id). Cost is counted correctly
even though the file isn't new (resuming appends to it): only the usage records added by THIS call are
counted, never the whole file's history re-counted or silently reported as $0.

## A single ad-hoc job from the command line

**This is the owner's default way to launch any Pi/agent job as of 2026-10-26** ("let
pi-wave-kit be our default app") -- install it globally once, from this repo, so it's on `PATH`
from any project without a per-repo dependency:

```bash
uv tool install --editable .   # from this repo's root; --editable so local fixes apply immediately
```

That installs `pi-wave-job` and `pi-wave-session` as real commands, confirmed working from any
directory. **Never fall back to a raw `pi -p` call or a project-local copy of `pi_job.sh`-style
shell script** -- five such copies had already drifted across different repos/worktrees by
2026-10-26 before this became the default; a bug found while using either command gets fixed/
filed in this repo, not patched around locally wherever it was hit.

For one job that doesn't need a whole wave, `pi-wave-job` (console script, installed with this
package) is the CLI equivalent of the sibling `agentic-reasoning-translator` project's old ad-hoc
`pi_job.sh` (now superseded by this), built on the tested `run_pi()` path -- it reads the prompt
file's content once and passes it straight through as a real argv string, never staging it to a
destination path, so the exact "cp: are the same file" bug class that silently killed a job there
(issue #1 / ERRATA #43) cannot happen here:

```bash
pi-wave-job my-job deepseek-flash /path/to/workdir prompt.md \
    --provider deepseek --thinking low --mem-max 2500M --jobs-dir pi-wave-jobs
```

Writes `pi-wave-jobs/my-job/{sessions/,log.txt,result.json}` and exits non-zero if the job failed
or timed out. Run `pi-wave-job --help` for every option.

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

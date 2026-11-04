# pi-wave-kit

Orchestrate a "wave" of headless [Pi](https://github.com/badlogic/pi-mono) worker processes — or any
CLI coding-agent that can be scripted the same way — under a **concurrency AND cumulative-dollar-budget
cap**, with an escalation protocol and a generic stage-check framework. Extracted from a document-
translation pipeline's real, months-long production use orchestrating DeepSeek translation waves
(10 concurrent workers, hundreds of documents, real dollar caps that were never exceeded).

## Capabilities at a glance

Budget and waves

- [**Waves under a concurrency and dollar cap**](#waves-under-a-concurrency-and-dollar-cap) — `run_wave`: a job launches only if spent + caps of running jobs + its cap fits the wave cap; resumable summary JSON; STOP file.
- [**Live per-job cost cap**](#live-per-job-cost-cap) — `run_wave(live_cost_cap=True)` / `cost_capped()`: a running job is killed once its own spend exceeds its cap.
- [**Resume on timeout**](#resuming-a-job-that-hits-its-timeout-resume_fn-max_resumes) — `run_wave(resume_fn=, max_resumes=)`: a timed-out job continues in its own pi session.
- [**Wave CLI over prompt files**](#a-capped-wave-from-the-command-line-pi-wave-run) — `pi-wave-run`: one job per prompt file, dry run by default, projected and worst-case cost, budget-file ledger.
- [**Cost recording and the ledger**](#cost-recording-and-the-ledger) — real token counts and pi's own cost from session files, logged to llm-ledger-client automatically; DeepSeek peak-price caveat.

Single jobs and isolation

- [**Single ad-hoc job CLI**](#a-single-ad-hoc-job-from-the-command-line-pi-wave-job) — `pi-wave-job`: one job, with `--cap-usd`, `--timeout`, `--mem-max`, any of four agents.
- [**Memory isolation via systemd-run**](#optional-memory-isolation-per-job) — `CgroupLimits` / `--mem-max`: an out-of-memory kill takes one job, not your terminal.
- [**Process-group kill**](#live-per-job-cost-cap) — `kill_group(proc)`: kills a job and every subagent/tool process it spawned.
- [**Other coding agents**](#other-coding-agents-opencode-codex-claude-code) — `pi_wave_kit.agents`: run and resume OpenCode, Codex and Claude Code jobs like pi jobs.
- [**Headless resume of a closed session**](#resuming-a-closed-session-headlessly) — `resume_pi_headless`: continue a finished session with its context, cost counted correctly.

Coordination

- [**Escalation protocol**](#escalation-protocol) — `pi_wave_kit.escalate`: a worker that cannot proceed writes a record and messages the coordinator instead of improvising.
- [**Stage checks**](#stage-checks) — `pi_wave_kit.stage_check`: a PASS/FIX/WARN/ESCALATE framework for "is this stage really done"; a full real pipeline ships as the `stt_translation` plugin.
- [**Coordinator role**](#the-coordinator-role-doesnt-have-to-be-a-pi-session) — `pi_wave_kit.coordinator`: a Pi session or any agent (e.g. Claude Code) watches the wave and handles escalations.

Interactive sessions

- [**Remotely reachable interactive sessions**](#launching-a-remotely-reachable-session-so-you-can-steer-it-later-from-elsewhere) — `pi-wave-session launch`: a pi session in `screen`, joined to the pi-messenger mesh.
- [**Three ways to reach a running session**](#three-ways-to-reach-a-running-session-and-when-each-is-right) — `pi-wave-session send` (mesh DM, confirmed from the feed), `type` (keystrokes), `hardcopy` (read-only).

Every console script documents itself: `pi-wave-job --help`, `pi-wave-run --help`, `pi-wave-session --help`.

## Install

**This is the owner's default way to launch any Pi/agent job as of 2026-10-26** ("let
pi-wave-kit be our default app") -- install it globally once, from this repo, so it's on `PATH`
from any project without a per-repo dependency:

```bash
uv tool install --editable .   # from this repo's root; --editable so local fixes apply immediately
```

That installs `pi-wave-job`, `pi-wave-run` and `pi-wave-session` as real commands, confirmed working
from any directory. **Never fall back to a raw `pi -p` call or a project-local copy of
`pi_job.sh`-style shell script** -- five such copies had already drifted across different
repos/worktrees by 2026-10-26 before this became the default; a bug found while using either command
gets fixed/filed in this repo, not patched around locally wherever it was hit.

## Waves under a concurrency and dollar cap

### What's generic here, and what isn't

The **hard part** — a rolling pool that only launches a new job if `committed + reserved-by-running-jobs
+ this job's cap` stays under the wave's total budget, even though each job's real cost isn't known
until it finishes — is fully generic and ported here (`pi_wave_kit.wave.run_wave`). So is the escalation
protocol (`pi_wave_kit.escalate`) and process spawning/cost-reading (`pi_wave_kit.run_pi`).

**Deliberately NOT ported**: the original project's concrete pipeline stages (chunk/translate/verify/
assemble — all document-translation-specific). `pi_wave_kit.stage_check` gives you the *framework*
(`Condition`, `evaluate()`, `reduce()`) with zero concrete stages — you write your own check functions
for your own pipeline and compose them with it. Porting the concrete stages here would make this
library useful for exactly one project; the framework is what actually generalizes.

### Quick start

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
    live_cost_cap=True,          # also kill a running job above its own cap_usd (see below)
    on_event=print,
)
print(summary.committed_usd, summary.not_successful())
```

- **Resumable**: the summary JSON is the source of truth. Re-run the same job list and jobs that already
  succeeded are skipped; every recorded spend (failed jobs too) still counts against the cap.
- **Stop file**: while `stop_file` exists no new job launches; running jobs finish.
- **Wave cap**: when the next job's cap does not fit, the pool waits for a running job to release its
  reservation; once nothing is running it stops and reports the rest as `not_launched`.

### Live per-job cost cap

The launch gate above only *reserves* a running job's cap: until this was added, a running job's spend was
seen only when it ended, so one runaway worker could spend far past its `cap_usd` (issue #17; the original
translation launcher polled live cost and killed the worker, `wiki/rules/translation/pi-wave-runner.md`).

- `run_wave(..., live_cost_cap=True, cost_poll_seconds=10)` re-reads each running job's spend from its own
  session files and kills its whole process group once it exceeds the job's `cap_usd` (what is left of it,
  for a resumed job). The job is recorded `failed` with reason `cost cap: spent $x > cap $y`
  (also in `result.extra["kill_reason"]`) and is never resumed. Default off: existing callers are unchanged.
- `run_pi.cost_capped(is_timed_out, cap_usd=...)` or `cap_for=lambda handle: ...` wraps any `is_timed_out`
  hook the same way, for your own poll loop or a per-job cap rule.
- `run_pi.session_cost_usd(handle)` is the live spend: `usage.cost.total` summed over the job's NEW session
  files (or the records appended since a resume); a half-written last line is skipped, not raised.
- `run_pi(..., cap_usd=0.30)` caps one blocking job; `pi-wave-job --cap-usd 0.30` from the command line.
- `run_pi.kill_group(proc)` is the process-group kill these use (public since issue #18; the old private
  name `_kill_group` still works).

A job can overshoot its cap by what it spends during one poll. Live capping needs pi handles
(`start_pi`, `start_pi_resume`, `agents.start_agent("pi", ...)`): OpenCode, Codex and Claude Code report
cost only when they finish.

### Resuming a job that hits its timeout (`resume_fn`, `max_resumes`)

`run_wave(..., resume_fn=..., max_resumes=2)`: when a worker is stopped by `timeout_seconds` while still making progress, its spend so far is
committed against the wave cap and `resume_fn(job, old_handle, result)` starts a NEW process in the same pi session (typically
`start_pi(..., extra_args=["--session", str(old_session_file)], prompt="Continue where you stopped...")`). After `max_resumes` a further
timeout is a failure as before. Both parameters default to off, so existing callers are unchanged.

### A capped wave from the command line (`pi-wave-run`)

No Python needed for the common case: one job per prompt file, N at a time, under a total cap (issue #20).
**A dry run unless `--yes-spend`**: it prints the plan, the projected cost and the worst case, and launches
nothing (every paid wave needs an explicit yes for its projection).

```bash
pi-wave-run --prompts-dir prompts --wave-cap-usd 2 --job-cap-usd 0.30                 # dry run: plan + cost
pi-wave-run --prompts-dir prompts --wave-cap-usd 2 --job-cap-usd 0.30 --yes-spend \
    --concurrency 4 --timeout 1800 --mem-max 1500M --out-dir work/round-3            # launches (paid)
pi-wave-run --job-list jobs.txt --wave-cap-usd 5 --job-cap-usd 0.5 --budget-file budget.json \
    --per-job-workdir --require-output out.jsonl --max-resumes 1 --yes-spend
```

- **Input**: `--prompts-dir DIR` (each `*.md` is a job, id = file stem) or `--job-list FILE` (one job per line:
  `[job_id] prompt_file [cap_usd]`, `#` comments, paths relative to the list).
- **Model**: `--provider/--model/--thinking` (default `deepseek`/`deepseek-flash`/`low`), `--extra-arg` for pi.
- **Caps**: `--wave-cap-usd` (launch gate), `--job-cap-usd` (reserved at launch and enforced live;
  `--no-live-cap` to disable the live kill), `--mem-max/--mem-high` per job.
- **Budget ledger**: `--budget-file` holds `{"total_usd": X, "rounds": [{"spent_usd": Y}, ...]}`; the wave cap
  is clipped to what is left minus `--budget-margin`, and a real run appends its spend as a round.
- **Output** under `--out-dir`: `wave-summary.json` (resumable: re-running skips jobs that succeeded),
  `wave-result.json` (committed, per-job status/cost/reason, not launched), and per job `job.json` (prompt
  file + sha256, model, cap, every attempt's tokens and peak-rate cost), `sessions/`, `log.txt`.
- **Stop**: `touch <out-dir>/STOP` (or `--stop-file`). Exit 0 only if every job succeeded.

### Cost recording and the ledger

`run_pi`/`collect_pi_result` read real token counts from the worker's own Pi session file (via
[llm-ledger-client](https://github.com/Elvis-codeur/llm-ledger-client)'s Pi adapter), and — pass
`ledger`/`run_pk` — log them to that ledger run automatically before returning:

```python
from llm_ledger_client import LedgerClient
from pi_wave_kit.run_pi import collect_pi_result

# $LLM_LEDGER_URL + $LLM_LEDGER_TOKEN (a per-machine token from the hosted ledger's API tokens
# page), so the same script reports costs from any machine.
ledger = LedgerClient.from_env(project="my-project")
run = ledger.create_run("wave-2026-10-15", label="translation-wave")

def collect(handle, timed_out):
    # ledger+run_pk here means every job logs itself as it finishes -- no separate "now call
    # log_call()" step for whatever is running the wave to remember.
    return my_wrapper(collect_pi_result(handle, timed_out=timed_out, ledger=ledger, run_pk=run["id"]))
```

Omit `ledger`/`run_pk` and nothing changes from before — this is opt-in, not required. But wiring it in
once, here, means every job in every wave logs itself for the lifetime of the pipeline; nothing further
to remember per job, per wave, or per agent that happens to be the one running it that day.

**What the dollar figure is.** `PiResult.cost_usd` (and every cap check) is Pi's OWN reported cost, the sum
of `usage.cost.total` in the session file(s) — evidence, not the billed price. For DeepSeek, Pi's price
table is the **peak** rate at all hours; off-peak is half, so off-peak the recorded figure over-states real
spend by 2x (conservative for caps). The ledger service computes the real cost from tokens. Measurements:
`wiki/research/pi-money-usage-recording.md`. A job that leaves several new session files has its cost summed
over all of them (never under-counted) and its per-call ledger entry skipped, with a warning.

## A single ad-hoc job from the command line (`pi-wave-job`)

For one job that doesn't need a whole wave, `pi-wave-job` (console script, installed with this
package) is the CLI equivalent of the sibling `agentic-reasoning-translator` project's old ad-hoc
`pi_job.sh` (now superseded by this), built on the tested `run_pi()` path -- it reads the prompt
file's content once and passes it straight through as a real argv string, never staging it to a
destination path, so the exact "cp: are the same file" bug class that silently killed a job there
(issue #1 / ERRATA #43) cannot happen here:

```bash
pi-wave-job my-job deepseek-flash /path/to/workdir prompt.md \
    --provider deepseek --thinking low --mem-max 2500M --jobs-dir pi-wave-jobs \
    --cap-usd 0.30 --timeout 1800
```

Writes `pi-wave-jobs/my-job/{sessions/,log.txt,result.json}` and exits non-zero if the job failed,
timed out or was killed by its cost cap (`result.json`: `cap_usd`, `kill_reason`). `--cap-usd` is the
live cost cap above, for fresh pi jobs (not `--session`, not other agents). Run `pi-wave-job --help`
for every option.

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
timeout-kill (`kill_if_timed_out`) still reaches the real process group. CLI: `--mem-max`/`--mem-high`
on `pi-wave-job` and `pi-wave-run`.

## Other coding agents: OpenCode, Codex, Claude Code

`pi_wave_kit.agents` runs the same kind of job on `pi`, `opencode`, `codex` or `claude`: start it
(a handle `run_wave` can schedule), resume its session with a new message, and get back the final
text, the session id and real token counts, logged to the ledger if you pass `ledger`/`run_pk`.
Background and per-agent details: `wiki/research/coding-agents-keys-logins-and-control.md`.

```python
from pi_wave_kit import agents

first = agents.run_agent("codex", "task-1", prompt="Summarise README.md", model="gpt-5.6-luna",
                         cwd="/path/to/repo", out_dir="jobs/task-1")
follow_up = agents.run_agent("codex", "task-1b", prompt="Now list the open questions",
                             model="gpt-5.6-luna", cwd="/path/to/repo", out_dir="jobs/task-1b",
                             session_id=first.session_id)   # same conversation, continued
print(follow_up.text, follow_up.prompt_tokens, follow_up.completion_tokens)
```

- `model`: `"provider/model"` for pi and opencode (`"deepseek/deepseek-flash"`), the agent's own
  name for codex (`"gpt-5.6-luna"`) and claude (`"haiku"`, `"sonnet"`).
- `env={...}` applies to that one job only: run it on a client's own key or config home, e.g.
  `env={"CODEX_HOME": "~/.codex-client-a"}` or `env={"ANTHROPIC_API_KEY": client_key}`.
- `billing` is guessed (`"subscription"` for Claude Code/Codex without an API key in the
  environment, `"api"` otherwise) and can be passed explicitly.
- In a wave: `launch_fn=lambda job: agents.start_agent(...)`,
  `collect_fn=lambda h, t: agents.to_wave_result(agents.collect_agent_result(h, timed_out=t))`,
  `is_timed_out=agents.kill_if_timed_out`. Codex reports no cost, so its jobs count $0 against the
  wave cap (the ledger still prices their tokens).
- Tools that need permission prompts in a headless run take the agent's own flags through
  `extra_args` (e.g. `["--permission-mode", "acceptEdits"]` for claude, `["--auto"]` for opencode).
- From the command line: `pi-wave-job <name> <model> <workdir> <prompt_file> --agent codex`, and
  `--session <id>` to continue an earlier job's session.

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
counted, never the whole file's history re-counted or silently reported as $0. The non-blocking halves
are `start_pi_resume`/`collect_pi_resume_result`. Live test: `wiki/research/pi-resume-and-remote-steer-live-test.md`.

## Escalation protocol

A worker never improvises around something it cannot do: it records an escalation and (if there is a
coordinator) sends it one line, then stops or continues as the record says. `pi_wave_kit.escalate` never
calls a model.

```python
from pi_wave_kit.escalate import Escalation, write_record, is_blocked

e = write_record(Escalation(item_id="doc-17", stage="translation", kind="data_problem", action="stop",
                            summary="chunk stage 1437 has no cues", coordinator="Coord"), "escalations/")
print(e.instructions())       # what to send to the coordinator, then "Now stop: ..."
is_blocked("escalations/", "doc-17")   # True: a launcher records this job as blocked, not success
```

- Kinds: `code_bug`, `data_problem`, `decision_needed`, `tool_failure`, `budget_or_time`; actions `stop` / `continue`.
- One JSON record per escalation under `<dir>/<item>/<timestamp>.json`; `read_records()` lists them.
- The message line is `ESCALATION <item> <stage> <kind> <action>: <summary> [file: <path>]`, sent over pi-messenger
  when a coordinator exists. How the production launcher wired this (environment variables, blocked runs,
  retry): `wiki/rules/translation/pi-wave-runner.md`, "Stage checks and escalation".

## Stage checks

`pi_wave_kit.stage_check` answers "is this stage really done?" with conditions instead of a worker's own
claim: each `Condition` is PASS, WARN, or FAIL with an action (FIX: the worker can fix it and re-check;
ESCALATE: someone else must decide). You write the check functions for your own pipeline and combine them
with `evaluate(stage, ctx, STAGES)`, `reduce()` and `render()` (one `[PASS|FAIL|WARN] id: detail` line each).
No concrete stage is built in. The full real pipeline it came from (8 stages: curate, stt_verification,
chunk_and_clean, translation, gates, assemble, review, final, plus its verbatim prompts and glossary) ships
as an optional plugin: `pi_wave_kit/plugins/stt_translation/README.md`.

## The coordinator role doesn't have to be a Pi session

`pi_wave_kit.coordinator` assumes nothing about who's watching the wave — an interactive Pi session
(`pi_coordinator_command()` prints the command to start one) or a Claude Code / any other agent session
reading `pending_stop_escalations()`/`summarize_for_coordinator()` directly works identically. The
project this library came from originally assumed only the former; it was later confirmed, in real
production use, that an agent session playing this role from the main repo (reading escalation files and
the wave summary directly, with no need for Pi's own inter-agent messaging tool) produced correct,
verified output across real translation waves.

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

**Message it from elsewhere** (pi-messenger itself has no sending CLI -- the sender must be another
`pi` agent calling the `pi_messenger` tool; a plain script or `curl` cannot reach it this way;
`pi-wave-session send` below wraps exactly this):

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
pi-wave-session send Home "PING" --workdir /path/to/project   # mesh DM, confirmed from feed.jsonl
pi-wave-session hardcopy Home   # dump its live terminal
pi-wave-session stop Home
```

`launch` does the by-hand recipe above AND writes `.pi/pi-messenger.json` for you if that project
doesn't already have one (never overwrites an existing one) -- so the session it starts is really
reachable, not just alive. Pass `--no-mesh` to skip that if the project already manages its own
messenger config. It tries agent-watch-daemon's local API first (so the session is steerable from that
web app) and falls back to the plain screen launch when the daemon is not running; `--no-watch` skips
the daemon. Equivalent Python: `pi_wave_kit.interactive.launch_screen_session()` /
`is_alive()` / `hardcopy()` / `stop()` / `send_message()` / `type_into()`.

### Three ways to reach a running session, and when each is right

| | `send` (mesh DM, the default) | `type` (keystrokes) | `hardcopy` |
|---|---|---|---|
| reaches | the agent, as a message it can reason about | the pty, as if a human typed it | nothing: read-only |
| timing | at the recipient's **next tool boundary** (M2 in `docs/pi-messenger-and-subagents-tested-claims.md`) | immediately, wherever the cursor is | now |
| needs | the session joined to the mesh | only that it runs in screen (or tmux) | screen |
| proof | a `message` line in pi-messenger's `feed.jsonl` | a line in `<jobs-dir>/<name>/inject.jsonl` | the dump itself |
| risk | the message is ignored | lands mid-stream and can corrupt input if the session is not at a prompt | none |
| cost | one cheap courier call (deepseek-flash, capped at $0.05 by default) | free | free |

```bash
pi-wave-session send Home "Correction: use the 2nd edition." --workdir /path/to/project [--from Dispatcher]
pi-wave-session type Home "/compact" --if-idle        # refuses if the screen changed over 3 s
pi-wave-session hardcopy Home
```

- **`send`** (issue #15) runs a one-shot courier `pi -p` as `PI_AGENT_NAME=<--from>`, stdin closed (an open
  stdin makes `pi -p` hang), with the text quoted verbatim between markers and the instruction to send it
  unchanged. It exits 0 only if pi-messenger's own feed (`<workdir>/.pi/messenger/feed.jsonl`,
  `$PI_MESSENGER_DIR` or `~/.pi/agent/messenger/`) gets a new `message` line from the courier to the
  recipient — never on the courier's own say-so. `--workdir` must be the recipient's project directory.
- **`type`** (issue #16) hands the text over through a file (`screen readreg` + `paste`; for a tmux session
  launched by agent-watch-daemon, `load-buffer` + `paste-buffer -r`), so no character is interpreted the way
  `screen -X stuff` interprets `^X` and backslashes; Enter is a carriage return (`--no-enter` to skip).
  `--if-idle` compares two snapshots: a streaming answer changes the screen, but a session silently
  waiting on a long tool call also looks idle, so it is a heuristic, not a guarantee. The injection is
  logged to `inject.jsonl`, not to pi-messenger's feed (which belongs to that extension).
  Not yet exercised against a real `screen` (none is installed on the development machine as of
  2026-11-04); the tests use a fake `screen`.

**Why `send` became a command.** Earlier versions of this README argued that sending needed no wrapper,
since it is "just" `run_pi()` with a prompt telling a one-shot agent to use the `pi_messenger` tool. That
holds for a human reading this file front to back, not for an agent that reads `--help` only: one
concluded a live session could not be messaged at all (issue #15). The courier prompt is also
load-bearing (verbatim payload, exact peer name, closed stdin), so it now lives in one tested place.

## Further reading

- `docs/pi-messenger-and-subagents-tested-claims.md` — every tested claim about pi-messenger and
  pi-subagents this library's design rests on (delivery timing, steering, cost per extension).
- `wiki/rules/translation/pi-wave-runner.md` — how the production translation wave ran: consent flag, caps,
  timeout formula, live cost poll, stage checks, escalation, systemd unit, peak hours.
- `wiki/research/pi-money-usage-recording.md` — what each Pi extension records as cost, and why Pi's figure is
  the DeepSeek peak price.
- `wiki/research/pi-resume-and-remote-steer-live-test.md`, `pi-interactive-delegation-and-messaging-test.md`,
  `pi-subagents-and-messenger-claim-tests.md`, `pi-agent-extensions-overview.md` — the live tests behind
  resume, remote steering and the extension landscape.
- `wiki/research/coding-agents-keys-logins-and-control.md` — per-client keys, shared logins and programmatic
  control for OpenCode, Codex and Claude Code.
- `CONTRIBUTING.md` — the change process (issue first, tests with the fake `pi`, CI green).

## Status

v0.1.0 published (2026-10-26). 2026-11-04: live per-job cost cap, `kill_group`, `pi-wave-job --cap-usd`,
`pi-wave-run`, `pi-wave-session send`/`type`, rewritten `--help` texts; 171 tests passing.

**Done (issue #8, 2026-10-26):** owner directive 2026-10-26 — once `agent-watch-daemon` (a sibling
project, a laptop daemon that makes coding-agent sessions remotely monitorable/steerable from a web app)
exposes its local `127.0.0.1`-only HTTP API, `launch_screen_session()`/`pi-wave-session launch` here should
prefer it (`POST /local/create`) over the current direct `screen`/tmux invocation, falling back to today's
behavior unchanged whenever that daemon isn't running or installed. The payoff: every `pi` session launched
through this library, in any project, becomes steerable from that web app automatically, with no
caller-side changes anywhere. See `agent-watch-web`'s `ARCHITECTURE.md` ("`pi-wave-kit` becomes
steerable-by-default...") for the full spec. The library side is in place (`register_with_daemon=True` by
default, `--no-watch` to skip). The daemon's own inner `pi-wave-session launch` call has to set
`PI_WAVE_KIT_SKIP_DAEMON` to avoid a loop (the recursion guard, `interactive.DAEMON_SPAWNED_ENV_VAR`).

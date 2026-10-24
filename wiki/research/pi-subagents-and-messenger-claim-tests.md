---
type: Research Note
title: pi-subagents and pi-messenger -- claim-by-claim test results, cost-routing hazard, re-run recipes and what they mean for a 10-agent wave
description: >
  Empirical test (2026-09-25) of what the two Pi extensions claim, on pi 0.87.1, pi-subagents 0.71.0 and
  pi-messenger 0.15.2, with every agent pinned to deepseek-flash at thinking low (about $0.20 in total). Most claims
  hold; five documentation-vs-behaviour gaps, one unsafe default (crew agents default to Anthropic models), and one
  accounting hole (nested children) were found. Includes copy-paste recipes to re-run any test.
timestamp: 2026-09-25T08:39:40Z
---

# pi-subagents and pi-messenger: claim tests

Overview, landscape and decision guide: [pi-agent-extensions-overview.md](pi-agent-extensions-overview.md).
Money accounting: [pi-money-usage-recording.md](pi-money-usage-recording.md). The 10-sermon Grace to You wave
was **not** run here; it waits for the user's cost consent (see the overview's status section).

## Method

- Scratch git repos under the Claude session scratchpad (never the project repo, so this repo's CLAUDE.md was not
  loaded); project-level `.pi/settings.json` and `.pi/pi-messenger.json` pinned every role to
  `deepseek/deepseek-flash`, thinking `low` (see [cost routing](#cost-routing-hazard-and-the-keys-that-worked)).
- Evidence came from `pi -p --mode json` event streams, session JSONL, messenger registry files, crew artifacts and
  files written by the agents themselves with `date +%s.%N`, not from what a model said about itself.
- Multi-process tests used `PI_AGENT_NAME` and `PI_MESSENGER_DIR` (both read in
  [pi-messenger `index.ts`](https://github.com/nicobailon/pi-messenger/blob/main/index.ts)) so agents had fixed names
  and an isolated state dir.
- TUI-only claims were driven through a Python pseudo-terminal (tmux is not installed here).
- Only `deepseek/deepseek-flash` was used: 325 assistant messages inspected, none from any other provider.

## Results

Claims are quoted from the [pi-messenger README](https://github.com/nicobailon/pi-messenger) and the
[pi-subagents README](https://github.com/nicobailon/pi-subagents) / its
[docs](https://github.com/nicobailon/pi-subagents/tree/main/docs).

### pi-messenger

| id | claim | verdict | evidence (own measurement 2026-09-25) | gotcha |
|---|---|---|---|---|
| M1 | Agents in one folder join, see each other, with themed names, model, branch ("Discovery") | **PASS** | Alpha's `join` returned "2 peers active: Bravo, Charlie"; `whois Bravo` returned "Model: deepseek-flash, Branch: master, 3 tool calls, 20.1k tokens". Crew workers auto-joined with themed names BrightViper, HappyQuartz, WildPhoenix, SageNova | Fixed names only with `PI_AGENT_NAME`; without it names are random. Registry entries are files `<dir>/registry/<Name>.json` (pid, model, branch, reservations), deleted on exit |
| M2 | A DM wakes the recipient "immediately" as a steering prompt | **PASS** (delivery); action waits for the tool boundary | Alpha's send returned at 07:31:54.407Z; Bravo's stream shows a `custom` message `agent_message` (from Alpha, `PING-DM-for-Bravo`) at 07:31:54.457Z, 51 ms later, while Bravo was mid-loop. Bravo acted on it 4.7 s later (its `sleep 3` tool call had to finish, then one LLM turn) | "Wake" = injected at the next tool boundary, not an interrupt. A long single `bash sleep` in the recipient delays the reaction by its full length |
| M3 | Broadcast reaches all peers | **PASS** | `broadcast PING-BROADCAST-all` -> "Message sent to Bravo, Charlie"; both logged it (Bravo 1790321520.4, Charlie 1790321519.4); Charlie did **not** receive the DM addressed to Bravo | The sender's tool result says "(N messages remaining)", see M8 |
| M4 | File reservations block other agents' edits with a clear message; auto-release on leave/exit | **PASS with limits** | Blocked's `edit` and `write` on the reserved `a.txt` were refused with "Reserved by: Owner (in pi-test on master) / Reason: "m4 test" / Coordinate via pi_messenger send"; after `release`, edit succeeded within 2.25 s in the tight test (attempt 3 blocked at -1.6 s, attempt 4 passed at +2.25 s). **Bypass works:** `bash -c 'echo BYPASS-LINE >> a.txt'` returned rc 0 and changed the reserved file. `kill -9` on the holder left `Ghost.json` (with its reservation) on disk, but the next agent saw "0 peers active", edited the file successfully and the stale file was gone after its run | Reservations guard the `edit`/`write` tools only, not `bash`. One earlier run showed a blocked edit about 5.6 s after release (not reproduced in the tight test, cause not determined; loader caches for 1 s per [`store.ts`](https://github.com/nicobailon/pi-messenger/blob/main/store.ts) `AGENTS_CACHE_TTL_MS`) |
| M5 | Activity feed records edits, commits, test runs, messages | **PASS** (quirk) | Feed lines seen: `joined`, `left`, `Alpha -> Bravo: ...`, `Alpha (broadcast)`, `reserved a.txt`, `released a.txt`, `Blocked editing a.txt`, `Chatty ran tests (passed)` (from `python3 -m pytest --version`), `Committer committed` | Commit detection is the regex `/\bgit\s+commit\b/` ([`index.ts` line 702](https://github.com/nicobailon/pi-messenger/blob/main/index.ts)): `git -c user.email=.. commit` was **not** recorded, plain `git commit` was |
| M6 | Stuck detection / presence states | **NOT TESTED** | Overlay text shows a "Stuck threshold" setting; not exercised (would need an idle agent for the threshold's duration) | |
| M7 | Crew: plan -> dependency graph -> parallel waves -> automatic reviewer pass; "Workers will start automatically" | **PARTIAL** | Graph correct: task-1..3 `depends_on []`, task-4 `depends_on [1,2,3]`, `summary.txt` = 6. All roles ran `deepseek/deepseek-flash`. task-4 started (07:42:39.1) after task-3 completed (07:42:35.0). Four reviewers each returned `Verdict: SHIP`. Workers are `--mode json` subprocesses. Crew-2 with concurrency 4: four workers started within 1.68 s of each other (`start1..4.txt`), 31 s for the wave. Plan step alone took 26 s. **Auto-start did not happen**: after "Workers will start automatically" nothing ran for about 90 s until the lead called `work` itself | (a) Auto-start is only a self-prompt: on the lead's `agent_end` the extension injects a steer message asking the lead's model to call `work` ([`index.ts` ~1022-1035](https://github.com/nicobailon/pi-messenger/blob/main/index.ts)); a lead that keeps polling inside one turn never triggers it. Use `plan` with `autoWork:false`, then call `work` explicitly. (b) `concurrency.workers` set in `.pi/pi-messenger.json` was ignored (2 ran at a time, the overlay says `0/2 workers`); the crew loader reads `.pi/messenger/crew/config.json` ([`crew/utils/config.ts`](https://github.com/nicobailon/pi-messenger/blob/main/crew/utils/config.ts) line 138), README says otherwise. With it: 4 concurrent. (c) A `PI_AGENT_NAME` exported to the lead is inherited by the planner subprocess, which then failed to join ("Mesh join failed on all three attempts"); do not set it for crew runs |
| M8 | `messageBudgets` cap outgoing messages | **PASS** | 12 sends to one peer: the first 10 accepted ("(9 messages remaining)" ... "(0 messages remaining)"), the 11th and 12th rejected: "Message budget reached (10/10 for chatty level). Focus on your task." | Applies to any joined session, not only crew workers |
| M9 | Human appears as a participant; `/messenger` overlay | **PARTIAL** | pty run: `/messenger` opened an overlay titled "Messenger" with "No active plan / 0/2 workers", crew-agent list, and "You (active)"; status bar `msg: TuiUser (0 peers)` | README says `(you)`; actual text is `You (active)`. Sending chat from the overlay: PASS in a later test ([interactive test](pi-interactive-delegation-and-messaging-test.md), T6) |

### pi-subagents

| id | claim | verdict | evidence | gotcha |
|---|---|---|---|---|
| S1 | Fresh sessions expose only a `subagents_enable` loader; complexity alone does not authorize delegation | **PASS** | System prompt of every one-shot run lists `subagents_enable` and not `subagent`. A multi-file task without authorization used only `bash`/`read` (0 delegation calls). With "I explicitly authorize delegation": `subagents_enable` -> "Enabled: subagent" -> `subagent` | Every delegating prompt costs two extra turns (enable, then `list capabilities`) |
| S2 | Foreground child returns its result; isolated context | **PASS** | Parent told a secret word (`PINEAPPLE-7`) and asked a `scout` child for it: "No secret word was present anywhere in the conversation" | Child returns a long structured report unless told otherwise |
| S3 | Parallel fan-out is truly concurrent | **PASS** | Three scouts each `sleep 20`: start stamps 1790321131.308 / .698 / .857 (0.55 s spread), each ended 20.0 s later; `bg_wait` returned after 26.4 s (60 s if sequential) | Fan-out is only via `workflowScript` with `runs.all`; top-level `parallel`/`chain`/`tasks` are "not supported" per [tool-reference.md](https://github.com/nicobailon/pi-subagents/blob/main/docs/tool-reference.md) |
| S4 | Chain: sequential steps pass output forward | **PASS after one failed attempt** | `TOK586931199` produced by step 1 was used by step 2, `chain_2.txt` = `TOK586931199-B`. First attempt failed: the step-1 child ignored "reply with only the token" and returned a report, so step 2 got the whole report | Pass data between steps with `outputSchema`/`structuredOutput`, not free-text `output` |
| S5 | Background run; parent continues; later retrieval | **PASS** | `async:true` scout `sleep 25`; parent wrote its own stamp at 1790321227.716 immediately; `status` showed `State: running`; `bg_wait` returned after 27.6 s; child stamp 1790321253.418 (+25.7 s) | In `-p` mode Pi auto-drains detached children at `agent_end`, so background work is not abandoned |
| S6 | Parent steers a running child | **PASS** | Child doing 8 separate 5 s tool calls: 3 ticks (last 1790321310.11), steer queued at 09:28:30.6, child obeyed: `steer_ack.txt` = `MAGENTA-STEERED`, ticks 4-8 never ran | The plain `steer` action reports "Steering queued", not "delivered"; delivered/queued/missed receipts exist for workflow `runs.steer` ([tool-reference.md](https://github.com/nicobailon/pi-subagents/blob/main/docs/tool-reference.md#workflow-steering)). Lands at a tool boundary |
| S7 | Child asks parent via `contact_supervisor`; parent replies; supervisor messages are scoped to the spawning session | **PASS** | Child called `contact_supervisor need_decision` about 2 s after launch; `bg_wait` yielded "pending supervisor request"; `subagent_supervisor pending` listed id `cc0f219a...`; reply `BLUE` at 09:29:52; child finished 3.5 s later with `answer.txt` = `BLUE`. A second pi session in the same repo, queried while the parent was paused, returned "No pending supervisor requests." | Parent must stay alive (here: a 40 s `bash sleep`) |
| S8 | `maxSubagentSpawnsPerRun`; recursion guard | **PASS with a trap** | Cap 2, four requested: "Run fan-out limit reached at workflow[scout-3] (0/2 used; 4 requested, 2 remaining). No children from this admission group were started." Rejection is all-or-nothing. A `scout` child has exactly 7 tools (read, grep, find, ls, bash, write, contact_supervisor), no `subagent`. A project agent whose `tools` include `subagent` did spawn a nested scout (depth 2, "Run fan-out: 2/64") | `runs.all` **did not throw**: the workflow returned "completed: 4" with four result objects whose `output` is the error text. A script must check `ok` |
| S9 | `/subagents-doctor`, `subagent({action:"guide"})` | **PASS** | Doctor reported 13 builtin agents, async available, run dirs ok, fan-out limit 64, supervisor channel available, 11 skills loaded; guide returned the README | `chain-runs` dir "missing" (benign) |
| S10 | Fleet inspector; machine-readable run artifacts | **PARTIAL** | pty: `/subagents-fleet` opened "Subagent fleet inspector - no children / No current-session Fleet jobs"; async runs leave result JSON and run dirs under `/home/elvis/matlab_tmp/pi-subagents-uid-1000/` (`async-subagent-results/output-archives/<id>.json`) and per-child `session.jsonl` under `<session-dir>/<parent>/<runId>/run-0/` | Live inspection and steering a running child from the UI: PASS in a later test ([interactive test, test 2](pi-interactive-delegation-and-messaging-test.md#test-2-steering-from-subagents-fleet-and-auto-join)); stop (`D`) not tested |

Cross-cutting: the two extensions plus pi-fork loaded together without tool-name or hook conflicts in every run.
`pi -p` hangs forever if stdin is an open pipe: always add `< /dev/null` when launching from a script or agent.
A cold `pi -p` start to first answer was 1.6 s; a subagent child started about 1.8 s after launch; crew workers spawned
within about 1-2 s.

## Cost-routing hazard, and the keys that worked

Defaults that would silently spend money or fail (read from the installed packages, 2026-09-25):

| component | default model / thinking | source |
|---|---|---|
| pi-subagents builtins `scout` / `worker` / `reviewer` / `oracle` / `researcher` / `evidence-auditor` / `delegate` | no model (inherit parent); thinking low / high / high / high / medium / high / unset | `agents/*.md` frontmatter; [models.md](https://github.com/nicobailon/pi-subagents/blob/main/docs/models.md) says builtins "inherit your current Pi default model" |
| pi-subagents external-CLI agents `claude-code`, `claude-code-writer`, `codex-exec`, `codex-exec-writer` (and `cursor-agent*`) | listed as available (check mark) for the `claude` and `codex` CLIs on this machine | capability listing; they use those CLIs' own logins, not Pi's model; **never used in these tests** |
| pi-messenger crew `crew-planner`, `crew-reviewer` | `anthropic/claude-opus-4-6` | `crew/agents/*.md`, [README default table](https://github.com/nicobailon/pi-messenger#default-agent-models) |
| pi-messenger crew `crew-worker`, `crew-plan-sync` | `anthropic/claude-haiku-4-5` | same |
| Pi itself on this machine | `deepseek-v4-pro`, thinking `xhigh` | user `~/.pi/agent/settings.json` |
| pi-fork children | inherit the parent's model and thinking (result showed `deepseek-flash`) | fork tool result `model` field |

The `/messenger` overlay shows the Anthropic defaults, so they are visible before a run. Pi's auth on this machine
lists no Anthropic provider (names only were inspected, never key values), so an un-overridden crew would fail or
route unexpectedly; the outcome was not tested because the override was in place.

Keys that **worked** (project-level files in the working directory; nothing global was edited):

```json
// <cwd>/.pi/settings.json  -- pi-subagents and Pi defaults
{ "defaultProvider": "deepseek", "defaultModel": "deepseek-flash", "defaultThinkingLevel": "low",
  "subagents": { "defaultModel": "deepseek/deepseek-flash", "defaultProvider": "deepseek", "defaultThinking": "low",
    "agentOverrides": { "worker": {"model": "deepseek/deepseek-flash", "thinking": "low"},
                        "reviewer": {"model": "deepseek/deepseek-flash", "thinking": "low"},
                        "oracle": {"model": "deepseek/deepseek-flash", "thinking": "low"},
                        "scout": {"model": "deepseek/deepseek-flash", "thinking": "low"},
                        "delegate": {"model": "deepseek/deepseek-flash", "thinking": "low"} } } }
// <cwd>/.pi/pi-messenger.json  -- crew models/thinking (crew-1 had only this file and all 69 messages were deepseek-flash)
{ "crew": { "models": { "planner": "deepseek/deepseek-flash", "worker": "deepseek/deepseek-flash",
                        "reviewer": "deepseek/deepseek-flash", "analyst": "deepseek/deepseek-flash" } },
  "thinking": { "planner": "low", "worker": "low", "reviewer": "low", "analyst": "low" } }
// <cwd>/.pi/messenger/crew/config.json  -- the file the crew loader really reads for concurrency
{ "concurrency": { "workers": 4, "max": 4 }, "review": { "enabled": false } }
```

Parent process: `pi --provider deepseek --model deepseek-flash --thinking low -a` (`-a` trusts project-local
`.pi` files for the run). Thinking levels for crew roles were set but not independently verified beyond every
message being deepseek-flash.

## Money-usage recording (summary; full note linked)

Pi core, pi-fork and pi-subagents record money and match ground truth; pi-subagents' `/subagent-cost` omits nested
depth-2 children (-34 % in the test); pi-messenger records input+output tokens only and its workers leave no Pi
session file. Pi's price table is DeepSeek's peak rate at all hours. Details, the C5 table and the plan for
bridging into our telemetry DB: [pi-money-usage-recording.md](pi-money-usage-recording.md).

## Re-run recipes

```bash
# 1. one-shot, machine-readable, cost-pinned. stdin MUST be closed or -p hangs.
pi --provider deepseek --model deepseek-flash --thinking low -a --session-dir "$SD" \
   -p --mode json "<prompt>" < /dev/null > run.jsonl

# 2. read a stream: events are one JSON per line; assistant tool calls are content items of type "toolCall",
#    results are role "toolResult", usage/cost are on each assistant message (message.usage.{input,output,cacheRead,cost.total}).

# 3. messenger multi-process: fixed names + isolated state, background each process, stagger starts
PI_AGENT_NAME=Alpha PI_MESSENGER_DIR="$D" pi ... -p --mode json "<prompt>" < /dev/null > a.jsonl &
# live state while agents run: $D/registry/<Name>.json  (empty after exit -- snapshot it mid-run)
# do NOT export PI_AGENT_NAME for a crew lead (children inherit it)

# 4. slash command on a finished session (no LLM call, so free): 
pi ... --session "$SD/<stamp>_<id>.jsonl" -p --mode json "/subagent-cost"

# 5. child sessions: "$SD/<parent-stem>/<runId>/run-0/session.jsonl" (nested: run-0/session/<id>/...); crew: <cwd>/.pi/messenger/crew/artifacts/*.jsonl

# 6. kill test processes safely: a bracketed pattern cannot match its own shell
ps -eo pid,args | grep -E "[p]i --provider deepseek"     # never pkill -f "<literal that appears in your own command>"
```

TUI checks through a pty (used for the pi-fork footer, `/messenger`, `/subagents-fleet`):

```python
import os,pty,select,fcntl,termios,struct,time
pid,fd=pty.fork()
if pid==0:
    os.chdir(CWD); os.environ.update(TERM="xterm-256color",COLUMNS="140",LINES="45")
    os.execvp("pi",["pi","--provider","deepseek","--model","deepseek-flash","--thinking","low","-a"])
fcntl.ioctl(fd,termios.TIOCSWINSZ,struct.pack("HHHH",45,140,0,0))
def pump(sec):
    end=time.time()+sec
    while time.time()<end:
        if select.select([fd],[],[],0.2)[0]:
            d=os.read(fd,65536); out.write(d)
            if b"\x1b[6n" in d: os.write(fd,b"\x1b[10;10R")   # answer cursor-position query or the TUI stalls
pump(8); os.write(fd,b"/messenger\r"); pump(6); os.write(fd,b"\x1b"); pump(2)   # then strip ANSI from `out` and grep
```

Usage/cost ground truth: walk every `*.jsonl` (recursively), keep `message.role == "assistant"` with a `usage`,
dedupe on `(responseId, timestamp)` (resumed sessions replay history), and compare `usage.cost.total` with
`(input*0.30 + output*1.20 + cacheRead*0.006)/1e6` for deepseek-flash.

## What this means for a 10-agent translation wave

Measured unit costs (deepseek-flash, peak rate, all trivial tasks, so a floor):

| item | tokens | cost |
|---|---|---|
| bare turn with both extensions and pi-fork loaded ("Reply OK") | 6,325 input | $0.0019 |
| foreground scout child, 4 turns | 3.5K in / 0.9K out | $0.0022 |
| each of 3 parallel scout children | about 2.7K in / 0.95K out | about $0.0020 |
| crew-1, 4 tiny tasks (planner + 4 workers + 4 reviewers), 212 s wall (lead's first to last event) | 52.8K in / 24.0K out / 596K cache-read | $0.0482 (about $0.012 per task all-in) |
| crew-2, 4 tiny tasks, review off, 31 s wave | 33.0K in / 12.9K out / 393K cache-read | $0.0278 |

- **Overhead per agent** is 6.3K input tokens before any work, plus this repo's CLAUDE.md if the working directory is
  the repo: 21,955 bytes (about 5.5K tokens, estimate at 4 characters per token). Skills are not auto-loaded from
  `.claude/skills/`; the translation skills are 22-38 KB each (see the overview).
- **Estimate for 10 sermons (ASSUMPTION, not measured; no translation task was run):** cost = sum over calls of
  (fresh input x $0.30 + cache-read x $0.006 + output x $1.20) / 1M. If one sermon needs about 40 LLM calls, about
  150K fresh input, 1.2M cache-read and 40K output tokens, that is $0.045 + $0.007 + $0.048 = about $0.10 per sermon
  at peak, about $0.05 off-peak, so about $0.5-1 for ten with a factor-3 uncertainty either way. A one-sermon pilot
  with real logging replaces this guess with a measurement and is the recommended first step.
- **Superseded by a measurement (2026-09-25 pilot):** one real sermon (3,216 English words, 118 cues) cost $0.2419 at
  the peak rate, 2.4 times the $0.10 assumed above; a median Grace to You sermon (7,192 words) projects to about $0.49
  at peak. See [the pilot](pi-agent-extensions-overview.md#pilot-one-grace-to-you-sermon-through-a-single-pi-agent-2026-09-25).
- **Time of day matters 2x:** run outside 01:00-04:00 and 06:00-10:00 UTC Mon-Fri for DeepSeek's half price
  ([pricing page](https://api-docs.deepseek.com/quick_start/pricing)); Pi will still display the peak figure.
- **Rate limits:** no HTTP 429 or retry was seen with 4 concurrent crew workers or 3 concurrent children; behaviour at
  10 concurrent DeepSeek requests is unknown (limits not looked up).
- **Safe settings:** pin all roles as above; cap `maxSubagentSpawnsPerRun`; set crew concurrency in
  `.pi/messenger/crew/config.json`; call `work` explicitly; forbid `claude-code`/`codex-exec` agents in the prompt;
  do not rely on reservations to stop `bash` writes (give each agent its own output files instead); collect usage
  from all three places (see the money note) before the 7-day crew cleanup.
- **Not evidence of quality:** nothing here measures DeepSeek-flash French theological translation quality against
  the agent-manual output; the 50 Sproul videos were done by Claude agents.

## Not tested

M6 stuck detection; S10 stopping from the UI (live fleet inspection and steering from the UI: tested 2026-09-30,
PASS, same note as M9) (M9 sending chat from the overlay: tested
2026-09-30, PASS, see [pi-interactive-delegation-and-messaging-test.md](pi-interactive-delegation-and-messaging-test.md)); RPC `cost`
method; pi-fork forks-of-forks; `@ifi/pi-extension-subagents`, the `mjakl`/`hoangvu12` `pi-subagent` forks, Oh My Pi;
missions/schedules/watchdog/worktree isolation in pi-subagents; crew `team.*` profiles and approval gates;
crew abort grace period; DeepSeek behaviour at 10 concurrent requests; any real translation task.

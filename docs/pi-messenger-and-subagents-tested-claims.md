# Pi messenger & subagents: every tested claim this library's design rests on

This is a full, deliberately uncurated compilation of every real, tested claim about Pi's cross-agent
communication (`pi-messenger`, `pi-subagents`, `pi-fork`) that `pi-wave-kit`'s design (the coordinator
role, the escalation protocol, the wave scheduler) rests on or should be checked against. Compiled
2026-10-15 from `agentic-doc-treatement`'s wiki research notes — every claim below is sourced to a real
file and a real measured number, not a summary from memory. If you're an agent working with
`pi-wave-kit` and need to know "has X actually been tested, and what did it actually show" — this is the
file to read before assuming.

**Source files** (in `agentic-doc-treatement`'s own wiki, not duplicated verbatim here but faithfully
compiled from): `wiki/research/pi-subagents-and-messenger-claim-tests.md`,
`wiki/research/pi-interactive-delegation-and-messaging-test.md`,
`wiki/research/pi-wave-100-readiness-audit.md`, `wiki/rules/translation/pi-wave-roles.md`,
`wiki/research/pi-agent-extensions-overview.md`, `wiki/research/pi-money-usage-recording.md`, plus
corroborating entries in `wiki/log/2026-W39.md`/`2026-W40.md`/`2026-W41.md`.

## 1. pi-messenger: peer-to-peer mechanics (claim-tests M1-M9)

- **M1 — join/discovery, PASS.** Agents in one folder see each other with themed names/model/branch.
  Alpha's `join` → "2 peers active: Bravo, Charlie"; `whois Bravo` → "Model: deepseek-flash, Branch:
  master, 3 tool calls, 20.1k tokens". Crew workers auto-join with themed names (BrightViper,
  HappyQuartz, WildPhoenix, SageNova). Gotcha: fixed names only with `PI_AGENT_NAME` env var; without
  it, random names. Registry = files `<dir>/registry/<Name>.json` (pid, model, branch, reservations),
  deleted on exit.
- **M2 — DM delivery timing, PASS (delivery), with a real timing nuance.** A DM "wakes the recipient
  immediately" is **false as stated** — it's injected at the recipient's *next tool boundary*, not an
  interrupt. Measured: Alpha's send returned 07:31:54.407Z; Bravo's stream showed the message 51ms
  later while Bravo was mid-loop; Bravo acted on it 4.7s later only after its in-flight `sleep 3`
  finished. **A long single bash call in the recipient delays the reaction by its full length.**
- **M3 — broadcast, PASS.** `broadcast` reached all peers (Bravo 1790321520.4, Charlie 1790321519.4);
  the DM-only recipient (Bravo) did NOT also get a broadcast meant differently — Charlie correctly did
  not receive a DM addressed to Bravo. Sender's result shows "(N messages remaining)" — ties into M8's
  budget.
- **M4 — file reservations, PASS WITH LIMITS.** `edit`/`write` on a reserved file refused with a clear
  message ("Reserved by: Owner... Coordinate via pi_messenger send"); release→edit succeeded within
  2.25s. **Reservations do NOT block `bash`** — `bash -c 'echo BYPASS-LINE >> a.txt'` returned rc 0 and
  changed the reserved file. `kill -9` on the holder left a stale `Ghost.json`, but the next agent saw
  "0 peers active" and edited successfully — the stale lock self-cleared, didn't block forever. One
  earlier untight run showed a blocked edit ~5.6s after release (not reproduced; suspected 1s loader
  cache per `store.ts`'s `AGENTS_CACHE_TTL_MS`).
- **M5 — activity feed, PASS with a quirk.** Records joins/leaves/messages/reservations/test-runs/
  commits. **Commit detection uses regex `/\bgit\s+commit\b/`**: `git -c user.email=.. commit` was NOT
  recorded, plain `git commit` was — a real false-negative in commit tracking.
- **M6 — stuck detection, NOT TESTED.** Overlay shows a "Stuck threshold" setting but it was never
  exercised (needs an idle agent for the full threshold duration).
- **M7 — Crew (plan→dependency graph→parallel waves→reviewer), PARTIAL.** Graph correctness confirmed
  (task-1..3 no deps, task-4 depends on 1-3, final sum correct). All four reviewers returned "Verdict:
  SHIP". Crew-2 with concurrency 4: four workers started within 1.68s of each other, 31s total wave;
  plan step alone took 26s.
  - **Real bug: "Workers will start automatically" did NOT happen** — nothing ran for ~90s until the
    lead called `work` itself manually. Root cause: auto-start is only a self-prompt injected on the
    lead's `agent_end`; a lead that keeps polling inside one turn never triggers it. **Fix: use `plan`
    with `autoWork:false`, then call `work` explicitly.**
  - Second bug: `concurrency.workers` set in `.pi/pi-messenger.json` was **ignored** (only 2 ran at a
    time despite the setting) — the crew loader actually reads `.pi/messenger/crew/config.json` instead
    (the README is wrong about this); with the right file, 4 concurrent confirmed.
  - Third bug: a `PI_AGENT_NAME` exported to the lead gets inherited by the planner subprocess, which
    then fails to join ("Mesh join failed on all three attempts") — **do not set `PI_AGENT_NAME` for
    crew runs.**
- **M8 — messageBudgets cap, PASS.** 12 sends to one peer: first 10 accepted (counting down "(9
  messages remaining)"→"(0 messages remaining)"), 11th and 12th rejected: "Message budget reached
  (10/10 for chatty level). Focus on your task." Applies to any joined session, not just crew workers.
- **M9 — human-as-participant / `/messenger` overlay, PARTIAL at first, then PASS.** pty run:
  `/messenger` opened an overlay "Messenger" titled with "No active plan / 0/2 workers", crew-agent
  list, "You (active)" (the README said it'd be "(you)" — wrong text, minor doc error), status bar
  `msg: TuiUser (0 peers)`. Sending chat from the overlay was untested in this note but confirmed PASS
  in the interactive follow-up test (section 2, T6).

**Cross-cutting findings**: all three extensions (pi-subagents, pi-messenger, pi-fork) loaded together
with **zero tool-name or hook conflicts** in every run. `pi -p` **hangs forever if stdin is an open
pipe** — always redirect `< /dev/null` when launching from a script/agent. Cold `pi -p` start to first
answer: 1.6s. A subagent child started ~1.8s after launch. Crew workers spawned within ~1-2s of each
other.

## 2. pi-subagents: delegation mechanics (claim-tests S1-S10)

- **S1 — authorization gate, PASS.** Fresh sessions expose only `subagents_enable`, not `subagent`
  directly — complexity alone doesn't authorize delegation. A multi-file task with no explicit
  authorization used only `bash`/`read` (0 delegation calls). With explicit "I explicitly authorize
  delegation": `subagents_enable`→"Enabled: subagent"→`subagent` worked. **Cost note: every delegating
  prompt costs two extra turns** (enable, then list capabilities).
- **S2 — isolated child context, PASS.** Parent told a secret word (`PINEAPPLE-7`); child (a `scout`)
  asked for it reported "No secret word was present anywhere in the conversation" — confirmed real
  context isolation, not just a claim.
- **S3 — true parallel concurrency, PASS.** Three `scout` children each doing `sleep 20`: start stamps
  spread only 0.55s apart (1790321131.308/.698/.857), each ended ~20.0s later; `bg_wait` returned after
  26.4s total (would be 60s if sequential) — genuine concurrency, not sequential-disguised-as-parallel.
  Caveat: **fan-out is only via `workflowScript` with `runs.all`** — top-level `parallel`/`chain`/
  `tasks` tool actions are "not supported" per the extension's own docs.
- **S4 — sequential chain with data passing, PASS after one failed attempt.** First attempt failed:
  step-1 child ignored "reply with only the token" and returned a full report instead, so step 2
  received the whole report as its "token". Fixed by using `outputSchema`/`structuredOutput` instead of
  free-text `output` — then `TOK586931199` (step 1) correctly became `TOK586931199-B` (step 2). **Real
  lesson: never trust a child to follow a "reply with only X" instruction in free text — use structured
  output.**
- **S5 — background run / parent continues / later retrieval, PASS.** `async:true` scout doing `sleep
  25`; parent wrote its own stamp immediately (1790321227.716); `status` showed `State: running`;
  `bg_wait` returned after 27.6s; child's own stamp landed 25.7s after launch. **In `-p` (headless) mode,
  Pi auto-drains detached children at `agent_end`** — background work is not silently abandoned when
  the parent process exits.
- **S6 — steering a running child, PASS.** Child doing 8 separate 5s tool calls; steer queued at tick 3
  (09:28:30.6); child obeyed (`steer_ack.txt` = `MAGENTA-STEERED`); ticks 4-8 never ran. Note: the plain
  `steer` action only reports "Steering queued", never "delivered" — delivered/queued/missed receipts
  exist only for the `workflow runs.steer` variant. Lands at the child's next tool boundary.
- **S7 — child asks parent via `contact_supervisor`, PASS.** Child called `contact_supervisor
  need_decision` ~2s after launch; `bg_wait` yielded "pending supervisor request"; parent's
  `subagent_supervisor pending` listed the request id; parent replied `BLUE` at 09:29:52; child finished
  3.5s later with `answer.txt` = `BLUE`. **Important scoping confirmation: a SEPARATE second Pi session
  in the same repo, queried while the parent was paused, returned "No pending supervisor requests."** —
  supervisor requests are scoped to the spawning session, not global/shared across any session in the
  repo. Caveat: the parent must stay alive to answer (tested via a 40s `bash sleep` on the parent).
- **S8 — spawn cap / recursion guard, PASS WITH A TRAP.** Cap set to 2, 4 children requested: "Run
  fan-out limit reached... (0/2 used; 4 requested, 2 remaining). No children from this admission group
  were started." — **rejection is all-or-nothing**, not "start what fits." Real trap: **`runs.all` did
  NOT throw an exception** on this rejection — it returned "completed: 4" with four result objects whose
  `output` field held the error text. **A calling script MUST check each result's `ok` field, not
  assume a throw on failure.** Also confirmed: a plain `scout` child has exactly 7 tools (read, grep,
  find, ls, bash, write, contact_supervisor) — no `subagent` tool, so it cannot itself spawn a
  grandchild. A project agent explicitly given `subagent` in its tool list DID spawn a nested scout
  (depth 2, reported "Run fan-out: 2/64").
- **S9 — doctor/guide commands, PASS.** `/subagents-doctor` reported 13 builtin agents, async
  available, run dirs OK, fan-out limit 64, supervisor channel available, 11 skills loaded.
  `subagent({action:"guide"})` returned the README. Minor: `chain-runs` dir reported "missing" (called
  benign).
- **S10 — fleet inspector / machine-readable artifacts, PARTIAL (completed later).** pty:
  `/subagents-fleet` opened "Subagent fleet inspector" (correctly empty when no children). Async runs
  leave result JSON under `~/matlab_tmp/pi-subagents-uid-1000/async-subagent-results/output-archives/
  <id>.json` and per-child `session.jsonl` under `<session-dir>/<parent>/<runId>/run-0/`. Live
  inspection + steering from the UI was confirmed PASS in the interactive follow-up test below. Stopping
  via the `D` key: never tested.

## 3. The interactive-session follow-up test — the one closest to "coordinator gives orders to a worker"

This is the test most directly relevant to a real coordinator↔worker scenario. **Note the source file's
own closing section states explicitly: "Worker-to-coordinator messaging from a headless `pi -p` worker
inside a launcher worktree has not been tested either; the messaging test used a separate `pi -p`
process in the same cwd and messenger dir."** (echoed in `pi-wave-roles.md`'s own "Not verified yet"
section.) **This is a real, explicitly-named gap, not something inferred** — see section 5 below for why
it matters.

**Six main tests, all PASS:**
- **T1**: typed "authorize delegation, launch a background scout (12 ticks), don't wait" → agent called
  `subagents_enable`→`subagent list`→`subagent async`, printed LAUNCHED 6.1s later, FleetView showed
  the running child live.
- **T2**: while the child ran, an unrelated question (17×23) was answered 1.45s later, with the child's
  own ticks landing both before and after, unaffected — **the main session stays fully usable while a
  background child runs.**
- **T3**: typed "steer the running child: stop ticking, write STEERED, finish" → agent read the steer
  tool-reference doc first (one extra call), called `subagent steer`, "queued" reported; the child's
  **current** tick (already mid-`sleep`) finished, then no further ticks ran; `steer_ack.txt` =
  `STEERED`. A `subagent-notify` "Background task completed" message **woke the parent unprompted**
  8.5s later into an unrequested summary turn.
- **T4** (typing-while-busy semantics): main agent busy on `sleep 20`. A message + `Enter` (8s in) was
  injected right after the bash call finished and executed BEFORE the agent's own reply — confirming
  **`Enter` = steer at next turn boundary**. A second message + `Alt+Enter` (1.6s later) was injected
  right after the whole run ended — confirming **`Alt+Enter` = queued follow-up after the run
  completes**, matching Pi's own documented behavior.
- **T5** (cross-session DM via the agent): a separate `pi -p` process "Bravo" was running. Asking Alpha
  to DM Bravo: **first send failed — "Not registered"** (the interactive session hadn't joined the
  mesh); the agent auto-joined and retried successfully 2.7s later; Bravo received it 4.1s after Alpha's
  first attempt; **Bravo's ACK reply woke the idle Alpha session into a new, unrequested paid model
  turn.**
- **T6** (typing directly in the overlay): `/messenger` → `@Bravo HUMAN-OVERLAY-MSG` + Enter. Overlay
  showed the live feed and unread-count badge; Bravo logged the message 2.3s later; overlay confirmed
  the ACK. **No model call was spent on the sending side** for this path. Bravo's ACK again woke Alpha
  into an unrequested turn.

**Named gotchas, exact list:**
1. Interactive sessions do NOT auto-join pi-messenger by default — fixed via `autoRegisterPaths`/
   `autoRegister` (see Part A below).
2. **Every incoming DM costs a model turn on the receiver, even when idle** — pi-messenger delivers DMs
   as steering prompts with `triggerTurn: true`. "Chatty peers therefore spend money on each other."
3. Overlay messages carry only the session's name — a peer cannot distinguish "the human typed this"
   from "the agent sent this." Both render identically as `Alpha → Bravo`.
4. A background child finishing **wakes the parent** via `subagent-notify` even when the user never
   asked for a status update.
5. Steering through chat is "two hops" (ask the agent → it calls `steer`, costing an extra tool-
   reference read); steering directly from `/subagents-fleet` skips the parent model entirely (see
   Part B).

### Follow-up test, same day: steering from the Fleet inspector directly, and auto-join mechanics

**Part B — steering without the parent model being involved at all, PASS, the cleanest coordinator
pattern found:** Opening `/subagents-fleet` showed the running child live with its own transcript.
Pressing `s` opened an inline "Steer message (steer): ▌" input (default mode `steer`, Tab cycles steer/
follow_up/auto). Typing + Enter delivered as a "Supervisor" block directly into the child's own session
0.7s later, at its next tool boundary; child wrote its ack 3.0s after Enter and stopped (4 of 15 ticks
ran, no further). **Critically: the parent session made ZERO model calls for this steer** — only the
later completion notification cost it 2 turns. "This is the closest equivalent to talking to a subagent
directly: the person's text goes straight to the child, without the parent model rewording it."

**Part A — auto-join at startup, PASS, all 5 config forms tested:**

| case | config | joined? | cost |
|---|---|---|---|
| A0 (control, no config) | none | No, confirmed unjoined after 15s | $0 |
| A1 | `autoRegisterPaths: ["<abs path>/work"]` (exact match) | Yes, ~4.5s | $0 |
| A2 | `autoRegisterPaths: ["~/.../pi-itest/*"]` (tilde + wildcard-folder) | Yes, ~4.5s | $0 |
| A3 | `autoRegisterPaths: ["<abs path>/wo*"]` (prefix wildcard) | Yes, ~4.6s | $0 |
| A4 | `autoRegisterPaths: ["<abs path>/work-other"]` (non-matching) | No, confirmed unjoined after 15s | $0 |
| A5 | `autoRegister: true` | Yes, ~4.5s | $0 |

**All 5 forms behave exactly as the source code says, and joining costs literally zero model calls in
every case** (verified: 0 assistant messages for all of A0-A5). Side effect found in code (not
independently tested): `index.ts` deletes `~/.pi/agent/messenger/feed.jsonl` on every session start —
the default-directory activity feed does not survive a Pi restart.

**Cost of this whole test battery**: first run $0.02071 (Alpha 21 messages $0.01428, scout child 8
messages $0.00400, Bravo 9 messages $0.00243); follow-up test $0.01085 (Part B parent $0.00736 + scout
child $0.00349; Part A cases A0-A5 all $0, no prompts sent at all).

**Comparison vs. Claude Code** (explicit, from the source file): background subagent while chatting —
both do it. Steering a running subagent — Claude Code: ask the main session (`SendMessage`); Pi: ask the
main session OR type directly in `/subagents-fleet` with **no parent model call**, landing at the
child's next tool boundary. Typing while the main agent is busy — Claude Code yes; Pi yes (`Enter`=
steer, `Alt+Enter`=follow-up). Messaging another session — Claude Code: ask the agent (`SendMessage`);
Pi: ask the agent OR type directly in `/messenger`, but **the session must have joined the mesh first**
(fixed by `autoRegisterPaths` at startup). Cost — Claude Code: subscription; Pi: DeepSeek API per token,
billed separately, **and each received DM costs the receiver a turn** (a real, Claude-Code-dissimilar
cost mechanic).

**Explicitly NOT tested** (stated in the source file): stopping a child from `/subagents-fleet` via `D`;
`follow_up`/`auto` steer modes; `Enter`/`H` Inspect (needs a Herdr/Ghostty plugin); more than one
background child at once in the TUI; the overlay's `@all` broadcast and agent tabs.

## 4. Money/cost-recording accuracy per extension

- **Pi core**: reports cost per assistant message (`usage.cost.total`), **matches hand-recomputed
  ground truth to 1e-18** across 253 messages in 49 sessions ($0.110059 both ways). Persisted in the
  session JSONL. **Real limitation: child usage from async/background subagents does NOT appear in Pi's
  own running total** — only the parent's own tokens are counted in the footer.
- **pi-fork**: reports cost per fork + a footer line, **matches ground truth exactly** (2 forks,
  $0.001819, diff = 0). Stored inline in the parent's own session file (no separate child session
  file). Footer is UI-only — needs a real TTY (shows `forks +$0.000` in a pty run due to rounding
  display, even though the real cost was $0.000435 and the fork genuinely ran).
- **pi-subagents** (`/subagent-cost`): matches ground truth to its 4-decimal display for foreground/
  parallel/background children (e.g. $0.0070 shown vs $0.006968 real). **Real, confirmed gap: a NESTED
  (depth-2) child's cost is silently omitted** — a coordinator→scout chain showed Total $0.0036 while
  the scout's own real session file showed $0.005416 — **a 34% undercount**, and the scout's file
  exists on disk but simply isn't included in the sum.
- **pi-messenger** (crew): **reports tokens only, NOT cost** — no money figure derivable at all from its
  own `_meta.json` (which excludes cache-read tokens entirely, e.g. 18,758 reported vs the real 236,928
  cache-read tokens for that worker). **Crew workers write NO Pi session file at all** — the only place
  real crew cost exists is `<project>/.pi/messenger/crew/artifacts/*.jsonl`, with a default 7-day
  retention (`artifacts.cleanupDays`) before it's gone forever.
- **Price-table accuracy**: Pi's own catalog uses DeepSeek's **PEAK** rate, always, with no time-of-day
  awareness — confirmed by comparing Pi's `models-store.json` against DeepSeek's official pricing page.
  **Outside DeepSeek's actual peak window, Pi over-reports cost by exactly 2x.** Peak windows:
  01:00-04:00 and 06:00-10:00 UTC, Monday-Friday, excluding Chinese public holidays.
- **Existing historical spend** found already recorded in Pi's own session history (a scan predating
  these tests): deepseek-v4-pro 4,132 messages/$11.37; deepseek-flash 247 messages/$0.64; moonshotai
  kimi-k2.7-code 91 messages/$1.56; github-copilot 10,361 messages/$0.00 (**Pi records zero cost for
  subscription-billed models** — a real blind spot if Copilot usage is ever metered elsewhere).
- **Bridging into a ledger — the design principle `llm-ledger-client` already implements**: three
  sources must ALL be walked to get complete cost (parent + all nested child session files recursively;
  `toolResult.details.results[].messages` for pi-fork; crew's `artifacts/*.jsonl` copied out before the
  7-day cleanup). The right approach, and the one actually built: import tokens, never Pi's own dollar
  figure, and let the receiving ledger compute cost itself from its own pricing table as the source of
  truth — Pi's own figure is kept only as a cross-check. This is exactly `llm_ledger_client.session_ingest`'s
  design (`reported_cost_usd` kept separately, never posted as the real `cost_usd`), and exactly the
  real bug `pi-wave-kit`'s own `run_pi.py` had and fixed the same day these docs were compiled (see
  git history: "PiResult now reports real token counts, not just Pi's own cost claim").

## 5. A real cross-process data-corruption incident, not just a messaging claim

From the original wiki (dated 2026-10-03): **"a worker once transposed two digits and excluded 5 chunks
of a different video before noticing."** This is the real incident that led the original launcher to
pass a scoping environment variable to every worker, with every telemetry write refusing to touch any
ID other than the one it was explicitly told about — so a mistyped/transposed ID fails loudly instead of
silently corrupting a different work item's data. **This is the direct, real precedent for why any
multi-agent wave sharing one checkout needs this exact kind of scoping guard** — not implemented inside
`pi_wave_kit` itself (it has no concept of "chunk stages"), but worth building into any concrete usage of
this library that shares file/DB state across concurrent workers.

## 6. The ten-sermon production wave — real numbers at scale

Not a toy test — a real production run. Ten Pi agents (`deepseek-flash`, thinking low), one job each,
five concurrent at a time, hard caps $1.00/agent and $5.00 total wave, off-peak hours.

- **Total real cost: $1.4948** (well under the $5 cap and under the pre-run low-end projection of
  $1.98). Per-agent range $0.1168-$0.1915, mean $0.1495.
- **Zero HTTP 429/rate-limit/timeout errors** across all ten concurrent-capable agents; 20 tool-result
  errors total across 994 tool calls, all self-recovered by the agents (max 4 in any one agent).
- Cache-read share of prompt tokens: 98.6%-99.3%.
- **Five concurrent agents was the actual tested ceiling — ten concurrent was deliberately never
  tried** ("capped at five by choice"). Nobody has confirmed what happens at 10 simultaneous DeepSeek
  requests from this account.
- Telemetry cross-check: launcher-imported totals ($1.494786 over 876 LLMCall rows) matched an
  independent hand-recompute to the cent; re-running the importer on every session inserted 0 duplicate
  rows.

## 7. The settled design, and its own stated caveat about what's actually proven

The two-role design (one interactive coordinator; up to 10 headless workers; code does the mechanical
steps around each worker) was, as of its own writing, explicitly flagged as **agreed but not yet
pressure-tested against a real wave**: the interfaces for the escalation protocol and stage-check
framework were "being built in parallel when this was written." **Worker-to-coordinator messaging from
a real headless `pi -p` worker inside an actual launcher-spawned, isolated working directory has never
been tested — only a separate `pi -p` process in the same cwd/messenger dir was tested** (sections 1-3
above), which is a materially different scenario from a worker spawned inside its own isolated worktree
by a real launcher.

**This is the one gap `pi-wave-kit`'s own live test (2026-10-15, real money, section 8 below) was
specifically designed to close**: everything in sections 1-3 proves pi_messenger/subagents work in a
*standalone* multi-process test harness; nothing in the original wiki proves it inside the real
worktree-isolated, launcher-spawned production shape this library's `wave.py` actually creates.

## 8. CLOSED: real test, isolated-directory coordinator → worker, real money (2026-10-15)

**Setup** (simulating a real launcher's worktree isolation, not a shared cwd like every test in
sections 1-3): two completely separate directories
(`worker/` and `coordinator/`), each its own `.pi/pi-messenger.json` (`{"autoRegister": true,
"scopeToFolder": false}`), both pointed at one shared `PI_MESSENGER_DIR` env var — the exact mechanism
`pi-wave-runner.md` describes the real launcher using, confirmed here working end to end for the first
time.

**Worker**: a real headless `pi -p` process (`deepseek-flash`, low thinking, `PI_AGENT_NAME=worker-1`),
prompted to run three separate 8-second `sleep` calls in sequence, checking after each one whether a
peer message had arrived, and to obey immediately and stop early if one did.

**Coordinator**: a SEPARATE real headless `pi -p` process (`deepseek-flash`, low thinking,
`PI_AGENT_NAME=coordinator-1`), launched ~3 seconds after the worker, prompted to join the mesh, confirm
`worker-1` as an active peer, and send it a specific order via `pi_messenger`.

**Result: PASS, verified independently of either agent's own self-report.** The coordinator reported
"2 agents online... worker-1 confirmed as an active peer... send succeeded." Rather than trusting that
claim, the worker's own `result.txt` was read directly afterward: it contained exactly
`ORDER-RECEIVED-42` — the literal string the coordinator's order specified, which the worker's own
original task never would have produced on its own (its fallback instruction for "no message received"
was a different, longer string). The worker's own transcript confirms genuine mid-task interruption, not
a lucky coincidence at the end: **"Received peer message after sleep #2. Stopped immediately and
obeyed it."** — it was interrupted after the second of three sleeps, not after finishing all three.

**One real NEW finding, not in any prior wiki note**: the worker's own transcript also says **"Reply to
coordinator-1 failed (`not found`), but the instruction was carried out."** The forward direction
(coordinator → isolated-directory worker) works correctly end to end; the worker's attempt to reply
BACK to the coordinator failed with a "not found" error. This is a real, confirmed asymmetry worth
flagging for anyone building an escalation/acknowledgement protocol on top of raw `pi_messenger` sends
between isolated-directory agents — a one-way order delivered correctly; a same-direction-reversed ACK
did not, at least in this exact configuration. Not yet root-caused (possibly a registry/scoping detail
specific to which directory a reply resolves against); a real open question for anyone depending on
bidirectional isolated-directory messaging.

**Real cost: $0.0046** (worker $0.002526, coordinator $0.002075) — both read directly from each
process's own session file via `llm_ledger_client.session_ingest.read_usage()`, not estimated.

**What this settles**: the core claim `pi-wave-kit`'s coordinator/escalation design depends on — that a
real launcher-spawned worker in its own isolated directory can receive and act on a live message from a
separate coordinator process — is now confirmed true, for the forward direction, with real money, not
merely assumed from the standalone same-directory tests in sections 1-3. The reply-back asymmetry means
a design that needs the WORKER to reliably message the coordinator (rather than just escalating via a
file, which `pi_wave_kit.escalate` already does and does not depend on this) should not yet assume that
path works without its own direct test.

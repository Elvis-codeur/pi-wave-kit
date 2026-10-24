---
type: Research Note
title: Pi interactive session -- background subagent while chatting, steering it, queued messages, and cross-session messaging (human and agent)
description: >
  Test (2026-09-30) of whether a person working in an interactive Pi terminal session can do what they do in Claude
  Code: send a subagent off in the background, keep talking to the main session, steer the running child, and send
  messages to another session (asking the agent to, or typing directly in the /messenger overlay). All six steps
  passed on pi 0.87.1 with deepseek-flash at thinking low; total $0.0207 at Pi's (peak-rate) price. A second run the
  same day added steering a child directly from /subagents-fleet (PASS, no parent model call) and pi-messenger
  auto-join via autoRegisterPaths/autoRegister (all four forms PASS, zero model calls); $0.0109 more.
timestamp: 2026-09-30T11:39:07Z
---

# Pi interactive session: delegation and messaging test

Follow-up to [pi-subagents-and-messenger-claim-tests.md](pi-subagents-and-messenger-claim-tests.md). That note tested
the claims mostly in one-shot `pi -p` mode. This note covers the question it left open: whether a person
typing in an **interactive** Pi TUI can use these features the way they would in Claude Code. The scenario and the
user's go-ahead for the DeepSeek spend (a few cents) are from the conversation of 2026-09-30.

## Answer

Yes, on every point tested ([results](#results)):

- **Background child while you keep chatting:** the main session answered an unrelated question 1.5 s after it was
  typed while the child kept running. A live FleetView below the editor shows the running child.
- **Steering the child from the chat:** you ask the main session, and it calls `subagent` `steer`. The child
  stopped after its in-flight tick.
- **Steering the child yourself, from `/subagents-fleet`:** open the inspector, press `s`, type the message, press
  Enter. The child received it 0.7 s later, at its next tool boundary, and the parent's model made **no call** for
  it ([test 2](#test-2-steering-from-subagents-fleet-and-auto-join)).
- **Typing while the main agent itself is busy:** `Enter` queues a steering message (delivered after the current tool
  call finishes). `Alt+Enter` queues a follow-up (delivered after the whole run ends). The observed order matches
  Pi's [usage.md](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/usage.md) (installed copy:
  `@earendil-works/pi-coding-agent/docs/usage.md`, lines 36-40).
- **Another session, through the agent:** "send X to Bravo" works, but by default the interactive session is **not
  joined to the mesh**. The first `send` failed with "Not registered", and the agent joined and retried on its own.
  Setting `autoRegisterPaths` (or `autoRegister: true`) in `.pi/pi-messenger.json` makes it join at startup with no
  model call ([test 2](#test-2-steering-from-subagents-fleet-and-auto-join)).
- **Another session, typed by you:** `/messenger` then `@Bravo text` + Enter delivered in 2.3 s with no model call on
  the sending side. The peer sees it as coming from the session's name (`Alpha`), not from a separate human
  identity.

## Method

- Scratch git repo in the Claude session scratchpad, not this repo, so this repo's CLAUDE.md was not loaded.
  Project-level `.pi/settings.json` and `.pi/pi-messenger.json` pinned every role to `deepseek/deepseek-flash`,
  thinking `low`, with the same keys as in the
  [claim-test note](pi-subagents-and-messenger-claim-tests.md#cost-routing-hazard-and-the-keys-that-worked).
- **Alpha**: a real interactive `pi --provider deepseek --model deepseek-flash --thinking low -a --session-dir ...`,
  started under a Python pseudo-terminal (160x50) with `PI_AGENT_NAME=Alpha` and an isolated `PI_MESSENGER_DIR`. A
  driver script typed the prompts character by character, as a person would, and rendered the screen with `pyte`
  for snapshots. `Enter` = `\r`, `Alt+Enter` = `\x1b\r`, answering the TUI's cursor-position query `\x1b[6n` as in the
  [pty recipe](pi-subagents-and-messenger-claim-tests.md#re-run-recipes).
- **Bravo**: a second, separate `pi -p --mode json` process (same cwd and messenger dir, `PI_AGENT_NAME=Bravo`),
  told to join the mesh, idle in `sleep 4` bash calls, log every message received to `bravo_inbox.txt` and reply
  `ACK-<text>`.
- Evidence: files the agents wrote with `date +%s.%N`, the driver's own `time.time()` log of each keystroke batch,
  and the Pi session JSONL files (parent, child `run-0/session.jsonl`, Bravo). No claim below rests on what a model
  said about itself.
- A kill switch stopped the run above $0.50. It was not hit.

## Results

All times are UTC on 2026-09-30, from the session JSONL or `date +%s.%N` stamps (own measurement).

| # | what the person did | what happened | verdict |
|---|---|---|---|
| T1 | Typed: authorize delegation, launch ONE `scout` in the background (12 ticks of `sleep 5; date >> ticks.txt`), don't wait, reply LAUNCHED | Typed 11:35:57.7. Agent called `subagents_enable`, `subagent list`, then `subagent` with `async`. It printed `LAUNCHED` at 11:36:03.8 (6.1 s) and the prompt came back. First tick 11:36:11.7. A FleetView under the editor showed `scout [fresh] · running (deepseek-flash · thinking low) · 2 turns · 2 tool uses` with the child's current bash call, plus `1 active agent` | **PASS** |
| T2 | While the child ran, typed an unrelated question (17*23, write `main_stamp.txt`) | Typed 11:36:16.8; `main_stamp.txt` stamped 11:36:18.2 (1.45 s); answer "391" at 11:36:19.4. Child ticks landed at 11:36:18.5 and 11:36:25.5, before and after, unaffected | **PASS**: the main session is fully usable while a background child runs |
| T3 | Typed: "steer the running background child: stop ticking, write STEERED to steer_ack.txt, finish" | Agent first read `subagent guide tool-reference` (one extra call), then `subagent {action: steer, id: 14b70bf4...}` at 11:36:31.0 and reported "queued". Tick 4 (already mid-`sleep 5`) finished at 11:36:32.6. No tick 5-12, `steer_ack.txt` = `STEERED`, no `child_done.txt`. At 11:36:41.1 a `subagent-notify` "Background task completed" message woke the parent, which summarised the result unprompted | **PASS**: lands at the child's next tool boundary, as in the one-shot test (S6) |
| T4 | Main agent busy on `sleep 20` (bash started 11:36:46.4). 8 s later typed a message + `Enter`; 1.6 s after that, another + `Alt+Enter` | `long.txt` 11:37:06.40. The `Enter` message was injected into the same run at 11:37:06.41, right after the bash result, and executed at 11:37:07.86, **before** the reply `LONG-DONE` (11:37:09.22). The `Alt+Enter` message was injected at 11:37:09.23, right after the run ended, and executed at 11:37:10.45 | **PASS**: `Enter` = steer at the next turn boundary, `Alt+Enter` = follow-up after the run |
| T5 | Bravo started as a separate process. Typed in Alpha: "use pi_messenger to send a DM to Bravo: HELLO-FROM-ALPHA-TUI" | Bravo registered 3 s after launch. The registry then held only `Bravo.json`: **Alpha, the interactive session, had not joined**. Alpha's first `send` (11:37:23.8) returned "Not registered. Use pi_messenger({ action: "join" }) ...". The agent called `join` ("Joined as Alpha ... Active peers: Bravo") and resent at 11:37:26.5. Bravo logged it at 11:37:30.6 (4.1 s, Bravo was in a `sleep 4`). Bravo's `ACK-...` reached Alpha at 11:37:30.65, which **woke the idle Alpha session into a new model turn** (11:37:32.5) | **PASS**, with the join caveat |
| T6 | Typed `/messenger`, then `@Bravo HUMAN-OVERLAY-MSG` + Enter in the overlay's chat input | Overlay showed the feed (`Alpha joined`, `Alpha → Bravo ...`, `Bravo → Alpha ...`), the key help `m:Chat v:chatty +/-:Wkrs Esc:Close`, and status `msg: Alpha (1 peer) ●1` (one unread). Typed 11:37:46.0; Bravo logged `Alpha: HUMAN-OVERLAY-MSG` at 11:37:48.2 (2.3 s). The overlay confirmed `✓ Bravo — ACK-HUMAN-OVERLAY-MSG`. Bravo's ACK again woke Alpha into a model turn (11:37:49.4), with the overlay still open | **PASS**. Closes M9's untested part in the [claim-test note](pi-subagents-and-messenger-claim-tests.md#pi-messenger) |

### Gotchas found

- **The interactive session does not auto-join pi-messenger by default.** Peers cannot see or message it until it
  joins, either when the agent calls `join` or at startup via `autoRegisterPaths`/`autoRegister` (fix verified in
  [test 2](#test-2-steering-from-subagents-fleet-and-auto-join)). The overlay itself works once joined.
- **Every incoming DM costs a model turn on the receiver, even when it is idle.** Pi-messenger delivers messages as
  steering prompts with `triggerTurn: true`
  ([README "How it works"](https://github.com/nicobailon/pi-messenger#how-it-works)). Two ACKs gave two unrequested
  Alpha turns. Chatty peers therefore spend money on each other.
- **Overlay messages carry the session's name.** A peer cannot tell "the person typed this" from "the agent sent
  this". Both show as `Alpha → Bravo`.
- **A background child finishing wakes the parent.** The `subagent-notify` message triggered a turn in the
  interactive session without the user asking (11:36:41-43).
- **Steering through the chat is two hops.** You ask the main agent, and it calls `steer`. Here it spent one extra
  call reading the guide first. Steering from `/subagents-fleet` skips the parent model entirely
  ([test 2](#test-2-steering-from-subagents-fleet-and-auto-join)).

## Test 2: steering from /subagents-fleet, and auto-join

Run 2026-09-30 11:49-11:52 UTC on the user's follow-up request. Same scratch repo, same pinned
deepseek-flash/low settings and the same pty + `pyte` driver as above. A fresh messenger dir was used for the join
cases.

### B: steering a background child directly from the fleet inspector

Keys come from pi-subagents'
[observability.md, "The fleet inspector"](https://github.com/nicobailon/pi-subagents/blob/main/docs/observability.md#the-fleet-inspector):
`s` composes "an acknowledged message to a selected live async child", and Tab cycles `steer` / `follow_up` / `auto`.

| step | what happened (own measurement; session JSONL and `date +%s.%N` stamps) |
|---|---|
| launch | Prompt as in T1 (15 ticks). The agent called `subagents_enable`, `subagent list`, `subagent` async, then printed `LAUNCHED` at 11:51:16.1 |
| open | Typed `/subagents-fleet`. The inspector titled "Subagent fleet inspector · live controls" listed `● scout [fresh] · ef251dfd running`, preselected, with its live bash transcript and the key bar `↑/k/↓/j agent · p Prompt Audit · Enter/H Inspect · s steer · D stop · x/X/ctrl+o tools · r/R refresh · Esc/ctrl+c/q close` |
| `s` | An input line appeared inside the inspector: `Steer message (steer): ▌` with the hint `Enter sends · Tab changes mode · Esc cancels · Backspace edits`. The default mode is `steer` |
| send | Typed the message + Enter at 11:51:40.95. The inspector's transcript showed a `◇ Supervisor` block: "Mid-run steering from the parent orchestrator: STOP ticking now ... Incorporate this guidance at the next safe point. Do not restart the task unless the guidance explicitly asks you to." |
| child | Tick 4 finished at 11:51:41.646. The steer entered the child's session as a user message at 11:51:41.651 (0.7 s after Enter, at the next tool boundary). The child wrote `fleet_ack.txt` = `FLEET-STEERED` at 11:51:43.9 (3.0 s after Enter) and finished. `ticks.txt` stayed at 4 of 15; no `child_done.txt` |
| parent | **No parent model call for the steer**: the parent session had 4 assistant messages before Enter and no new one until the child's completion. At 11:51:48.7 a `subagent-notify` "Background task completed" woke the parent. It ran two `bash` checks and a summary on its own (2 more assistant messages, not asked for) |

Verdict: **PASS**. This is the closest equivalent to talking to a subagent directly: the person's text goes straight
to the child, without the parent model rewording it.

### A: pi-messenger auto-join at startup

What the code does (read from the installed `pi-messenger` package, not tested separately):
- `index.ts` joins at session start when `config.autoRegister || matchesAutoRegisterPath(cwd, autoRegisterPaths)`.
- `config.ts` `matchesAutoRegisterPath` supports three pattern forms: an exact path, a trailing `/*` (that folder or
  any subfolder), and a trailing `*` (string prefix). It expands `~`.
- The project `.pi/pi-messenger.json` overrides `~/.pi/agent/pi-messenger.json`, which overrides the `"messenger"` key
  in `settings.json`
  ([README, "Configuration"](https://github.com/nicobailon/pi-messenger#configuration)).

Each case started a fresh interactive Pi in `<scratch>/work` with only the project file changed. No prompt was typed.

| case | project `.pi/pi-messenger.json` | joined? (registry file `Alpha.json`, status bar) | assistant messages |
|---|---|---|---|
| A0 | no auto-join keys (control) | no, after 15 s | 0 |
| A1 | `"autoRegisterPaths": ["<abs path>/work"]` (exact) | yes, about 4.5 s after start; `msg: Alpha (0 peers)` | 0 |
| A2 | `"autoRegisterPaths": ["~/matlab_tmp/.../pi-itest/*"]` (tilde + `/*`) | yes, about 4.5 s | 0 |
| A3 | `"autoRegisterPaths": ["<abs path>/wo*"]` (prefix `*`) | yes, about 4.6 s | 0 |
| A4 | `"autoRegisterPaths": ["<abs path>/work-other"]` (non-matching) | no, after 15 s | 0 |
| A5 | `"autoRegister": true` | yes, about 4.5 s | 0 |

Verdict: **PASS**, all forms behave as the code says. Joining is free: no model call happened at startup in any
case. To make every interactive session in a folder tree reachable by peers, put `"autoRegisterPaths":
["~/path/to/tree/*"]` in `~/.pi/agent/pi-messenger.json`. For a single project, put it in that project's
`.pi/pi-messenger.json`. Once joined, incoming DMs wake the session into a paid turn (see gotchas above), so
auto-join everywhere also means paying for every message peers send it.

A side effect seen in the code, not tested: `index.ts` (around line 850) deletes `~/.pi/agent/messenger/feed.jsonl`
on every session start, so the default-dir activity feed does not survive a Pi restart.

### Test 2 cost

| session | cost (Pi's figure) |
|---|---|
| A0-A5 (no prompts; no session file was even written) | $0 |
| B parent | $0.00736 |
| B scout child (`*_scout_meta.json`: $0.003495, 7 turns) | $0.00349 |
| **total** | **$0.01085** |

## Cost (first run)

From the session JSONL files, assistant messages with `usage` (own measurement):

| session | assistant messages | model | cost (Pi's figure) |
|---|---|---|---|
| Alpha (interactive parent) | 21 | deepseek/deepseek-flash | $0.01428 |
| scout child (`run-0/session.jsonl`; `subagent-artifacts/*_scout_meta.json` agrees: $0.003998, 8 turns) | 8 | deepseek/deepseek-flash | $0.00400 |
| Bravo | 9 | deepseek/deepseek-flash | $0.00243 |
| **total** | 38 | only deepseek-flash seen | **$0.02071** |

- Pi prices DeepSeek at the peak rate at all hours
  ([money note](pi-money-usage-recording.md#c1-is-pis-own-number-right)). This run was at 11:35-11:38 UTC, outside
  the peak windows listed in the [claim-test note](pi-subagents-and-messenger-claim-tests.md#what-this-means-for-a-10-agent-translation-wave).
  If DeepSeek applied its off-peak price, the actual charge is about half. That is an inference from the pricing
  page, not checked against a DeepSeek bill.
- `subagent-artifacts/*_scout_transcript.jsonl` repeats the child's messages (same per-message cost, e.g. the first
  at $0.0010015). Counting it together with `run-0/session.jsonl` double-counts the child.
- The driver's in-run kill-switch sum printed $0.04398. That figure is wrong (too high): its glob also walked
  `~/matlab_tmp/pi-subagents-uid-1000/`, which holds older runs' files. The table above is the correct figure.
- None of this reaches our telemetry DB; see the bridge assessment in the
  [money note](pi-money-usage-recording.md#c6-getting-pi-agent-costs-into-our-telemetry-assessment-only-nothing-implemented).

## How this compares to Claude Code (this session)

| | Claude Code | Pi + pi-subagents + pi-messenger (this test) |
|---|---|---|
| background subagent while you keep talking | yes (Agent tool, background) | yes (T1, T2) |
| steer a running subagent | ask the main session (`SendMessage`) | ask the main session (`subagent steer`, T3), **or type it yourself** in `/subagents-fleet` → `s` (test 2, no parent model call); lands at the child's next tool boundary |
| type while the main agent is busy | yes | yes: `Enter` = steer, `Alt+Enter` = follow-up (T4) |
| message another session | ask the agent (`SendMessage`) | ask the agent (`pi_messenger send`, T5) **or type it yourself** in `/messenger` (T6); the session must have joined first (`autoRegisterPaths` does it at startup, test 2) |
| cost | Claude subscription | DeepSeek API per token, billed separately; each received DM costs a turn |

## Re-running

The driver was a throwaway script in the session scratchpad (not kept). To rebuild it, combine:

- the pty loop from the [claim-test recipes](pi-subagents-and-messenger-claim-tests.md#re-run-recipes);
- `pyte.Screen(160, 50)` + `pyte.ByteStream` fed every byte read, then `"\n".join(screen.display)` for snapshots
  (`uv run --no-project --with pyte python drive.py`);
- keystrokes written one byte at a time with ~4 ms spacing, then `\r` (Enter) or `\x1b\r` (Alt+Enter);
- step completion detected from files the agents write (not from screen text), each with a timeout;
- Bravo as a `subprocess.Popen` of `pi ... -p --mode json "<prompt>"` with `stdin=DEVNULL` and
  `PI_AGENT_NAME=Bravo`, and the same `PI_MESSENGER_DIR` as Alpha;
- a cost kill switch that sums `usage.cost.total` only under the run's own `--session-dir`.

## Not tested

Stopping a child from `/subagents-fleet` (`D`); the `follow_up`/`auto` steer modes; `Enter`/`H` Inspect (needs a
Herdr or Ghostty plugin per observability.md, neither present here); a child asking the
interactive parent via `contact_supervisor` (tested only in one-shot mode, S7); more than one background child at
once in the TUI; the overlay's `@all` broadcast and agent tabs.

---
type: Research Note
title: Resuming a closed pi session headlessly, and remote-steering an already-running one -- both re-verified live
description: >
  Owner's question (2026-10-24): can a closed interactive session be picked up headlessly later, and can an
  already-running session be attached to/steered from elsewhere? Both tested directly rather than assumed from
  earlier notes. Part A (resume): confirmed, wired into pi_wave_kit as resume_pi_headless(). Part B (remote steer):
  confirmed, but only under a real, named constraint (screen + pi-messenger autoRegister); wired into
  pi_wave_kit.interactive for the launch/inspect/stop side. Total spend: about $0.03 across both tests.
timestamp: 2026-10-24T23:15:00Z
---

# Resuming and remote-steering a pi session: re-verified live

This repo (`pi-wave-kit`) already had `pi-subagents`/`pi-messenger` research copied in from
`agentic-doc-treatement`'s wiki ([pi-interactive-delegation-and-messaging-test.md](pi-interactive-delegation-and-messaging-test.md),
[pi-agent-extensions-overview.md](pi-agent-extensions-overview.md)) and the `pi -p` / `screen` finding from
`pi-gatekeeper`'s own README. The owner asked for both questions below to be tested directly rather than assumed
from those existing notes, since the scenario (someone away from the keyboard, talking to Claude instead) is new.

## Part A: resume a CLOSED session headlessly

**Question:** open an interactive session, work in it, close it. Later, pick that same session's state back up
and continue in headless mode (`pi -p`), not fresh.

**Method:** `pi -p --session-dir sessions --session-id resume-test-1 "Remember this secret codeword for later:
ZEBRA-9183. ..."`, which exited cleanly after one turn (a genuinely closed session, not kept alive). Then, in a
**separate, later process**, `pi -p --session-dir sessions --session-id resume-test-1 "What was the secret
codeword I told you earlier?"` -- and separately, `pi -p --session <the .jsonl file path> "One more time, what was
the codeword?"`.

**Result: PASS, both forms.** Both resumed processes answered `ZEBRA-9183` correctly -- the prior, closed session's
context was really there, not just a command that didn't error. deepseek-flash, thinking low; total cost for this
test was a few tenths of a cent.

**Wired in:** `pi_wave_kit.run_pi.resume_pi_headless()`. The one real wrinkle: `start_pi`/`collect_pi_result`'s
cost-reading diffs which session files are NEW in a directory, and resuming APPENDS to a file that already
existed, so that diff would see zero new files and silently report $0 -- so `resume_pi_headless` diffs by
usage-record COUNT in the one known file (before the call vs. after) instead. Re-verified with the real installed
library against the real `pi` binary (not just the unit tests' fake): a codeword survived two separate resumes of
the same session file.

## Part B: attach to / steer an ALREADY-RUNNING session

**Question:** open an interactive session somewhere (e.g. at home, left running), then later, from elsewhere,
control/message that still-live session.

**What was checked first** (reading, not re-testing): `pi-gatekeeper`'s README already states, from its own live
test, that `pi -p` has no "stay alive, idle" state and that a backgrounded interactive session with no real pty
dies on EOF after one turn -- `screen` is what it uses to keep a session alive and attachable. `tmux` is not
installed on this machine; `screen` is.

**What was newly tested here** (not just trusted from the note): a real interactive `pi` session was launched
under `screen -dmS`, in a scratch project with `.pi/pi-messenger.json` set to `{"autoRegister": true}`, given an
initial instruction (remember a codeword, ACK any incoming message with it) and left idling. A **separate**
one-shot `pi -p` process (standing in for "a request from elsewhere") was told to use the `pi_messenger` tool to
send that live session a DM. Evidence checked: pi-messenger's own `feed.jsonl` (a real file, not either agent's
self-report) and `screen -X hardcopy` on the live session.

```
{"ts":"...09:44.013Z","type":"message","agent":"Bravo","target":"Alpha","preview":"PING-FROM-BRAVO"}
{"ts":"...09:45.325Z","type":"message","agent":"Alpha","target":"Bravo","preview":"ACK-WOMBAT-42-PING-FROM-BRAVO"}
```

**Result: PASS, with a real constraint.** The live, already-running interactive session received the DM and
replied correctly (using context -- the codeword -- established before the sender even existed) 1.3 seconds
later. This reproduces the 2026-09-30 finding in
[pi-interactive-delegation-and-messaging-test.md](pi-interactive-delegation-and-messaging-test.md) independently,
rather than just citing it.

**The constraint, stated plainly, not papered over:**

- There is **no way to message an arbitrary already-running `pi` session from outside `pi` at all.** pi-messenger's
  npm package ships no sending CLI -- its only `bin` entry (`install.mjs`) is an installer, confirmed by reading the
  package's own `package.json`. The sender must itself be another `pi` agent process calling the `pi_messenger`
  tool. A plain script, `curl`, or anything that isn't `pi` cannot reach it this way.
- The **target** session is reachable at all only if it (1) runs under a real pty (`screen`/`tmux` -- this
  machine has only `screen`) and (2) has joined the pi-messenger mesh (`autoRegister`, or an explicit `join`).
- **So: the owner must always launch an interactive session this specific way (screen + autoRegister already
  configured) for remote control to be possible at all.** A session started by typing `pi` directly in a normal
  terminal, with no messenger auto-join, is not remotely reachable, no matter how it's running. This is a real,
  meaningful limitation to plan around, not an implementation detail to fix later.
- A secondary finding from the same run: when both sides keep auto-replying to incoming DMs (pi-messenger wakes
  the receiver into a paid turn on every message, per the earlier note), a ping-pong loop can run up a few extra
  turns before one side decides to stop -- worth a deliberate "don't reply to acks" instruction in any real
  deployment of this pattern, not left to the model's own judgment.
- Also seen: if the SENDER process exits right after sending (a one-shot `pi -p`), a reply addressed back to it
  can fail with "(not found)" -- the sender has already left the mesh. Fine for a fire-and-forget DM; a real
  back-and-forth needs the sender to also stay alive (another `screen` session, or a loop of one-shot sends).

**Wired in:** `pi_wave_kit.interactive` (`launch_screen_session`, `is_alive`, `hardcopy`, `stop`) for the
launch/inspect/stop side of a long-lived target session. The **sending** side needed no new wrapper code: it is
just `pi_wave_kit.run_pi.run_pi()` with a prompt instructing the one-shot agent to use `pi_messenger` -- the
message-sending capability already exists in this library as "spawn a pi agent with a prompt", because that's
genuinely what sending requires.

**A real bug found by the required manual smoke test, not by the unit tests** (which use a fake `screen`): the
real `screen -X hardcopy` output is not guaranteed valid UTF-8 (hit a real `0x91` byte at a fixed offset, a
box-drawing/terminal-control byte, not a transient glitch) -- `hardcopy()` now reads with `errors="replace"`.
This is exactly why this project's own CONTRIBUTING.md requires a manual smoke test against the real thing before
calling a process-spawning wrapper done: the fake-binary unit tests all passed with this bug still in the code.

## Total cost

Both tests combined (Part A's two tiny resumes, Part B's Alpha/Bravo exchange, plus the later real smoke test of
the finished `pi_wave_kit.interactive` code): about $0.03, deepseek-flash at thinking low throughout, read from
each session's own `usage.cost.total` fields (Pi's own figure, evidence only, never the real recorded cost per
this project family's own rule).

---
type: Research Note
title: Pi coding agent extensions for sub-agents and agent messaging -- landscape, how Pi is set up on this machine, and when to use which for this repo
description: >
  Which Pi extensions give Pi agents that can be delegated to, steered, asked questions and messaged (as Claude Code
  has), which of them were tested on 2026-09-25, how Pi is configured here (deepseek-flash at low thinking chosen by
  the user), a decision guide versus Claude Code's own Agent tool for this repo's translation pipeline, and the
  result of a one-sermon translation pilot through a single Pi agent (2026-09-25: $0.24 at peak rate, quality close
  to the agent-manual method after 13 reviewer fixes). The 10-sermon wave then ran the same day: $1.4948 off-peak, all ten accepted after review (see the wave results section).
timestamp: 2026-09-25T08:39:40Z
---

# Pi agent extensions: landscape, setup, decision guide

Question (user, 2026-09-25): "search for the pi extensions which enable pi to have agents like you have, agents with
which communication can be made", then install, test their claims, and send a wave of agents to translate 10 Grace
to You sermons. Companion notes: [claim tests](pi-subagents-and-messenger-claim-tests.md) (what held up, how to
re-run), [money-usage recording](pi-money-usage-recording.md) (what each component reports as cost).

## Landscape (web search 2026-09-25; star counts and licences from the repo pages)

Pi core ships four tools by default (read, write, edit, bash) per the
[pi-mono repository](https://github.com/badlogic/pi-mono) (the project is now hosted as
[earendil-works/pi](https://github.com/earendil-works/pi); search results list both URLs), and has no spawn/task tool
of its own: the [extension docs](https://github.com/badlogic/pi-mono/blob/main/packages/coding-agent/docs/extensions.md)
and example folder show subagents as an extension. Own check: the system prompt of a bare Pi run here lists
`read, bash, edit, write` plus only the tools the installed extensions add.

| extension | what it gives | licence / stars | tested here? |
|---|---|---|---|
| [pi-subagents](https://github.com/nicobailon/pi-subagents) (nicobailon) 0.71.0 | Delegation to child agents: foreground, background, parallel and chained via `workflowScript`; builtin `scout`, `researcher`, `evidence-auditor`, `worker`, `reviewer`, `oracle`, `delegate`; parent steers a running child; child asks the parent (`contact_supervisor`); `/subagents-fleet` inspector; `/subagent-cost` | MIT, about 3.8k stars | **Yes** (S1-S10) |
| [pi-messenger](https://github.com/nicobailon/pi-messenger) (nicobailon) 0.15.2 | Peer messaging between agents in separate terminals (DM, broadcast), file reservations, activity feed, and a "Crew" that turns a PRD into a task graph run in parallel waves with reviewers; state in files, no daemon | MIT, about 712 stars | **Yes** (M1-M9) |
| [pi-fork](https://github.com/elpapi42/pi-fork) (elpapi42) 0.1.0 | A `fork` tool that spawns a child `pi` process seeded with the current session branch, returns a structured report; cost footer | see repo | **Only its cost accounting** (C2) |
| [@ifi/pi-extension-subagents](https://www.npmjs.com/package/@ifi/pi-extension-subagents) | Fuller orchestration built on top of pi-subagents | see npm page | No |
| [mjakl/pi-subagent](https://github.com/mjakl/pi-subagent), [hoangvu12/pi-subagent](https://github.com/hoangvu12/pi-subagent) | Two separate lightweight subagent extensions (agents as Markdown files) | see repos | No |
| [Oh My Pi](https://github.com/can1357/oh-my-pi) (can1357) | A fork of pi-mono with subagents, LSP, debugging and 60+ providers built in, not an extension | see repo | No |
| Pi's own [examples](https://github.com/badlogic/pi-mono/tree/main/packages/coding-agent/examples/extensions/) `subagent/`, `event-bus.ts`, `handoff.ts` | Reference implementations: isolated child agents, extension-to-extension events, handoff to a fresh session | in-repo | No |

## How Pi is set up on this machine (deployment-specific)

Kept in this note, not in the `wiki/infra/` submodule: the infra-journal rule
([infra-journal.md](../rules/operations/infra-journal.md)) sends machine and deployment details there, but a note in
the submodule needs a commit in a separate private repo plus a pointer commit here that references an unpushed
submodule commit, which is not a straightforward workflow in this session. Move this section to `wiki/infra/` when
convenient. No key values are recorded here, provider names only.

- Pi 0.87.1 (`pi --version`), installed through nvm's Node 22; configuration under `~/.pi/agent/`
  (`settings.json`, `models-store.json`, `models.json`, `sessions/`, `npm/`, `git/`, `skills/`).
- `settings.json` packages: `npm:pi-frontend-create`, `git:github.com/elpapi42/pi-fork`, `npm:pi-subagents`,
  `npm:pi-messenger`. Default provider/model: **deepseek / deepseek-v4-pro at thinking xhigh**, an API key billed
  per token by DeepSeek, separately from the Claude subscription.
- Other providers configured in `auth.json` (names only): `github-copilot` (OAuth; its model list includes
  claude-sonnet-5, claude-haiku-4.5, gpt-5-mini and others; how Copilot bills usage was not checked), `kimi-coding`
  and `moonshotai` (API keys). Pi's existing session files already record metered spend on the pay-per-token providers
  (see [existing spend](pi-money-usage-recording.md#existing-spend-recorded-in-pis-own-history)), so none of them
  should be used by accident.
- The cheap DeepSeek model is `deepseek-flash` ($0.30 / $1.20 / $0.006 per 1M tokens in Pi's catalog, see
  [money note](pi-money-usage-recording.md#c1-is-pis-own-number-right)).
- **Decision (user, 2026-09-25):** use `deepseek-flash` at **low** thinking for these experiments and for the planned
  translation wave. Every test ran that way; the keys that enforce it are in the
  [claim-test note](pi-subagents-and-messenger-claim-tests.md#cost-routing-hazard-and-the-keys-that-worked).
- Skills: Pi loaded 11 (8 user-level skills, 3 from packages) per `/subagents-doctor`; the TUI startup also reported a
  skipped duplicate `clerk-cli` skill.

## Decision guide for this repo

What was measured about running Pi agents against this repo's workflow (own measurements, 2026-09-25, scratch
project with a canary `CLAUDE.md` and canary skills):

- Pi **loads `CLAUDE.md`** into a `project_context` section of the system prompt and follows it (the canary rule "end
  every reply with ZEBRA" was obeyed). This repo's `CLAUDE.md` is 21,955 bytes, roughly 5.5K tokens (estimate at 4
  characters per token) paid by every Pi agent started in the repo. `--no-context-files` disables it.
- Pi does **not** auto-discover `.claude/skills/`: a skill in `.pi/skills/` appeared in `<available_skills>`, an
  identical one in `.claude/skills/` did not. `--skill <dir>` loads it (verified). The relevant skills here are large:
  `translate-document` 22,321 bytes, `translate-video` 26,721, `verify-stt-transcript` 37,774. To use them from Pi, pass
  `--skill` or copy/symlink into `.pi/skills/` (not done).
- Pi has `bash`, so agents can run `uv run python ...` and call `agentic_doc` (Segond substitution, telemetry), but no
  such workflow was run under Pi.
- Pi's own cost accounting does not reach our telemetry DB; a bridge is described in the
  [money note](pi-money-usage-recording.md#c6-getting-pi-agent-costs-into-our-telemetry-assessment-only-nothing-implemented).

| | Claude Code Agent tool (used for the 50 Sproul videos) | pi-subagents | pi-messenger | pi-fork |
|---|---|---|---|---|
| fan-out / background | yes, in-session (observed: a platform cap on concurrent subagents, hit on 2026-09-24) | yes, `runs.all`, `async:true`, spawn cap default 64 | crew waves, concurrency default 2 (config path gap) | one child per call |
| steer a running agent | yes (`SendMessage`) | yes (`steer`, tool-boundary) | DM wakes a peer at its next tool boundary | no |
| agent asks the parent | hand-back message | `contact_supervisor` -> `subagent_supervisor reply` | DM | report only |
| peer-to-peer messaging | yes across sessions | no | **yes** (DM, broadcast, reservations) | no |
| cost mechanism | Claude subscription ("zero cost beyond the Claude Code subscription", [CLAUDE.md](../../CLAUDE.md)) | DeepSeek API, pay per token | same | same |
| cost visibility | subscription usage, not in telemetry | `/subagent-cost` (misses nested) | tokens only | footer + result |
| repo rules loaded | CLAUDE.md, skills | CLAUDE.md yes, `.claude/skills` no | same | same |
| quality on French theological translation | proven (50 videos) | **one pilot**: near agent-manual quality after review, see [the pilot](#pilot-one-grace-to-you-sermon-through-a-single-pi-agent-2026-09-25) | not measured | not measured |

Interactive use (a person typing in the Pi TUI while a background child runs, steering it, typing while the agent is
busy, messaging another session by asking the agent or directly in `/messenger`) was tested separately on 2026-09-30,
all PASS: [pi-interactive-delegation-and-messaging-test.md](pi-interactive-delegation-and-messaging-test.md).

Recommendation (a suggestion for the user to redirect, nothing changed in CLAUDE.md):

1. Keep the Claude Code agent-manual method as the default for translation and verification: it is the only path
   with demonstrated quality and it is free at the margin.
2. If a Pi wave is wanted, use **pi-subagents** with an explicit list of children and pinned deepseek-flash, after a
   one-sermon pilot with cost logging, and have the output judged before scaling. Use **pi-messenger crew** only for a
   task graph with real dependencies (its per-run overhead is a planner plus reviewers, about $0.048 for four trivial
   tasks); embarrassingly parallel translation does not need it. pi-fork is a context-management tool and adds little
   here.
3. **Apply the CLAUDE.md cost-consent rule.** It names `translate_document()` and `escalated_stt_correction()`, but a
   Pi agent calling DeepSeek is the same class of spend ("calls the API directly, billed separately from your
   subscription"), so a wave should get a per-invocation yes that names that mechanism and an estimate, as the
   rule's incident ([agent-manual-default-cost-confirmation.md](../rules/translation/agent-manual-default-cost-confirmation.md))
   requires. Whether to write this into CLAUDE.md is the user's call.
4. Before any wave: bridge Pi usage into the telemetry DB (or accept that the spend is invisible to it), fix the
   DeepSeek `ModelPricing` rows, and prefer DeepSeek's off-peak hours.

## Pilot: one Grace to You sermon through a single Pi agent (2026-09-25)

The user approved exactly this spend on 2026-09-25 ("One-sermon pilot now"): one Pi agent, DeepSeek API, billed
separately from the Claude subscription, estimated in advance at about $0.10 (an assumption, see the
[claim-test note](pi-subagents-and-messenger-claim-tests.md#what-this-means-for-a-10-agent-translation-wave)).
The measured cost was 2.4 times that.

### What was run

- **Document:** `video/divine-wisdom-for-the-family-part-a-selected-scriptures` (Grace to You radio sermon on
  Proverbs, [adf/video/divine-wisdom-for-the-family-part-a-selected-scriptures.md](../../adf/video/divine-wisdom-for-the-family-part-a-selected-scriptures.md)):
  127 cues, 28 minutes, several Scripture passages (Romans 1, Psalm 14, 1 Corinthians, 2 Timothy 3, Proverbs 1).
  Chosen because only 3 of the 1,157 then-untranslated Grace to You transcripts had 100-200 cues (own scan of
  `adf/video/*.md`, 2026-09-25) and it had many quotations to test Segond substitution. Its chunk stage (id 1412,
  from the corpus-wide backfill) was uncurated: no `sequence_index`, no STT flags.
- **Agent:** one top-level `pi` 0.87.1 process, `deepseek/deepseek-flash`, thinking `low`, the 7 pipeline skills
  passed with `--skill`, delegation tools excluded, run in a git worktree with no `.env`, `timeout 45m`, hard stop
  planned at $0.60. Prompt: the repo's agent-manual pipeline (chunk-and-store, verify-stt-transcript,
  chunk-and-clean, translate-document, verify-translation, assemble) plus the conventions that live in memory rather
  than in the repo (Trinity capitalization, lowercase "satan" outside verbatim Segond, "fratrie", numbers as words).
- **Recipe that worked** (re-usable for the wave):

```bash
# worktree so the agent's scratch files stay out of the main checkout; NO .env is copied in
git worktree add "$SC/wt" -b pi-pilot-tmp HEAD
# scratch/pi-pilot/run.sh in the worktree: cd worktree; PYTHONPATH=worktree/src;
#   uv run --project <main repo> --frozen --with language-tool-python --with symspellpy --with ftfy \
#     --with pythonbible --with getbible --with rapidfuzz python "$@"
echo '{"defaultProvider":"deepseek","defaultModel":"deepseek-flash","defaultThinkingLevel":"low"}' > wt/.pi/settings.json
cd wt && timeout 45m pi --provider deepseek --model deepseek-flash --thinking low -a --session-dir "$SC/sessions" \
  --exclude-tools subagent,subagents_enable,fork,pi_messenger \
  --skill .claude/skills/translate-video --skill .claude/skills/chunk-and-store ... (7 skills) \
  -p --mode json "$(cat prompt.txt)" < /dev/null > run.jsonl
# monitor: sum message.usage.cost.total over the session JSONL every few minutes; kill above the cap
```

### Measurements (own, 2026-09-25)

| item | value |
|---|---|
| run window | 08:14:48Z to 08:24:40Z, a Friday, entirely inside DeepSeek's **peak** hours (01-04 and 06-10 UTC, Mon-Fri) per the [pricing page](https://api-docs.deepseek.com/quick_start/pricing) |
| model activity | 84 turns, 91 tool calls (read 19, bash 52, write 15, edit 5), 1 tool error, about 9 min 50 s |
| tokens | 124,563 fresh input, 11,558,016 cache-read, 112,634 output |
| cost, peak rate | **$0.241878** = Pi's own figure (diff 3e-17); input $0.037369 (15 %), cache-read $0.069348 (29 %), output $0.135161 (56 %), at $0.30 / $0.006 / $1.20 per 1M |
| cost, off-peak equivalent | $0.120939 (the page: "Off-peak rates are half of the peak rates"); Pi would still have displayed $0.2419 |
| size | 118 included cues (9 excluded), 3,216 English words in, 3,442 French words out |
| unit costs | $0.00205 per included cue and $0.0752 per 1,000 English words at peak; output was 35 tokens per English word (thinking at `low` is inside it) |
| fixed part | about $0.04 was spent in the first minute reading the skills and the source (own monitoring snapshot at 08:15:41Z: 15 messages, $0.0387) |

The telemetry `PipelineRun` for it (id 511, `purpose=development`, `triggered_by=pi-agent:deepseek-flash`) shows
`total_cost_usd` 0: an agent-manual run logs no `LLMCall`, so **the real $0.2419 exists only in Pi's session file and
in the doc's pipeline log**. This is the gap described in the
[money note](pi-money-usage-recording.md#c6-getting-pi-agent-costs-into-our-telemetry-assessment-only-nothing-implemented);
it is not closed.

> **Closed later the same day:** the session was imported (`scripts/import_agent_usage.py`, run 511 now shows $0.241876 over 84 calls); see
> [agent-usage-telemetry.md](../rules/telemetry/agent-usage-telemetry.md).

### What the agent produced (agent's own report, each figure checked against the database)

127 cues, 118 kept and 9 excluded; 9 STT source corrections; 33 chunks substituted with real Segond 1910 and marked
`is_scripture` on both sides; 1 chunk flagged for a human; 6 fixes in its own verify pass; `adf_to_srt` clean;
117 `approved` + 1 `flag_for_human`. It followed the workflow: it read all 7 skill files first, read the repo's
`telemetry.py`, `translate.py`, `regenerate.py`, `subtitle.py` and `server/runs/views.py` to learn the APIs, made
**0 suspicious calls** (no `.env`, no paid function, no delegation, no git write, checked over all 91 tool calls), kept
per-stage pipeline-log entries whose timestamps match the database (revisions 08:18:04-08:19:18Z, translated chunks
08:22:47-08:22:50Z), and completed its run. It also caught its own off-by-one write in the STT stage (the skill's
documented hazard) and repaired it.

Its best judgement call: it excluded cues 0097-0105 as a Whisper hallucination loop (mixed Arabic/Dutch/Russian text,
"Thank you, Mom.", "Blend your friends", a 21 s cue holding 6 words). Own check: correct, and the loss is real, because
the full-length recording of the same sermon ([divine-wisdom-for-the-family.md](../../adf/video/divine-wisdom-for-the-family.md),
"Fourthly, wisdom says select your friends carefully") has speech there that Part A lacks; the agent flagged the next cue
for a human ear.

### Independent quality review (claude-sonnet-5 reading all 118 pairs; the agent is not a judge of its own work)

Mechanical, own scripts: 0 digits, 0 empty cues, 0 split negations, 0 real weak endings (the one hit is an exempt full
pronoun, "avec nous"), Trinity and Gospel conventions correct, `adf_to_srt` round-trips, French LanguageTool on the
joined text gave 20 candidates, all false positives. All 33 Scripture chunks were diffed word by word against
`resolve_french_verse()`: 29 are verbatim (verse splits across cues allowed), 4 deviate.

Defects found and **fixed by me in 13 chunk edits** (11 % of the cues; `revise_translated_chunk`, logged in the doc's
pipeline log): one real mistranslation ("right and wrong" as "le juste et le faux"), four calques ("commendation" as
"recommandation", "resident truth teacher" as "professeur de vérité résident", "foundational" as "fondamentales de base",
"the true and living God" as "le vrai Dieu vivant"), inconsistent book names ("Deuxième Timothée" next to "Première
épître aux Corinthiens"), a missing article before "Psaume" twice, a doubled colon, a stranded "Quelle étonnante" at a
cue end, and Proverbs 1:17-18 marked verbatim Segond but reworded ("de tout oiseau" for Segond's "de tout ce qui a
des ailes"). Left on purpose: "impies envers Dieu" (documented in the agent's own key_term_notes), two "ils" for Segond's
"qui", and the English "rightness" (the full-length recording reads "right and wrong"; left as spoken). Nothing
touched doctrine. Verdict: **accepted as a deliverable after the review fixes**; without them it would not pass this
repo's verify-translation standard.

How this compares with Claude agent-manual runs, without pretending it is a controlled test (different videos, n = 1):
the Claude agent-manual runs of 2026-09-23/24 fixed, before saving, 26 and 15 seam splits in two videos of 152 and 183
cues and 4 negation splits in each of two others ([wiki/log/2026-W39.md](../log/2026-W39.md), the 09:48 and 09:58
entries), and 55 weak cue endings in a 234-cue lecture (that video's pipeline log). Independent verification of those
runs then found real defects that the authors' own checks had missed: Romans 8:9-11 free-translated instead of Segond
and 3 more 1 Corinthians 15 cues not verbatim (the 07:17 entry), a cue truncated by a word-count split (the 09:58
entry) and unaccented French on two videos (the 09:42 entry). The Pi output was cleaner on seams (its own pre-save check found no real
violation, and mine agrees) and weaker on French word choice and on Segond exactness. Both need a review pass.

### Findings for running more of these

- **The worktree isolates files, not effects.** The telemetry server runs in Docker with the main checkout mounted, so
  every `revise_*` and `regenerate` call made by the agent wrote `adf/video/<slug>.md` and `<slug>.fr.md` into the
  **main** repo (root-owned), and every database write is global. Parallel agents must therefore own disjoint slugs, as
  the Claude batches already do; a worktree only keeps their scratch scripts apart.
- **No `.env` in the worktree is a useful guard:** `translate_document()` and the other paid functions cannot run there,
  and the agent never looked for one.
- **Skills need `--skill`;** the agent read about 146 KB of skill text (7 files) before starting. That is most of the
  fixed cost and does not shrink for a shorter document.
- **The agent wrote all 118 French cues in one file and saved them in a loop with a coverage assertion**, not one at a
  time as translate-document says; the Claude batches do the same, and no misalignment was found in this run.
- **It used a second recording of the same sermon** (the full-length transcript) to repair the garbled "inmates" cue.
  Sound here, but it rests on a document the task did not name; it marked the fix `uncertain`.
- **Its own verification missed the calques and the Prov 1:17 deviation** while judging them fine; an independent
  Segond diff and a native-level read are what caught them. A cheap gate for a wave: run a word-level diff of every
  `is_scripture` chunk against `resolve_french_verse()` and a reviewer read before accepting output.

### Projection for the 10-sermon wave (ASSUMPTION built on one measurement)

> **Superseded 2026-09-25 (afternoon)** by the calibrated model in [Wave readiness](#wave-readiness-2026-09-25-afternoon) below:
> median sermon $0.51 peak / $0.25 off-peak, ten about $5.1 / $2.5, with a range and a cache-hit-rate sensitivity. The linear
> extrapolation kept here is the earlier, coarser version.

Variable cost about ($0.2419 - $0.04) / 3,216 words = $0.063 per 1,000 English words at peak, plus about $0.04 fixed
per sermon. The untranslated Grace to You transcripts are much longer than the pilot (own scan of 1,156 files, words in
cue text: p25 6,168, **median 7,192**, p75 8,181, p90 9,101), so a median sermon is about $0.04 + 7.19 x $0.063 = **$0.49
at peak, $0.25 off-peak**, and ten of them about **$4.9 at peak, $2.5 off-peak**. The extrapolation is linear; cache-read
grows with context length, so treat these as a floor, not measured at that size. Time: about 22 minutes per median
sermon alone; ten in parallel about 25-30 minutes if DeepSeek does not throttle (behaviour at 10 concurrent requests
is unknown). The earlier $0.10 per sermon in the claim-test note was an assumption and is superseded by this.

### Recommendation (a suggestion; the user decides)

Quality is close enough to the agent-manual method that a wave is defensible, but it is a paid API spend, needs the
Claude review pass above (this pilot: 13 fixes in 118 cues), and its real cost is invisible to telemetry. If a wave is
run: (1) ask for a per-invocation yes naming the DeepSeek API and an estimate from the projection above; (2) run it at
off-peak hours (after 10:00 UTC on a weekday, or a weekend) for half price; (3) give each agent its own slug and pass
the same prompt, worktree and flags as the recipe; (4) put the Segond diff and the seam and digit checks in the prompt as
mandatory gates; (5) fix the `ModelPricing` rows and write the post-run importer first if the cost must land in
telemetry, otherwise record it in each pipeline log as done here.

## Wave readiness (2026-09-25, afternoon)

The user answered "fix first, then decide". Everything the pilot's recommendation listed is now built and verified **with no model or
API call** (all tests, dry runs and imports ran on data that already existed). Nothing has been run for the wave itself.

| what the pilot asked for | built | verified how |
|---|---|---|
| record the real cost in telemetry | [agent-usage-telemetry.md](../rules/telemetry/agent-usage-telemetry.md): `scripts/import_agent_usage.py`, migration 0037, `/api/usage-summary/` | the pilot's run 511 went $0 to $0.241876 (84 calls); independent sum $0.241878 |
| fix the `ModelPricing` rows | `--sync-pricing` (dated rows appended, none edited) | re-run reports every model up to date |
| Segond diff and seam gates in the prompt | [translation-gates.md](../rules/translation/translation-gates.md) | pilot: 26 of 33 Scripture chunks pass, 7 flagged (one the review had missed); mechanics 0 of 118 |
| one slug per agent / isolation | see "Separate slugs" below | probed on the live stack, two write paths confirmed |
| off-peak | launcher warns inside DeepSeek's peak window and can refuse (`--require-offpeak`) | dry run, unit tests |
| hard cost cap | launcher polls the session file and kills the agent past `--cap-usd` (recomputed cost at each message's own window) | unit test of the cost poller; the kill path itself not exercised (it needs a live agent) |

The unit is `scripts/pi/launch_translate_video.py --doc-id video/<slug> --purpose production --cap-usd 1.00`, one process per sermon
(`--dry-run` shows the exact command: `timeout 45m pi --provider deepseek --model deepseek-flash --thinking low -a --session-dir ...
--exclude-tools subagent,subagents_enable,fork,pi_messenger --skill <7 skills> -p --mode json "<prompt>" < /dev/null`). It creates a
worktree without `.env`, the document's `PipelineRun`, runs the agent, imports usage into the run, runs both gates itself and removes only its own worktree.

### Separate slugs: what is shared and what is not (probed 2026-09-25, live stack)

The pilot's note that a worktree "isolates files, not effects" is exact, and the two write paths were confirmed by rewriting identical
content with git staying clean:

| writer | where `adf/video/<slug>*.md` lands | proof |
|---|---|---|
| **client-side** `regenerate_agent_translated_document()` run with `PYTHONPATH=<worktree>/src` (`_repo_root()` is derived from the imported module's own location, [regenerate.py](../../src/agentic_doc/regenerate.py)) | the **worktree** | the file appeared in the worktree at 12:16:55, the main copy kept its 10:36:00 mtime |
| **server-side** regeneration: `POST document-translate-stages/<id>/regenerate/` and every `revise_*` / `regenerate_*` call ([views.py](../../server/runs/views.py)), because the Docker web container mounts the main checkout as `/app` ([docker-compose.yml](../../server/docker-compose.yml)) | the **main checkout**, owned by root | the main file's mtime moved to 12:17:02, the worktree copy untouched |

So what an agent delivers reaches the main checkout by itself, and the safe rule for parallel agents is **one slug per agent** (distinct files, distinct
rows, nothing collides; two agents on one slug would race). Consequences already handled in the launcher: the agent's **pipeline log** lives only in the
worktree, which is deleted, so the launcher copies it into the main checkout first (never overwriting an existing log); the agent is told not to edit the
shared `orthographic_allowlist.txt` (it would only change its own copy) and to list new words in its report. Still true and left as is: files written by the
container are root-owned (git is unaffected, deleting needs sudo), and ten agents' outputs all appear as uncommitted changes in one checkout, to be committed per slug
with explicit paths.

### Projection for ten sermons (model calibrated on the pilot; no spend)

The pilot's context grew from 13,002 to 226,327 tokens over 84 turns (mean 2,570 per turn; one 34,246-token write produced the whole French file), so
cache-read cost is turns times average context and grows faster than linearly with sermon length. The model: output = the French file (10.65 tokens per English
word, measured) plus other output (half fixed, half proportional to words in the "likely" case); fresh input = 55,000 fixed (system prompt and the seven skills)
plus 21.6 tokens per word; context = 60,000 fixed plus 49.1 tokens per word (fitted to the pilot's mean of 139,078); turns = 25 fixed plus 59 scaled by
(words / 3,216) to the power 0.4 / 0.7 / 1.0, plus 6 / 10 / 20 turns for the two gates and their fixes. It reproduces the pilot: $0.2426 against $0.2419 actual
(84 turns, 11.68M cache-read, 113k output, 125k fresh). Prices are DeepSeek's peak list rates, $0.30 / $0.006 / $1.20 per 1M
([pricing page](https://api-docs.deepseek.com/quick_start/pricing)); off-peak is half.

Sermon size, own scan of the 1,156 untranslated Grace to You transcripts (words of cue text): p10 3,793, p25 6,167, **median 7,191**, p75 8,175, p90 9,095, max 12,840.

| sermon size | words | low | likely | high | turns (l / m / h) |
|---|---|---|---|---|---|
| p25 | 6,167 | $0.35 | $0.44 | $0.56 | 108 / 128 / 158 |
| **median** | 7,191 | $0.40 | **$0.51** | $0.68 | 112 / 139 / 177 |
| p75 | 8,175 | $0.44 | $0.57 | $0.79 | 117 / 148 / 195 |
| p90 | 9,095 | $0.48 | $0.64 | $0.90 | 120 / 157 / 212 |

| ten sermons | low | likely | high |
|---|---|---|---|
| ten median sermons, **peak** | $3.96 | **$5.06** | $6.76 |
| ten median sermons, **off-peak** | $1.98 | **$2.53** | $3.38 |
| a realistic mix (3 x p25, 4 x median, 2 x p75, 1 x p90), off-peak | $2.00 | $2.56 | $3.44 |

At the median, "likely", peak: output $0.244, cache-read $0.197 (32.8M tokens), fresh input $0.065; context at the end about 414k tokens. The earlier linear figure ($4.9 / $2.5)
was close; this one adds the range and the risks below.

**The main tail risk is the cache hit rate**, because a cache miss costs 50 times a hit ($0.30 against $0.006). The pilot ran at 98.93%; the model assumes
99.35% for the long context. Per median sermon at peak: 99% $0.54, 98% $0.64, **95% $0.93**, **90% $1.41** (ten of them $5.4 / $6.4 / $9.3 / $14.1). Whether ten concurrent agents keep
that hit rate is **unmeasured**, and it is the first thing to check.

**Unmeasured assumptions, stated so nobody mistakes the table for a measurement:** the number of turns for a long sermon (exponent 0.4 to 1.0), the turns and tokens the
gates add (the pilot ran without them), how one 70,000-token French write behaves (the pilot's was 34,246), quality on 400k-token contexts (the 1M window allows it; nothing
was tested), whether DeepSeek throttles ten simultaneous agents, and machine load (each agent runs its own LanguageTool; the machine was at load average 9.9 during
unrelated work today, ten concurrent JVMs are untested). One pilot is one data point for every fixed-versus-proportional split above.

### Recommendation for the wave decision (a suggestion; the user decides)

1. **Do not start with ten.** Run ONE median-size sermon first, off-peak (after 10:00 UTC on a weekday, or a weekend), with the gates: about $0.25 to $0.30 expected,
   it measures the real turns, the gates' cost and the cache hit rate, and replaces this table's biggest assumptions with numbers.
2. Then run the remaining nine with `--cap-usd` at about 1.5 times the measured cost (the launcher enforces it per agent).
3. **Budget**: per agent `--cap-usd 1.00` (twice the likely median peak cost and above the high case); for the wave, $5.00 off-peak (the high case is $3.38; the margin covers a
   hit rate near 95%) or $8.00 if run at peak. The launcher caps each agent, not the sum: worst case is ten caps, so run the wave as two batches of five and read the
   cost after the first batch, or add a wave-level guard before going larger.
4. Keep the review pass. The pilot's output needed 13 fixes in 118 cues from an independent read that no gate replaces; budget Claude review time, which is on the subscription.
5. The wave is a DeepSeek API spend billed separately from the Claude subscription: it needs the user's per-invocation yes naming that mechanism and this estimate
   (CLAUDE.md, [agent-manual-default-cost-confirmation.md](../rules/translation/agent-manual-default-cost-confirmation.md)), even though the launcher and gates are ready.

## Follow-up: the errors became code and skill rules (2026-09-25)

The 389 edits of the pilot and wave were classified and turned into mechanical checks, a batch-persist helper and skill updates:
[agent-translation-error-catalogue.md](../rules/translation/agent-translation-error-catalogue.md) (counts, examples, catch and false-positive rates, what stays judgment-only).

## Status / next steps (2026-09-25)

- Done: landscape search, install check, claim tests M1-M9 / S1-S10, money-usage tests C1-C6 (cost about $0.20 total),
  and the one-sermon pilot above ($0.2419 at peak rate, accepted after review).
- Done 2026-09-25 afternoon (no spend): the telemetry importer and pricing sync, the two gates, the prompt template and capped launcher, the shared-checkout probe, the calibrated projection (all in [Wave readiness](#wave-readiness-2026-09-25-afternoon)).
- **Done 2026-09-25 (user's consent for exactly ten sermons, this model, $5 cap):** the ten-sermon wave, see [the results below](#wave-results-2026-09-25-run-1055z-to-1145z-off-peak).
  Still open: whether DeepSeek throttles at ten (not five) concurrent requests; a second wave needs a new consent.

### Wave results (2026-09-25, run 10:55Z to 11:45Z, off-peak)

The user gave a per-invocation, cost-specific yes for exactly ten sermons on `deepseek/deepseek-flash` at thinking `low`, DeepSeek API billed
separately from the Claude subscription, hard caps $1.00 per agent and $5.00 for the wave ([the cost-consent rule](../rules/translation/agent-manual-default-cost-confirmation.md)).
Ten Pi agents, one per sermon, were started with `scripts/pi/launch_translate_video.py --purpose production --cap-usd 1.00 --require-offpeak`
(own git worktree, no `.env`, own `PipelineRun`), at most five at a time. **No kill switch fired, no agent hit its cap, no message was billed at the peak rate.**

| sermon (link = its pipeline log) | cues | words (EN body, whitespace split) | turns | wall time | cost (off-peak) | Segond gate | content fixes at review (per 100 cues) | typography fixes |
|---|---|---|---|---|---|---|---|---|
| [Parents, do not provoke (Eph 6:4)](../../pipeline/log/video/parents-do-not-provoke-your-children-ephesians-6-4.pipeline.md) | 608 | 9,540 | 97 | 16 min 01 s | $0.1591 | 24/24 | 5 (0.82) | - |
| [The new Passover (Mark 14:17-26)](../../pipeline/log/video/the-new-passover-mark-14-17-26.pipeline.md) | 703 | 11,353 | 65 | 14 min 41 s | $0.1168 | 56/56 | 14 (1.99) | - |
| [Jesus, the divine Word (John 1:1-5)](../../pipeline/log/video/jesus-the-divine-word-john-1-1-5.pipeline.md) | 688 | 10,886 | 118 | 17 min 41 s | $0.1648 | 49/49 | 7 (1.02) | - |
| [Supernatural peace (John 14:27)](../../pipeline/log/video/supernatural-peace-john-14-27.pipeline.md) | 689 | 10,125 | 97 | 23 min 21 s | $0.1915 | 52/52 | 19 (2.76) | 102 |
| [Absolute inability (audio only)](../../pipeline/log/video/the-doctrine-of-absolute-inability-selected-scriptures-audio-only.pipeline.md) | 684 | 10,870 | 69 | 17 min 20 s | $0.1335 | 76/76 | 25 (3.65) | - |
| [The truth about hell](../../pipeline/log/video/the-truth-about-hell-selected-scriptures.pipeline.md) | 644 | 10,447 | 92 | 23 min 01 s | $0.1581 | 92/92 | 12 (1.86) | - |
| [Jesus trades places with a leper (Mark 1:40-45)](../../pipeline/log/video/jesus-trades-places-with-a-leper-mark-1-40-45.pipeline.md) | 674 | 10,722 | 87 | 13 min 20 s | $0.1433 | 44/44 | 5 (0.74) | - |
| [What if there is no resurrection (1 Cor 15:12-20)](../../pipeline/log/video/what-if-there-is-no-resurrection-1-corinthians-15-12-20.pipeline.md) | 611 | 9,922 | 82 | 16 min 20 s | $0.1412 | 69/69 | 11 (1.80) | - |
| [How Christmas solves the prophetic puzzle](../../pipeline/log/video/how-christmas-solves-the-prophetic-puzzle-selected-scriptures.pipeline.md) | 645 | 10,200 | 86 | 18 min 41 s | $0.1467 | 105/105 | 2 (0.31) | - |
| [Is God still revealing truth?](../../pipeline/log/video/is-god-still-revealing-truth-selected-scriptures.pipeline.md) | 637 | 10,421 | 83 | 17 min 00 s | $0.1398 | 16/16 | 8 (1.26) | 74 |
| **total** | **6,583** | **104,486** | **876** | | **$1.4948** | **all pass** | **108 (1.64)** | **176** |

Sources for the table: per-agent `summary.json` under the gitignored `scratch/pi-launch/<slug>/` (turns, wall seconds, tokens, gate output; the launcher's own measurement),
the review edits from the telemetry table `runs_translatedchunkrevision` (`edited_by = claude-review:wave-review`, own SQL join to the document), and the pipeline logs linked in the first column.
Costs are recomputed by me from the token counts at the [DeepSeek published rates](https://api-docs.deepseek.com/quick_start/pricing) as stored in the
`pricing` block of [config/pipeline.yaml](../../config/pipeline.yaml) ($0.30 / $0.006 / $1.20 per 1M tokens, times 0.5 off-peak) and equal the launcher's figure to the cent for every agent.
The word counts are my own rough count of the ADF body, used only for ratios.

**Cost.** Total **$1.4948**, against the $5.00 wave cap (30 %) and against the projection of $1.98 to $3.38 off-peak in the [projection above](#projection-for-ten-sermons-model-calibrated-on-the-pilot-no-spend):
**below the low end**. Per agent $0.1168 (the new Passover, 65 turns) to $0.1915 (supernatural peace, 97 turns, the longest output at 189,127 tokens); mean $0.1495.
That is about $0.0143 per 1,000 words, against $0.0376 for the pilot (its $0.1209 off-peak equivalent over about 3,216 words, see [the pilot cost](pi-money-usage-recording.md#measured-one-real-translation-run-pilot-2026-09-25)):
the fixed part of each run is amortised over a sermon three times longer. The Pi catalog cost is peak-rate only, so it read exactly twice these figures ($2.99 in sum); the recompute was the number used for the cap.

**Telemetry.** The launcher imported each session; I checked the ten runs (PipelineRun ids 515 to 524, `purpose=production`, `billing=api`) by SQL: 876 `LLMCall` rows, $1.494786 in total, per-run turns and cost equal to my recompute,
and re-running `scripts/import_agent_usage.py` on every session inserted 0 rows (10 of 10 "new 0, already present N").

**Concurrency and rate limits.** Five concurrent agents throughout (peak of five at once, refilled as each finished). **0 HTTP 429 / rate-limit / overloaded / timeout matches** in any agent's stderr; 20 tool-result errors in 994 tool calls, all
recovered by the agent (the largest count was 4 in one agent). Cache-read share of prompt tokens 98.6 % to 99.3 % (pilot 98.93 %), so the projection's cache-miss tail risk did not materialise. Machine load was not measured; I saw no agent stalls.
Ten simultaneous agents were **not** tested (capped at five by choice).

**Review (independent, Claude Code on the subscription, every cue of every sermon read against the English).** 108 content fixes in 6,583 cues (**1.64 per 100 cues**; range 0.31 to 3.65 per sermon) plus 176 programmatic fixes for one systemic slip
(no regular space before `:` `?` `!` `;`, in 2 of 10 runs: 102 chunks in supernatural peace and 74 in "Is God still revealing truth?"; neither gate detects it). By category (own count of the same table): lexical_choice 54,
grammar 19, mistranslation 13, register 8, orthographic (not the spacing fix) 6, theological_interpretation 5, omission_or_addition 3. The theological ones are real and were not caught by the gates, for example "God breathed" (*theopneustos*) rendered "inspiré de Dieu" in a passage arguing that
"inspired" is the wrong word; false friends ("autoritaire" for "authoritative", "soumissions" for "submissions") and one duplicated/omitted half-verse (Revelation 5:5) are the other typical kinds. The pilot needed 13 fixes in 118 cues (about 11 per 100, [pilot review](#pilot-one-grace-to-you-sermon-through-a-single-pi-agent-2026-09-25));
the wave's rate is about one seventh of that, plausibly because the wave prompt included both gates, but the two are different sermons and I did not test that cause. No comparable per-100-cue rate was ever recorded for the Claude Code agent-manual batches, so **no defect-rate comparison against them is made here**.
The reviewer's own usage was imported (`--source claude-code`, `billing=subscription`, batch `pi-wave-review-2026-09-25`, 146 messages, API-equivalent estimate about $15.47, **not** real spend; attribution to these ten sermons is approximate because the same transcript carries the whole review).

**Verdict per sermon.** All ten are **accepted** as deliverables on the pilot's standard (both gates pass, every cue read, defects fixed), committed in `60916a2d`. Left as-is on purpose and flagged, not fixed: loose (unsubstituted) scripture recitations
where the speaker paraphrases rather than quotes (for example Heb 1:1-2 and Ex 3:14), and English cues that are themselves garbled by the STT (for example new-passover cue 0553, truth-about-hell cue 0291); both are listed in the review entries of the linked pipeline logs. Nothing is left for a human beyond ordinary review of the ADF.

**Honest verdict: Pi + deepseek-flash (low) versus the Claude Code agent-manual method.** For the *draft*, Pi is defensible and very cheap: $0.15 a sermon, about 18 minutes of wall time per agent (mean 1,065 s) and 48 minutes for all ten with five in parallel, no subscription usage, no `.env` exposure, and the Segond gate keeps quotations verbatim.
It is not a replacement for review: about 1.6 real defects per 100 cues, several theological or false-friend errors per sermon in the worst cases (3.65 per 100 in the audio-only doctrine sermon), and one typography slip that no gate sees. So the honest recommendation is Pi for the first draft plus a Claude-side (or human) review pass, and add a space-before-punctuation
check to the mechanics gate before another wave. The comparison with the agent-manual cost is not like for like: agent-manual costs $0 on the subscription but consumes subscription usage, which the importer only estimates (about $15 API-equivalent for this review alone), so "Pi is cheaper" holds for API money only.

---
type: Research Note
title: Money-usage recording in Pi and its extensions -- what each one reports, whether it is correct, and how to get it into our telemetry
description: >
  Empirical check (2026-09-25, deepseek-flash, thinking low) of whether Pi core, pi-fork, pi-subagents and
  pi-messenger record what an agent run costs. Pi core, pi-fork and pi-subagents report money and match ground
  truth recomputed from raw session files; pi-subagents silently omits nested (depth-2) children; pi-messenger
  records tokens only. Pi's price table is DeepSeek's PEAK rate at all hours. None of it lands in our telemetry DB.
timestamp: 2026-09-25T08:39:40Z
---

# Money-usage recording in Pi and its extensions

Part of the Pi investigation: overview and decision guide in
[pi-agent-extensions-overview.md](pi-agent-extensions-overview.md), claim-by-claim test results in
[pi-subagents-and-messenger-claim-tests.md](pi-subagents-and-messenger-claim-tests.md). This note answers the
user's question "does each extension record money usage" (asked 2026-09-25; the user believed
[pi-fork](https://github.com/elpapi42/pi-fork) has it). Everything below is an own measurement of 2026-09-25
unless a link says otherwise. All test agents ran `deepseek/deepseek-flash` at thinking `low`.

## Result table (C5)

Ground truth = cost recomputed by hand from the raw `usage` records in the session/artifact JSONL files
(tokens x catalog price), never from an extension's own display.

| extension | reports money? | matches ground truth? | covers children / background / nested? | persisted after exit? | gotchas |
|---|---|---|---|---|---|
| **Pi core** (per assistant message `usage.cost.total`) | Yes, per message; footer shows a running total | Yes: 253 messages in 49 sessions, reported $0.110059 = recomputed $0.110059, max per-message diff 8.7e-19 | Own session only; child usage delivered as async notifications is NOT in Pi's totals ([observability.md](https://github.com/nicobailon/pi-subagents/blob/main/docs/observability.md), and in the pty run of the pi-fork test Pi's own footer showed only the parent's figures, the fork cost sat on a separate line) | Yes, in the session JSONL | Price table is DeepSeek's **peak** rate always (see below); footer shows 3 decimals (`$0.000` for a $0.0005 call); `output` already includes `reasoning` tokens (131 of 131 messages with reasoning had output >= reasoning) |
| **pi-fork** 0.1.0 | Yes: `usage.cost` per fork result and a `forks +$x` footer line | Yes, exactly: 2 forks, reported $0.001819 = sum recomputed from each child's embedded transcript (diff 0) = hand calc from tokens ($0.0004347 + $0.001383864) | Forks yes; forks-of-forks per [README](https://github.com/elpapi42/pi-fork) and `src/cost.ts` (not tested) | Yes, **inline in the parent's session file** (`toolResult.details.results[].usage` plus the child's full `messages`); no separate child session files | Footer is UI-only (needs a TTY; seen as `forks +$0.000` in a pty run, true cost $0.000435 rounds away). `pi-fork.costFooter:false` in project `.pi/settings.json` removes the line (0 occurrences in a pty run, fork still ran). `cost` is a plain number here, an object `{total}` elsewhere |
| **pi-subagents** 0.71.0 (`/subagent-cost`, RPC `cost`) | Yes: parent, per-child, children total, total | Yes for foreground, parallel async workflow (3 children) and background single child, to its 4-decimal display (s2 $0.0070 vs GT $0.006968; s3 $0.0094 vs $0.009403; s5 $0.0042 vs $0.004197) | Foreground, parallel, background: yes. **Nested (depth-2) child: NO** -- coordinator -> scout run showed Total $0.0036 while ground truth is $0.005416 (the scout's own $0.001785 session file exists but is not listed): -34 % | Yes: works from a fresh `pi -p --session <file> "/subagent-cost"` process, reads child `session.jsonl` files and run artifacts; costs no LLM call | 4-decimal display; no per-model breakdown (agent name and tokens only); needs the parent session file (`--session`); RPC `cost` method not exercised (in-process event bus), slash command is the equivalent per [extension-api.md](https://github.com/nicobailon/pi-subagents/blob/main/docs/extension-api.md) |
| **pi-messenger** 0.15.2 (crew) | **No.** Tokens only | n/a. Its `tokens` = input+output only: worker_0 `_meta.json` says 18,758 = 12,439 + 6,319, so cache-read (236,928 for that worker) is excluded and cost cannot be derived from it | Crew workers, planner, reviewers: tokens in `_meta.json`; `whois`/`list` show a live token count per agent | Raw usage (with `cost`) survives only in `<project>/.pi/messenger/crew/artifacts/*.jsonl`, default retention 7 days (`artifacts.cleanupDays`, [README](https://github.com/nicobailon/pi-messenger#crew-configuration)) | Crew workers write **no Pi session file**, so `/subagent-cost`, Pi's footer and any session-dir scan all miss them. Ground truth for the crew-1 run: $0.0482 (planner + 4 workers + 4 reviewers), lead session separately $0.0060 |

Bottom line: the user's belief is right for pi-fork, and pi-subagents also has it; pi-messenger does not.
Nobody records money for a nested subagent (pi-subagents) or for crew workers (pi-messenger) in a place Pi
itself totals up.

## C1: is Pi's own number right?

- Pi's model catalog (`~/.pi/agent/models-store.json`, price fields only read) holds `deepseek-flash` at
  input $0.30, output $1.20, cacheRead $0.006, cacheWrite 0 per 1M tokens, and `deepseek-v4-pro` at
  $1.32 / $3.96 / $0.044.
- DeepSeek's [official pricing page](https://api-docs.deepseek.com/quick_start/pricing) (fetched 2026-09-25,
  page has no update date) lists `deepseek-flash` cache-hit $0.006 peak / $0.003 off-peak, cache-miss $0.30 / $0.15,
  output $1.20 / $0.60, and `deepseek-v4-pro` $0.044/$0.022, $1.32/$0.66, $3.96/$1.98. So Pi's catalog = the
  **peak** column exactly. The page says off-peak is half of peak and that peak hours are 01:00-04:00 and
  06:00-10:00 UTC Monday-Friday excluding Chinese public holidays (i.e. 03:00-06:00 and 08:00-12:00 Paris time in
  summer).
- All tests ran 07:20-07:55 UTC on a Friday, inside peak, so reported = billed rate for this battery. **Outside peak
  Pi over-reports by 2x** (its table has no time-of-day notion); the reported figure is an upper bound.
- Arithmetic check: a bare "Reply OK" turn reported input 6,325 tokens, output 2, cost $0.0018999 =
  6325 x 0.3 + 2 x 1.2 per M. Across all 253 messages the recomputed and reported totals agree to 1e-18.
  Reasoning tokens are inside `output`, so thinking is billed at the output rate in Pi's figure.
- `deepseek-v4-flash` (older id seen in the user's history) is documented by DeepSeek as a deprecated alias billed at
  Flash pricing; Pi's current catalog has no row for it.

## Existing spend recorded in Pi's own history

Own scan of every session file under `~/.pi/agent/sessions` on 2026-09-25 09:24 (before this battery's real tests; its
smoke tests had cost under $0.01), using each assistant message's `usage.cost.total`:

| provider / model | assistant messages | fresh input | output | cache-read | cost recorded by Pi |
|---|---|---|---|---|---|
| deepseek / deepseek-v4-pro | 4,132 | 6.16M | 3.35M | 1.03B | $11.37 |
| deepseek / deepseek-flash | 247 | 0.50M | 0.29M | 22.9M | $0.64 |
| moonshotai / kimi-k2.7-code | 91 | 0.12M | 0.05M | 6.7M | $1.56 |
| github-copilot (9 models) | 10,361 | | | | $0.00 (Pi records no cost for the subscription models) |

So Pi's figures are already a real record of pay-per-token spend on this account, and Copilot usage is invisible to
Pi's cost numbers (whether Copilot meters it elsewhere was not checked).

## C6: getting Pi-agent costs into our telemetry (assessment only, nothing implemented)

> **Built 2026-09-25, after this assessment:** the importer is `scripts/import_agent_usage.py`
> ([agent-usage-telemetry.md](../rules/telemetry/agent-usage-telemetry.md)). It differs from the plan below in three
> ways: it recomputes cost from tokens with a `pricing` block in `config/pipeline.yaml` instead of relying on the
> server's flat `ModelPricing` (which cannot express DeepSeek's off-peak half price), a schema migration (0037) adds
> `billing`, `external_id` and time-of-day pricing, and it also reads Claude Code transcripts. The `ModelPricing` gaps
> listed under "Gaps that must be fixed" below were fixed by `--sync-pricing`. The pilot's run 511 now shows
> $0.241876 instead of $0. The text below is kept as written for the record.

CLAUDE.md requires every paid model call to be logged with cost via `agentic_doc.telemetry` (`purpose`
test/development/production) and forbids discarding the response. Pi's accounting lives in its own JSONL files, so
a Pi translation wave would be invisible to the DB unless bridged.

**Approach (recommended): post-run importer, no Pi extension.**
1. Before the wave: `get_or_create_document()` + `start_run(document_doc_id, stage, purpose="production" or "test",
   triggered_by="pi-agent")` per sermon -- exactly what the agent-manual path already does
   ([telemetry.py](../../src/agentic_doc/telemetry.py) `start_run`, `complete_run`).
2. After the wave, read every source of Pi usage and call `log_llm_call(run_id, provider="deepseek",
   model="deepseek-flash", call_purpose=..., input_text, output_text, prompt_tokens=usage.input,
   completion_tokens=usage.output, cache_read_tokens=usage.cacheRead, latency_ms=<timestamp deltas>)` per
   assistant message. `log_llm_call` computes `cost_usd` **server-side from `ModelPricing`** and says "never pass
   it in", so the importer sends tokens, and Pi's own dollar figure is only a cross-check.
3. Sources to walk (all three are needed): (a) the parent session JSONL and every child session under
   `<session-dir>/<parent-stem>/<runId>/run-*/session.jsonl`, **recursively**, so nested children are included even
   though `/subagent-cost` misses them; (b) `toolResult.details.results[].messages` for pi-fork; (c) crew
   `<project>/.pi/messenger/crew/artifacts/*.jsonl`, copied out before the 7-day cleanup.
4. Persist the whole response (CLAUDE.md "persist everything from paid calls"): each assistant message's text and
   tool calls are in the same JSONL, so `output_text` is available; dedupe by `(responseId, timestamp)` because a
   resumed session file replays earlier messages.
5. Reconciliation check in the importer: recomputed cost vs Pi's `usage.cost.total` (they matched to 1e-18 here) and
   vs the sum `/subagent-cost` prints; flag a mismatch.

**Gaps that must be fixed in the DB first** (queried 2026-09-25 from `runs_modelpricing`):
- A `deepseek/deepseek-flash` row exists (input 0.30, output 1.20, `effective_from` 2026-09-25) but its
  `cache_read_usd_per_mtok` is empty. With cache reads at 90-97 % of input tokens (this battery: 3.1M cache-read vs
  0.25M fresh input) an empty cache price either zeroes or mis-prices most of the input side. Set 0.006 (peak).
- The `deepseek/deepseek-v4-pro` row says 0.435 / 0.87 / 0.0036, which disagrees with both Pi's catalog and DeepSeek's
  page (1.32 / 3.96 / 0.044 peak). Whichever is stale, re-verify against the pricing page before relying on it.
- No off-peak notion: peak/off-peak halves the price. Either store both rates with a time window or log at peak
  rate and accept a 2x upper bound (document it).
- `provider` naming: Pi says provider `deepseek`, model `deepseek-flash`; the table key is `deepseek/deepseek-flash`.

**Effort estimate (assumption, not measured):** the importer is a self-contained script of roughly 150-250 lines
(JSONL walk + dedupe + one POST per message + reconciliation), plus one ModelPricing fix; well under a day including
a test on the sessions from this battery. An alternative (a small Pi extension hooking `message_end` to POST
directly) would give live logging but couples our DB to Pi's extension API and needs the DB reachable from every
child process; not recommended for a first version.

Do not edit CLAUDE.md for this; if a wave is approved, the existing paid-call logging rule already covers it and the
per-invocation cost-consent rule applies (see the decision guide in
[pi-agent-extensions-overview.md](pi-agent-extensions-overview.md#decision-guide-for-this-repo)).

## Measured: one real translation run (pilot, 2026-09-25)

A single top-level Pi agent translated one Grace to You sermon on `deepseek-flash` at thinking `low`
(details in [the pilot section](pi-agent-extensions-overview.md#pilot-one-grace-to-you-sermon-through-a-single-pi-agent-2026-09-25)).

| source | messages | fresh input | output | cache-read | cost |
|---|---|---|---|---|---|
| Pi session file and the `--mode json` stream (identical, deduplicated on `(responseId, timestamp)`) | 84 | 124,563 | 112,634 | 11,558,016 | **$0.241878** at the peak rate |
| recomputed from the tokens at $0.30 / $0.006 / $1.20 per 1M ([pricing](https://api-docs.deepseek.com/quick_start/pricing)) | | | | | $0.241878 (diff 3e-17) |
| the same tokens at the off-peak rate ($0.15 / $0.003 / $0.60) | | | | | $0.120939 |

- The run was 08:14:48Z to 08:24:40Z on a Friday, inside peak hours, so the figure Pi shows is also the rate billed by
  the published schedule. Output is 56 % of the cost, cache-read 29 %, fresh input 15 %.
- **Telemetry records $0 for it.** `PipelineRun` id 511 (`purpose=development`, `triggered_by=pi-agent:deepseek-flash`,
  status success) has `total_cost_usd` 0 because agent-manual runs log no `LLMCall`; the other Claude agent-manual runs
  that day show the same 0 plus an `estimated_cost_usd` in `result_summary`. So a Pi/DeepSeek run breaks the rule that
  every paid call is logged with its cost unless someone imports it: the real spend is only in Pi's session file and,
  for this document, in an entry of its pipeline log ([pipeline log](../../pipeline/log/video/divine-wisdom-for-the-family-part-a-selected-scriptures.pipeline.md),
  stage `pilot_cost_measurement`). The importer plan in C6 above still applies unchanged, and so do the two
  `ModelPricing` fixes (cache-read price for `deepseek-flash`, the `deepseek-v4-pro` row); nothing was built or changed.
- Everything here came from the single session file: a run with no subagents, no crew and no fork has no cost outside
  it.
- **Update 2026-09-25 (afternoon):** run 511 now carries the 84 imported calls and reads **$0.241876** (was $0), via
  [agent-usage-telemetry.md](../rules/telemetry/agent-usage-telemetry.md); the rounding to 6 decimals per call explains $0.241876 against the unrounded $0.241878.

## Cost of the whole test battery (own accounting)

| source | messages | in | out | cache-read | cost |
|---|---|---|---|---|---|
| Pi sessions incl. subagent child sessions (recursive scan, 60 files) | 277 | 161,646 | 51,524 | 2,088,832 | $0.1229 |
| crew-1 artifacts (planner + 4 workers + 4 reviewers) | 69 | 52,788 | 24,025 | 596,096 | $0.0482 |
| crew-2 artifacts (planner + 4 workers, review off) | 47 | 33,033 | 12,923 | 392,960 | $0.0278 |
| pi-fork embedded child transcripts | 2 forks | 2,875 | 654 | 28,544 | $0.0018 |
| **total** | | **250,342** | **89,126** | **3,106,432** | **about $0.20** |

Only `deepseek/deepseek-flash` appeared in any file (325 non-deduplicated assistant messages inspected); no
github-copilot, kimi or moonshot model was used. Hard cap was 3M in+out tokens; used 339,468.

## Measured: the ten-sermon wave (2026-09-25, off-peak)

Full write-up, per-sermon table and review outcome: [the wave section](pi-agent-extensions-overview.md#wave-results-2026-09-25-run-1055z-to-1145z-off-peak). The money figures:

| | messages | fresh input | cache-read | output | cost |
|---|---|---|---|---|---|
| ten Pi agents, `deepseek-flash` low (own sum of `scratch/pi-launch/*/summary.json`; equal to my recompute from the session JSONL) | 876 | 1,443,444 | 144,713,088 | 1,406,871 | **$1.4948** off-peak |
| the same tokens at the peak rate (what Pi's catalog cost shows) | | | | | $2.99 |
| pilot for comparison (one sermon, peak) | 84 | 124,563 | 11,558,016 | 112,634 | $0.2419 ($0.1209 off-peak) |

- Rates: the `pricing` block of [config/pipeline.yaml](../../config/pipeline.yaml) ($0.30 / $0.006 / $1.20 per 1M; off-peak multiplier 0.5), from the [DeepSeek pricing page](https://api-docs.deepseek.com/quick_start/pricing).
- Per agent $0.1168 to $0.1915, mean $0.1495; wave total 30 % of the $5.00 cap and below the $1.98 to $3.38 projection. Cache-read share 98.6 % to 99.3 %. 0 rate-limit errors, 0 peak-priced messages.
- Telemetry: PipelineRun 515 to 524, `billing=api`, `purpose=production`; DB total $1.494786 over 876 calls equals the recompute, and re-import inserts 0 rows (checked by SQL and by re-running the importer on each session).
- The Claude Code review of these sermons was imported as batch `pi-wave-review-2026-09-25` (`billing=subscription`, 146 messages, API-equivalent estimate about $15.47, not real spend; attribution approximate).


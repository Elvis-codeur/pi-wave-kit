---
type: Rule
category: translation
title: Pi wave runner -- one capped launcher per document, run N at a time under a cumulative wave cap
description: How scripts/pi/launch_translate_video.py (hardened) and scripts/pi/run_wave.py run a wave of Pi/DeepSeek translation agents, and which steps code does around each worker (pre-step, post-step, one repair session) since 2026-10-05. Covers the consent flag, the per-document and wave caps, the timeout formula and the data behind it, failure statuses, resume, the condensed context files, the new prompt placeholders, the server-side regenerate, and the stage checks + escalation protocol (stage_check.py, escalate.py, the coordinator session, blocked runs, the stop file).
tags: [translation, pi, deepseek, wave, launcher, cost, agent-manual, escalation, pi-messenger]
timestamp: 2026-10-05T12:57:00Z
---

# Pi wave runner

Built 2026-10-02 to close the "Launcher robustness at 100" items and A1, A3 and A6 of the
[100-sermon readiness audit](../../research/pi-wave-100-readiness-audit.md). Two scripts:

- [`scripts/pi/launch_translate_video.py`](../../../scripts/pi/launch_translate_video.py): one document, one Pi agent, one
  hard cost cap.
- [`scripts/pi/run_wave.py`](../../../scripts/pi/run_wave.py): runs that launcher N at a time over a list of documents, under a
  cumulative cap.

Every launch is a DeepSeek API call billed separately from the Claude subscription. The
[cost-consent rule](agent-manual-default-cost-confirmation.md) therefore applies to every wave.

## The rule

1. **A wave is a dry run unless `--yes-i-consent-to-deepseek-spend` is given.** Without the flag, `run_wave.py` classifies every
   document (read-only), prints the plan, the projected cost and the worst case (the sum of the caps), and stops. Get the user's
   explicit yes for that projection before re-running with the flag.
2. **A killed run is a failed run.** The launcher marks the `PipelineRun` `failed` in each of these cases:
   - a `timeout` exit (124, or 137 when `-k` had to KILL);
   - a cost-cap kill or the wall backstop;
   - any non-zero `pi` exit;
   - no session file;
   - an agent that created no translate stage, or left included chunks untranslated;
   - `pi` failing to start.

   It does this through `agent_usage.finalize_run(..., status="failed")` (new `status` parameter,
   [agent_usage.py](../../../src/agentic_doc/agent_usage.py)), or `complete_run(status="failed")` from its `finally` block. The
   earlier launcher marked every run `success`, including killed ones, per the audit's
   [A6](../../research/pi-wave-100-readiness-audit.md#a-blocking-or-high-impact).
3. **Only a complete, unkilled, unblocked run publishes a `.fr.md`.** The launcher's post-step calls
   `telemetry.regenerate_translate_stage(id)`, which is `POST document-translate-stages/<id>/regenerate/`
   ([views.py](../../../server/runs/views.py) `DocumentTranslateStageViewSet.regenerate`). The server writes into the checkout
   it runs from, the main one. Since 2026-10-05 the worker no longer regenerates anything itself (see
   [Code steps around the worker](#code-steps-around-the-worker-2026-10-05)).
4. **Gates are run by the launcher**, from the main checkout, with explicit `--translate-stage`/`--chunk-stage` and `--json`.
   The mechanics gate runs with `--languagetool --fix-digits --fix-spacing --fix-seams --edited-by <worker identity>`
   (`--fix-digits` since 2026-10-05, [below](#digit-auto-fix-2026-10-05)). Their output is saved to
   `gate-<name>.txt` in the work dir and merged into the run's `result_summary.gates`.

## Launcher changes (CLI is backward compatible)

| Flag | What it does |
|---|---|
| `--prompt-template PATH` | The prompt template. Default: `scripts/pi/translate-video-prompt.md`. |
| `--skills-mode full` | Default. Passes the seven skills as `--skill <dir>`, as before. |
| `--skills-mode condensed` | Passes no skills (and `--no-skills`, so none are discovered either). Instead passes `scripts/pi/agent-checklist.md`, `scripts/pi/fr-theology-glossary.md` and `scripts/pi/review-examples.md` as context files. A real launch refuses if one is missing; `--dry-run` only warns. |
| `--context-file PATH` (repeatable) | Extra file appended to Pi's system prompt. Works in either mode. |
| `--skill PATH` (repeatable) | Extra skill dir or file. |
| `--stage ID` | Chunk stage to use. Required when the document has more than one: the launcher refuses and prints the ids instead of silently taking `max(id)`. |
| `--resume` | Continue an existing, incomplete translate stage (see the placeholders below). |
| `--discard-stale-branch` | Delete a stale `pi-wave-<slug>` branch even when it holds commits HEAD lacks. |
| `--timeout-min N` | Now optional; the default comes from the formula below. |

How the context files reach Pi: `--append-system-prompt <path>` "Appends text or an existing file to the system prompt and is
repeatable", and `--no-skills` "Disables discovered and configured skills. Explicit `--skill` paths still load". Both quotes are
from Pi 1.0.0's own `docs/cli.md` (installed package, `pi --version` = 1.0.0), and both flags are listed by `pi --help`. Verified
with `--help` and the docs only, no model call. A path that does not exist would be appended as literal text, which is why the
launcher checks that every file exists first.

Other changes:
- **Paths.** Derived from the doc_id prefix: `adf/<source>/<slug>.md`, `.fr.md`, and `pipeline/log/<source>/<slug>.pipeline.md`.
  Before, `video/` was hardcoded, per the audit's [A1](../../research/pi-wave-100-readiness-audit.md#a-blocking-or-high-impact).
- **Source ADF in the worktree.** The worktree is built from `HEAD`. The source ADF is copied in when the worktree's copy is
  missing (the file is untracked in git) or differs (uncommitted server-side STT corrections).
- **Worktree setup and teardown run in try/finally.** A stale worktree is handled first: the agent's pipeline log is rescued
  into the main checkout, then the worktree is removed. A stale `pi-wave-<slug>` branch is deleted when it has no commits HEAD
  lacks. When it has some, the launch refuses and lists them (`--discard-stale-branch` overrides, with a warning). Teardown never
  deletes a branch with unmerged commits; it keeps it and says so in `summary.json`.
- **Cost.** Each launch writes its sessions to `sessions/<run_id>/`. Both the live cost poll and the usage import read every
  session file there, not only the newest.
- **`summary.json`** is written from the `finally` block, so it also exists after a crash. It now records `status`, `reason`,
  `cues`, `timeout_min`, `cap_usd`, `tstage_id`, `included`/`missing`, `session_files`, `regenerated`, `stale_cleanup`,
  `teardown`, and `adf_copied_into_worktree`.

## Prompt placeholders

The existing placeholders are unchanged. A placeholder left unfilled stops the launch. The coordinator writes the prompt text
that uses these:

| Placeholder | Value |
|---|---|
| `{{EDITED_BY}}` | Same string as `{{TRANSLATED_BY}}` (`pi-agent:<provider>/<model>`). For `edited_by=` on STT/source edits and `revise_translated_chunk`, so the skills' hardcoded `agent:claude-sonnet-5` is overridden (audit A5). |
| `{{SOURCE}}` | The doc_id prefix (`video`, `sermonindex`, ...). |
| `{{ADF_PATH}}` | Repo-relative source ADF path. |
| `{{FR_ADF_PATH}}` | Repo-relative French ADF path. |
| `{{LOG_PATH}}` | Repo-relative pipeline log path. |
| `{{STT_SIGNALS}}` | One factual line. Either the `VideoIngestion` id, engine and model, the number of cues with signals, how many are flagged (non-empty `flag_reasons`), the GET URL, the key format (cue number without leading zeros), and whether the chunks already carry them; or a line saying none exist. Looked up read-only: `videos?document=<db id>` then `video-ingestions?video=<id>`. Audit A2. |
| `{{RESUME}}` | `yes` when launched with `--resume` on a partial stage, else `no`. |
| `{{TSTAGE_ID}}` | The existing translate stage to continue, or `none`. |
| `{{MISSING_CHUNKS}}` | Included chunks (`translate=true`, `include_in_output=true`, not superseded) with no `TranslatedChunk` in that stage. On a fresh launch: all included chunks. |
| `{{RESUME_NOTE}}` | One sentence built from the three above: continue stage N, translate only the M missing chunks, do not overwrite the others, do not create a new stage. On a fresh launch: "create one". |

A resumed launch creates a new `PipelineRun`. The resumed stage keeps the run it was created with.

## Timeout formula and its data

```
timeout_min = min(240, ceil(18 + 5.0 * cues / 60))
```

Refit 2026-10-03 from the first 45 runs of the sproul-100 wave (2026-10-03, all off-peak), twice: two documents (145 and
239 cues) hit the old 15 + 3.0 s/cue limit at 103%+ of the timeout while the median run used 43% (base 15->16 min, slope
3.0->4.0 s/cue); then ascension-what-did-jesus-do (254 cues, 41 scripture chunks) needed more than 33 min under that fit,
so base 16->18 min and slope 4.0->5.0 s/cue. Wall clock is free (money is capped), so the tail gets the headroom
(wiki/log/2026-W40.md). The original data (kept for the record) comes from the ten-sermon wave of
2026-09-25. Each run's wall `seconds` is in `scratch/pi-launch/<slug>/summary.json` (gitignored); the cue counts are
the `<!-- cue:` anchors in each `adf/video/<slug>.md`:

| cues | wall s | s/cue | cost USD (off-peak) |
|---|---|---|---|
| 645 | 1121 | 1.74 | 0.1467 |
| 637 | 1020 | 1.60 | 0.1398 |
| 688 | 1061 | 1.54 | 0.1648 |
| 679 | 800 | 1.18 | 0.1433 |
| 608 | 961 | 1.58 | 0.1591 |
| 689 | 1401 | 2.03 | 0.1915 |
| 684 | 1040 | 1.52 | 0.1335 |
| 703 | 881 | 1.25 | 0.1168 |
| 653 | 1381 | 2.11 | 0.1581 |
| 611 | 980 | 1.60 | 0.1412 |

- **Range.** 1.18 to 2.11 s/cue (median 1.59). The cue range is only 608 to 703.
- **No base can be fitted.** A least-squares fit gives 832 s + 0.35 s/cue with r = 0.06. The data cannot separate a fixed part
  from a per-cue part.
- **3.0 s/cue.** That is about 1.4 times the slowest observed rate, charged as if all the time were per-cue. This is the
  conservative choice for long documents.
- **15-minute base. ASSUMPTION.** It covers the fixed work: reading the skills or checklists, and the agent's own gate runs (the
  LanguageTool pass is about 20 s per call, per the
  [mechanics gate's docstring](../../../scripts/check_translation_mechanics.py)). It also keeps tiny documents (7 to 30 cues)
  from getting a timeout of one or two minutes.
- **Margin.** On every wave document the formula gives at least twice the observed wall time; the tightest is 689 cues, 50 min
  against 23.4 min. A [test](../../../tests/test_pi_wave.py) checks this.
- **240-minute cap.** The Sproul list has 948 entries (median 186 cues, p90 422, max 4,599), counted by me from
  `scratch/sproul-awaiting-translation.txt` in the main checkout. Its largest document (4,599 cues) gets 240 min. The slowest
  observed rate would need 162 min for it.
- **Extrapolation. ASSUMPTION.** Applying a rate measured at 600 to 700 cues to 20-cue and 4,600-cue documents is untested.
  Re-fit after the first wave: the wave summary records `cues` and `wall_seconds` per document.

`--timeout-min` still overrides the formula. The launcher also kills the agent itself 5 minutes after the timeout, as a
backstop.

## Cost projection (estimate, never a price)

**Superseded as the default on 2026-10-02:** run_wave.py now projects with the model fitted on the recorded runs
([cost-forecasting.md](../telemetry/cost-forecasting.md): `0.0543 + 0.000144 x cues` off-peak on 12 runs, with a 90%
range) and caps from each document's high projection. The formula below remains the fallback (no server, fewer than 5
runs, or `--fixed-projection`) and the launcher's own dry-run figure.

```
projected_usd = 0.03 + 0.00028 * cues      (off-peak; x2 at peak = 1 / offpeak_multiplier 0.5)
```

- **0.00028 $/cue.** The highest $/cue of the wave above (0.191486 USD / 689 cues), so the estimate sits on the high side.
- **0.03 fixed part. ASSUMPTION.** The wave cannot measure it (cost against cues: r = -0.02).
- **Peak multiplier.** From `config/pipeline.yaml` `pricing.deepseek/deepseek-flash.offpeak_multiplier`
  ([pipeline.yaml](../../../config/pipeline.yaml)).

For the first 100 entries of the Sproul list, the dry run printed $10.19 projected at off-peak rates. The worst case was $62.65,
with `--cap-usd 0.60 --cap-scale 2`. That dry run ran on 2026-10-02 with no launch.

## Wave runner

```
uv run python scripts/pi/run_wave.py scratch/sproul-awaiting-translation.txt --max-docs 100 --order small-first \
    --cap-usd 0.60 --cap-scale 2 --wave-cap-usd 15 --concurrency 5 --require-offpeak            # dry run
... --yes-i-consent-to-deepseek-spend                                                            # launches (paid)
```

- **Input.** A file of doc ids, either bare or in the scratch list format `video/<slug> | cues=N`.
- **Skipped and reported.** These are never launched:
  - documents already translated (a complete translate stage, or a `.fr.md` without one);
  - documents with no chunk stage or several chunk stages, or with no Document or ADF;
  - incomplete translate stages, unless `--resume-partial` is given (then the launcher runs with `--resume`);
  - documents beyond `--max-docs`. With `--order small-first`, the list is sorted by its cue counts before any request.
- **Per-document cap.** `max(--cap-usd, --cap-scale x projected)`. With the default `--cap-scale 0`, large documents would be
  killed, so the dry run warns when the projection exceeds the cap.
- **Wave cap.** A document launches only if:

  ```
  committed spend + caps of the running documents + its own cap <= --wave-cap-usd
  ```

  - **Committed spend** is the real cost of every finished document in the wave summary, including earlier invocations. A
    launch that left no `summary.json` counts its whole cap.
  - When the next document does not fit, the runner waits for running documents to finish. Once nothing is running, it stops
    launching and reports the rest as `not_launched`.
  - The effective concurrency is therefore about `(wave cap - committed) / cap`. The dry run prints it when that is below
    `--concurrency`.
  - A document can overshoot its own cap by one 20-second poll before it is killed.
- **`--require-offpeak`.** No launch inside DeepSeek's peak window (weekdays 01:00-04:00 and 06:00-10:00 UTC, from the same
  `pricing` block). A wave that reaches the window stops launching and lets the running documents finish.
- **Output.** `<out-dir>/wave-summary.json` and a `.md` twin, rewritten after every launch and every finish. Per document:
  status (`success`, `failed`, `gates_failed`, `not_launched`, or a skip status), cues, cost, turns, gate exits, wall seconds,
  reason, run_id and tstage_id.
- **Resume.** Re-running the same command skips documents whose summary says `success`.

## Code steps around the worker (2026-10-05)

**User decision, 2026-10-05: code over LLM.** Every mechanical step moved out of the worker into the launcher; the worker
keeps only the judgment: STT verification decisions, the English clean-up fixes, the translation, and the EN-vs-FR
review.

### Why: what the mechanical stages cost

- **Cost per stage.** On the 75 successful sproul-100 worker runs, chunk_and_clean cost $0.4701, gates $0.6513, assemble
  $0.2296 and final $0.5943: $1.9453 of $7.9278 (off-peak re-pricing), more than stt_verification itself ($1.7155)
  ([cost-forecasting.md](../telemetry/cost-forecasting.md#cost-per-stage-and-the-claude-coordinator-equation)).
  Curate added $0.5086 for work that is mostly mechanical numbering.
- **What those turns did.** Counted over the same 75 `run.jsonl` files with
  `scripts/pi/stage_cost_split.py scratch/pi-wave100/launch scratch/pi-wave100/docs-100.txt --tools`
  ([stage_cost_split.py](../../../scripts/pi/stage_cost_split.py), definitions in its docstring; my own run, 2026-10-05):
  6,922 assistant messages; 1,031 `stage_check.py` calls (417 in chunk_and_clean, gates, assemble and final), 478 `date`
  calls, 767 calls touching `pipeline/log/`, 432 gate-script calls, 340 regenerate calls and 176 `mark_stt_verification`
  calls. The coordinator's own count for the task that started this change (563 stage_check calls in the four stages,
  143 `date`, 72 log edits, 232 gate runs, 185 regenerations, 2,120 worker turns, 45 real French fixes from the gates)
  used other definitions that are not recorded; the order of magnitude is the same.
- **Why each call is expensive.** Every worker turn re-reads the whole context (cache reads) and thinks (output tokens),
  so a `date` or a `stage_check` run from the model costs a full turn; run from code it costs nothing.

### What code does now

| When | Step | Where |
|---|---|---|
| pre-step | number the included cues `sequence_index` 0..N-1 in `original_index` order, only when they are not already (excluded chunks keep `None`) | [pipeline_steps.py](../../../scripts/pi/pipeline_steps.py) `numbering_plan`, `pre_step` |
| pre-step | the chunk-stage check (`translation_gates.check_source_chunks`, as [check_chunk_stage.py](../../../scripts/check_chunk_stage.py)) | `pre_step` |
| pre-step | create the fr translate stage (`method agent_manual`, `run` = the run id), or reuse an existing empty one; `classify()` now treats an EMPTY translate stage as `ready`, not `resumable` | `pre_step`, [launcher](../../../scripts/pi/launch_translate_video.py) `classify` |
| pre-step | write `scratch/pi-run/facts.md` (cue counts, numbering, chunk check, STT signals, worklist summary, hallucination candidates), `cues.md` (every included cue: cue number, seq, chunk id, text), `stt-worklist.md` (exactly [stt_worklist.py](../../../scripts/stt_worklist.py)'s Markdown), `clean-candidates.md` (`find_correction_candidates()` once on the joined cues, mapped to cue + chunk id; a CASING hit exactly at a cue start is dropped) | `pre_step`, `clean_candidates` |
| pre-step | a `launcher_pre_step` pipeline-log entry; LanguageTool failing stops the launch before any model call | launcher |
| worker | one mechanical call: `pipeline_steps.py review-sheet` writes `review-sheet.md` (the review worklist rows, then every cue `[seq] tc <id>` EN/FR) | `review_sheet` |
| post-step | `POST document-chunk-stages/<id>/regenerate/` (new `telemetry.regenerate_chunk_stage`), so the worker's STT fixes reach `adf/<doc>.md` with one rebuild | [telemetry.py](../../../src/agentic_doc/telemetry.py) |
| post-step | both gates (`--json`, parsed by `launcher.parse_gate`; mechanics with `--languagetool --fix-digits --fix-spacing --fix-seams`, see [below](#tail-auto-cover-and-seam-auto-fix-2026-10-05)), then the server-side French regenerate, then `adf_to_srt(fr, source_body_markdown=en)` | `post_step`, `run_gates`, `srt_check` |
| post-step | dispositions coverage of the STT and review worklists (from the worktree's files only: stage_check's new `--dispositions-dir`; non-suspicious `tail` pairs auto-covered, [below](#tail-auto-cover-and-seam-auto-fix-2026-10-05)), and `mark_stt_verification(done, "worklist", <worker identity>)` only when the STT dispositions cover the worklist | `post_step`, [stage_check.py](../../../scripts/pi/stage_check.py) |
| repair | when a gate FAIL or an undisposed worklist pair remains: ONE short pi session (below), then the post-step once more | launcher |
| end | the five stage entries (`chunk_and_store`, `stt_verification`, `chunk_and_clean`, `translation`, `translation_verification`) from real figures: DB counts (exclusions, human-ear flags, revisions by the worker identity since the run start, translated / scripture / key-term counts), gate summaries, dispositions counts; times from the run (pre-step end, dispositions-file mtimes, last translated chunk's `created_at`, post-step end) | `gather_figures`, `log_entries`, [pipeline_log.py](../../../src/agentic_doc/pipeline_log.py) |
| end | `stage_check --stage final` in-process, read-only, then a `final` log entry (result, WARN/FAIL lines, worker/repair turns and cost, the list of code steps) | `final_check` |
| end | usage of every session (main + repair) imported into the one PipelineRun; `summary.json` gets `steps` (per-step seconds, cost, turns, results) and `code_did` | launcher `finally` |

The log is written straight into the MAIN checkout's `pipeline/log/<source>/<slug>.pipeline.md` with
[agentic_doc.pipeline_log](../../../src/agentic_doc/pipeline_log.py) (YAML `runs:` entries appended as text, tz-aware
times, Markdown-body fallback). A worker's escalation line goes there too: the launcher sets `PI_WAVE_PIPELINE_LOG`, which
[escalate.py](../../../scripts/pi/escalate.py) now honours. A failed or blocked run before the post-step gets a
`pi_worker_run` entry instead, never one of the five stage names.

### The worker's scope now

[agent-checklist.md](../../../scripts/pi/agent-checklist.md): 5 steps instead of 8 stage_check-gated stages; 130 lines /
1,475 words / 11,078 bytes, from 190 / 1,854 / 13,993 (`wc` on both versions, 2026-10-05). The prompt
([translate-video-prompt.md](../../../scripts/pi/translate-video-prompt.md)) went from 825 to 730 words.

1. STT: a line in `stt-dispositions.txt` per worklist row, hallucination exclusions (candidates given), read every cue of
   `cues.md`, one `revise_document_chunk` per cue, no regenerate.
2. Clean: a line in `clean-dispositions.txt` per candidate (`<#>\t<fix|dismiss>\t<reason>`), real fixes only.
3. Translate with `persist_batch` into the pre-created stage (seams, Segond, key-term notes: unchanged rules).
4. Review: `review-sheet`, a line per worklist row in `review-dispositions.txt`, read every cue EN beside FR,
   `revise_translated_chunk` fixes; at most one optional `stage_check --stage translation --no-retry-count`.
5. Write `scratch/pi-run/DONE`.

Every judgment rule, convention, Scripture rule, the escalation path and the never-do list are kept. Forbidden now:
`stage_check` loops, the gate scripts, `regenerate_*`, `adf_to_srt`, `regenerate_subtitle=True`, `mark_stt_verification`,
`date`, writing `pipeline/log/`.

### When the post-step runs, and the repair session

- **Post-step only** when pi was not killed or timed out, exited 0 or wrote `DONE`, every included cue is translated, and
  no escalation of this run says `stop`. Otherwise the run is `failed` (or `blocked`) as before.
- **Not repairable, so blocked at once** (escalation record kind `tool_failure` or `data_problem`): a gate crash
  (traceback, unexpected exit code, unparseable JSON, exit code that disagrees with the parsed FAILs) or an
  `adf_to_srt` mismatch after both regenerates.
- **Repair session.** `scratch/pi-run/repair.md` lists each failing cue (seq, tc id, EN, FR, the gate lines) and each
  undisposed worklist pair. Pi runs with [repair-prompt.md](../../../scripts/pi/repair-prompt.md) and
  [repair-checklist.md](../../../scripts/pi/repair-checklist.md) only (`--no-skills`), same model and thinking, same
  worktree and environment, cap = `--cap-usd` minus the main session's recomputed cost (skipped below $0.01: blocked,
  `budget_or_time`), timeout `min(30, 10 + 1 x items)` minutes. That timeout is an ASSUMPTION (no repair run measured yet).
  It writes `REPAIR_DONE`.
- **Still failing after one repair** (or the repair session escalated `stop`): no second loop. The launcher writes an
  escalation record itself (stage `post_step`, kind `decision_needed`, action `stop`, agent `launcher`, same format and
  directory as [escalate.py](../../../scripts/pi/escalate.py)), the run ends `blocked`, and `run_wave.py --retry-blocked`
  relaunches it after the fix as before.

### Tail auto-cover and seam auto-fix (2026-10-05)

The live validation (scratch/codesteps-5, codesteps-3b, pi-launch/do-we-have-free-will; [W41 log](../../log/2026-W41.md))
sent 8 of 8 finished runs into a repair session. Two causes were mechanical, so code now handles them:

- **Tail auto-cover.** Workers skipped the `tail` lines even when told to write one range line. A `(cue, tail)` pair
  is now disposed by code, "dismiss: auto — not suspicious"
  ([stt_worklist.tail_auto_cover / tail_suspicion](../../../src/agentic_doc/stt_worklist.py)), when the cue is clearly
  real speech: included; `tail` is its only worklist check; no STT `flag_reasons` (even `implausible_speech_rate` alone);
  `chars_per_sec` within the STT step's own bounds (`video.stt.verify` min/max in
  [config/pipeline.yaml](../../../config/pipeline.yaml), 3-25); at least 3 words; Latin letters only; no known tail
  phrase ("Thank you", "God bless", "Amen", "I'm sorry", "right back", "thanks for watching", ...); no repetition; not a
  near-duplicate of the previous cue; STT signals present. Anything else still needs a worker line.
  [stage_check](../../../scripts/pi/stage_check.py) (`stt_auto_covered`, `disposition_conditions(auto_covered=)`) and
  the post-step ([pipeline_steps.uncovered](../../../scripts/pi/pipeline_steps.py)) use the same set; facts.md tells the
  worker which tail rows need a line; summary.json (`steps.post_step.stt_auto_covered`: count + cues), the
  `mark_stt_verification` notes and the stt_verification log entry record it.
  - Measured on those 8 launch dirs (DB state after the runs, repair lists as written): 23 of the 35 `tail` repair
    items (of 83 repair items in all) would not have been raised. The 12 left are on cues with another check (6 pronoun,
    2 stt_flag, 1 dup_prev), a sign-off phrase ("Thank you for listening.") or under 3 words ("Amen.").
  - Safety, at the pre-step state (each run's exclusions undone): none of the 42 cues the workers excluded as
    hallucinations would have been auto-covered (9 punctuation-only cues of do-we-have-free-will, 10 "Amen." loop cues
    of christ-coming-in-glory, the halluc/stt_flag tails of contradiction-and-paradox-003, coram-deo, cleansing-of-the-leper,
    the dup_prev cue of christ-and-david).
- **Seam auto-fix** (`check_translation_mechanics.py --fix-seams`,
  [translation_gates.plan_seam_fixes](../../../src/agentic_doc/translation_gates.py)). A `weak_ending` FAIL: the trailing
  weak word(s) (at most 3, as many as needed, so "à ce" moves together) go to the start of the next cue; only when that
  would empty the cue are the next cue's first word(s) pulled back. A `split_negation` FAIL only when the next cue starts
  with the partner (pas, jamais, plus, rien, ...): it is pulled back. Never a Scripture cue on either side, never across
  an excluded cue (`original_index` must differ by exactly 1), never an empty cue, never a new seam FAIL on either cue;
  the concatenated French is unchanged and a second run plans nothing. Applied with one `revise_translated_chunk` per
  changed cue (category `orthographic`, reason "cue seam (...) (check_translation_mechanics.py --fix-seams)", `edited_by`
  as for `--fix-spacing`: the launcher passes the worker identity, the CLI default is `agent:mechanical-gate`), the
  French regenerated on the last one, then the gate re-checks.
  - Measured on the same 8 runs, French reconstructed as it was at the first post-step (repair revisions undone):
    10 of 13 seam FAILs fixed, 0 new FAILs. Left for the repair session: 2 split negations whose partner is not at the
    start of the next cue, 1 weak ending inside a Scripture cue.
  - Verified on the real blocked case, video/contradiction-and-paradox-003 (run 173b0e04): the last FAIL (seq 207
    ending on 'à') fixed, gate 0 fail, adf_to_srt OK, stage_check final WARN; finished without a model call.
- **Effect on repair sessions:** with both, 1 of the 8 repair sessions would not have run. The rest still had `digits`
  FAILs (20 across 3 runs), Segond differences (9 across 4 runs) or STT pairs that are the worker's to judge. A
  mechanical `digits` fix is the next candidate (counts from the 8 repair.md files).

### Digit auto-fix (2026-10-05)

- **`check_translation_mechanics.py --fix-digits`** ([agentic_doc.french_numbers](../../../src/agentic_doc/french_numbers.py)),
  now first in the post-step's fix list (before `--fix-spacing`, so "trois, seize:" then gets its space). It writes the
  digits a worker left ("verset 24", "Jean 3.16", "en 1517", "16e siècle") in the corpus's word forms, never in a
  Scripture cue, and leaves any form it cannot read with certainty (a number ending in "un" before an unknown noun, a
  decimal, "N.N" with no Bible book, alphanumerics, URLs) as a `digits` FAIL for the repair session. Same recording as
  the other fixers: one `revise_translated_chunk` per changed cue, category `orthographic`, reason "digits written out
  in words: '24' -> 'vingt-quatre' (check_translation_mechanics.py --fix-digits)", `edited_by` the worker identity;
  per-cue detail goes to stderr so `parse_gate` still reads the JSON. Rules, conventions and measurements:
  [translation-gates.md](translation-gates.md#fix-digits).
- **On the repairs it replaces:** of the 129 real digit->word revisions the deepseek-flash repair sessions made
  (TranslatedChunkRevision history, `tests/fixtures/digit_revisions.json`), the converter reproduces 122 exactly; the
  other 7 are a seam move made in the same revision, a reviewer's "mil" for the corpus's "mille", a changed final
  punctuation, a "quatorze:" left without its French space, a chapter/verse the English does not confirm, and two
  "première/deuxième Corinthiens" forms the `book_name` gate itself rejects ([test_french_numbers.py](../../../tests/test_french_numbers.py) KNOWN_DIFFERENCES).

### Verification so far

- **Unit/integration tests** (fake pi, in-memory telemetry, tmp git repo): [tests/test_pi_steps.py](../../../tests/test_pi_steps.py)
  (numbering, pre-step files, dry run, reuse, clean-candidate mapping, review sheet, coverage counts, post-step marking,
  log figures, gate parsing, code-steps cost split) and the code-steps block of [tests/test_pi_wave.py](../../../tests/test_pi_wave.py)
  (success path with the log written by code, no rewrite of a contiguous numbering, gate FAIL -> repair -> success,
  repair still failing -> blocked + escalation, no budget for a repair, the dry-run plan), plus
  [tests/test_pipeline_log.py](../../../tests/test_pipeline_log.py).
- **Read-only pre-step on a real document** (`pipeline_steps.py prestep --dry-run`, 2026-10-05 14:54 CEST, my run):
  `video/do-we-have-free-will-ultimately-with-r-c-sproul`, chunk stage 1437, 66 cues: numbering needed on all 66; chunk
  check WARN `no_stt_signals` and a 9-cue `punct_only_run`; STT worklist 20 rows / 31 pairs from VideoIngestion 1410;
  11 hallucination candidates (cues 5 and 26 dup_prev, 58-66 punct_only); 7 clean candidates, in 5.5 s.
- **Not yet verified:** a real launch with a real worker. The first one is the coordinator's to run (paid, needs the
  user's yes); compare it with `stage_cost_split.py scratch/pi-launch --flow code-steps --tools --doc <slug>`.

### Running a wave as a systemd unit, 10 at once (2026-10-07)

The sproul-200 campaign ([wiki/log/2026-W41.md](../../log/2026-W41.md), 2026-10-07 entries) runs each wave of 10 with
`--concurrency 10` inside `systemd-run --user -p MemoryHigh=7G -p MemoryMax=9G`, so a memory overrun kills the wave
unit, never the desktop session (systemd-oomd killed the whole terminal scope on 2026-10-05,
[2026-W41](../../log/2026-W41.md)). Three things learned on the first launch:

- **PATH:** a user unit does not get the login shell's PATH, and `pi` lives under nvm
  (`~/.nvm/versions/node/v22.22.3/bin/pi`). The first wave 00 launch failed all 10 documents with `pi exited 127` before
  any API call ($0). Pass `--setenv=PATH="$PATH"` (and `PYTHONUNBUFFERED=1` so the runner's lines reach the journal).
- **Memory:** 10 workers peaked at 7 GB for the unit (the `MemoryHigh` throttle) with 499 MB swapped (wave 00,
  `systemctl --user show` after the run). Every LanguageTool check now goes to the one shared server
  (`agentic-languagetool` unit, `languagetool.remote_server` in `config/pipeline.yaml`) instead of a JVM per call.
- **Concurrency ceiling: this machine's RAM, not DeepSeek's own cap.** See
  [[pi-wave-concurrency-limits]]: DeepSeek documents a 2,500-connection account-level concurrency limit for
  `deepseek-flash` (0.8% used at 20 workers), so the binding constraint is the 14 GB host, measured at ~7 GB
  peak for 10 workers.
- **Peak hours:** `--require-offpeak --offpeak-margin-min 40` stops launching 40 minutes before a DeepSeek peak window
  (UTC 01-04 and 06-10, Monday-Friday, half price outside them per
  [the pricing page](https://api-docs.deepseek.com/quick_start/pricing), checked 2026-10-07), so no document runs mostly
  at peak price.

## Stage checks and escalation

Added 2026-10-02 for the setup "one interactive coordinator session + up to 10 deepseek-flash workers". A worker never
decides by itself that a stage is finished. Since 2026-10-05 the worker no longer runs these checks stage by stage: the
launcher runs `stage_check --stage final` once after its post-step (see above), and the worker may run the cheap
`--stage translation` check at most once. When a worker cannot proceed, it still escalates instead of improvising.

### `scripts/pi/stage_check.py`

```
scratch/pi-run/run.sh scripts/pi/stage_check.py --doc-id video/<slug> --stage <stage> [--json] [--chunk-stage N] [--translate-stage M]
```

- **Stages**, in order: `curate`, `stt_verification`, `chunk_and_clean`, `translation`, `gates`, `assemble`, `review`,
  `final` ([stage_check.py](../../../scripts/pi/stage_check.py)).
- **Output.** One line per condition, `[PASS|FAIL|WARN] <condition id>: <detail>`, then `RESULT: PASS|FIX|ESCALATE|WARN`
  and `NEXT: <one imperative sentence>`. `--json` prints the same report as JSON.
- **Exit codes.** 0 PASS; 1 FIX (the agent can fix what the FAIL lines say, then reruns the check); 2 ESCALATE (tool error,
  data inconsistency, missing ingestion, impossible condition; `NEXT` holds the `escalate.py` command to run); 3 WARN (passes,
  the WARN lines go in the pipeline-log entry).
- **Read-only on the database.** It only reads through `telemetry` and runs the gate scripts in their default read-only mode.
  The only file it writes is the retry counter (`--no-retry-count` skips that too).
- **Retry limit.** Each FIX result is counted per document + stage + condition in `scratch/pi-run/stage-retries.json`. The
  third FIX of the same condition (`MAX_FIX_RETRIES = 2`) comes back as ESCALATE, kind `decision_needed`, so a worker cannot
  loop on something it does not know how to fix. A condition that passes resets its counter. The limit of 2 is a design
  choice, not a measurement.

What each stage checks, and the library code it reuses:

| Stage | Conditions (FAIL is FIX unless marked ESCALATE) | Reused code |
|---|---|---|
| `curate` | exactly one chunk stage (none or several: ESCALATE); every included, non-superseded chunk has a `sequence_index`; included indices are exactly 0..N-1; no `punct_only_run`; WARN when no cue carries `stt_signals` | `translation_gates.check_source_chunks` (the [chunk-stage check](../../../scripts/check_chunk_stage.py)) |
| `stt_verification` | `curate` passes; `scratch/pi-run/stt-dispositions.txt` covers every (cue, check) of the current STT worklist; the chunk stage's `stt_verification_status` is `done` (recorded with `telemetry.mark_stt_verification`; field missing: ESCALATE); WARN above max(5, 5% of included cues) human-ear flags | `stt_worklist.join_signals`/`build_worklist` and the ingestion lookup of [stt_worklist.py](../../../scripts/stt_worklist.py) |
| `chunk_and_clean` | the pipeline log has a `chunk_and_clean` stage entry | `pipeline_state.log_stages` ([pipeline_state.py](../../../src/agentic_doc/pipeline_state.py)) |
| `translation` | exactly one `fr` translate stage on the chunk stage (several: ESCALATE); every included chunk (`include_in_output`, `translate`, not superseded) is translated; no empty translated cue | the launcher's `translation_progress` definition |
| `gates` | both gate scripts, the mechanics one with `--languagetool`: exit 0 PASS (WARN lines: WARN), exit 1 FIX, a traceback, another exit code, a timeout or a failed start ESCALATE (`tool_failure`) | [check_scripture_fidelity.py](../../../scripts/check_scripture_fidelity.py), [check_translation_mechanics.py](../../../scripts/check_translation_mechanics.py) |
| `assemble` | `adf/<doc>.fr.md` exists; `adf_to_srt(fr, source_body_markdown=en)` passes. `CueMismatchError` is FIX, with the regenerate hint; an unreadable ADF (ESCALATE `data_problem`) or any other exception (ESCALATE `code_bug`) is not the agent's to fix | `subtitle.adf_to_srt` |
| `review` | `scratch/pi-run/review-dispositions.txt` covers every (cue, check) of the current translation worklist | `translation_worklist.load_work_cues`/`build_worklist` ([translation_worklist.py](../../../scripts/translation_worklist.py), default checks, no LanguageTool) |
| `final` | each previous stage is PASS or WARN; the pipeline log has the five entries `chunk_and_store`, `stt_verification`, `chunk_and_clean`, `translation`, `translation_verification` | all of the above |

- **One deviation from the original spec.** `curate` requires a `sequence_index` on every *included* chunk, not every chunk.
  `mark_document_chunk_hallucination` sets `sequence_index=None` on the chunk it excludes, by design
  ([telemetry.py](../../../src/agentic_doc/telemetry.py) docstring), so an excluded chunk without an index is correct.
- **The human-ear threshold is an ASSUMPTION** (not measured). It only produces a WARN.
- **Any unexpected exception** while a stage is evaluated (a telemetry error, an API that ignored a filter) is ESCALATE,
  kind `tool_failure`.

**Dispositions files.** One line per worklist row and check:

```
<cue>\t<check>\t<fix|flag|dismiss>\t<reason>
```

- `<cue>` is the number the worklist prints. For `stt_worklist.py` that is the cue-anchor number. For
  `translation_worklist.py` it is the `sequence_index`, as in its `## cue N` headings.
- `<check>` is the row's check code, or `*` for every check of that row.
- Tabs are the format; runs of spaces are accepted. Blank and `#` lines are ignored.
- A malformed line is FIX.
- A line for a row that is no longer in the worklist (it was fixed away) is a WARN, not a failure.

### `scripts/pi/escalate.py`

```
scratch/pi-run/run.sh scripts/pi/escalate.py --doc-id D --stage S --kind {code_bug,data_problem,decision_needed,tool_failure,budget_or_time} \
    --action {stop,continue} --summary "..." [--evidence "..."] [--tried "..."] [--need "..."]
```

It does three things, and exits 0 ([escalate.py](../../../scripts/pi/escalate.py)):

1. Writes a JSON record to `$PI_WAVE_ESCALATION_DIR/<slug>/<timestamp>.json`. The record holds the timestamp (timezone-aware,
   `config.get_timezone()`), `doc_id`, `stage`, `kind`, `action`, `summary`, `evidence`, `tried`, `need`, `agent`
   (`PI_AGENT_NAME`), `run_id` (`PI_WAVE_RUN_ID`), `coordinator` and `file`. Without the variable it writes to
   `scratch/pi-run/escalations/`, with a WARNING.
2. Appends one line to the document's pipeline log. The line never contains `stage:`, so `pipeline_state.log_stages()` cannot
   mistake it for a stage entry.
3. Prints the message to send with the `pi_messenger` tool to `PI_WAVE_COORDINATOR`:
   `ESCALATION <doc> <stage> <kind> <action>: <summary> [file: <path>]`. With `--action stop` it then prints `Now stop: reply
   with your final report and end.` Without a coordinator it says to send nothing; the record is the escalation.

### Launcher and wave runner

- **`--coordinator-name NAME`** (`launch_translate_video.py`, passed through by `run_wave.py`):
  - `pi_messenger` is no longer excluded; `subagent`, `subagents_enable` and `fork` still are.
  - The agent gets `PI_AGENT_NAME=w-<slug prefix>-<6 hex>`, at most 24 characters. pi-messenger accepts only names matching
    `^[a-zA-Z0-9_][a-zA-Z0-9_-]*$` (`isValidAgentName` in `~/.pi/agent/npm/node_modules/pi-messenger/lib.ts`, version 0.15.2).
  - It also gets `PI_WAVE_COORDINATOR=NAME`.
  - `PI_MESSENGER_DIR` is `--messenger-dir`, or unset. Unset means pi-messenger's default `~/.pi/agent/messenger`
    (`index.ts`: `process.env.PI_MESSENGER_DIR || join(homedir(), ".pi/agent/messenger")`), which an interactive coordinator
    started without the variable also uses.
- **Messenger config written into the worktree** (merged into any existing file):
  - `.pi/pi-messenger.json`: `{"autoRegister": true, "scopeToFolder": false}`. `autoRegister` joins the mesh at startup with
    no model call ([interactive test, A5](../../research/pi-interactive-delegation-and-messaging-test.md#a-pi-messenger-auto-join-at-startup)).
    `scopeToFolder` defaults to false (`config.ts`); it is written explicitly because the coordinator runs in a different
    folder.
  - `.pi/messenger/crew/config.json`: `{"coordination": "moderate", "messageBudgets": {"minimal": 5, "moderate": 5, "chatty": 5}}`.
    pi-messenger reads the send budget as `crewConfig.messageBudgets[crewConfig.coordination]` (`handlers.ts`, the `send`
    handler). `loadCrewConfig` reads it from `<cwd>/.pi/messenger/crew/config.json` (`crew/utils/config.ts`), not from
    `pi-messenger.json`. The same file location was found for `concurrency` in the
    [claim tests (M7)](../../research/pi-subagents-and-messenger-claim-tests.md); the budget cap itself was verified there
    (M8). The budget of 5 per worker is a choice.
- **Delivery.** A DM reaches the recipient at its next tool boundary, not as an interrupt
  ([claim tests, M2](../../research/pi-subagents-and-messenger-claim-tests.md)). An incoming DM wakes an idle interactive
  session into a new, paid model turn ([interactive test, T5](../../research/pi-interactive-delegation-and-messaging-test.md)).
- **Every launch**, with or without a coordinator, passes the agent:
  - `PI_WAVE_ESCALATION_DIR`: `--escalation-dir`, default `<out-dir>/escalations`, made absolute, in the main checkout;
  - `PI_WAVE_RUN_ID`: the PipelineRun id;
  - `PI_WAVE_CHUNK_STAGE`: the document's own chunk stage id -- every telemetry chunk/translated-chunk write
    (`revise_*`, `mark_*`, `update_document_chunk`, `flag_*`, `save/persist`) then refuses a target that belongs to any
    OTHER stage (a mistyped id fails loudly instead of silently editing another document: a worker once transposed two
    digits and excluded 5 chunks of a different video before noticing; wiki/log/2026-W40.md, 2026-10-03);
  - the prompt placeholders `{{COORDINATOR}}` (the name, or `none`) and `{{ESCALATION_DIR}}`.
- **Blocked.** After the agent exits, the launcher reads the records of this document and this run id.
  - At least one with `action: stop` makes the run **blocked**: the PipelineRun is `failed`, `result_summary.launcher.status`
    is `blocked` with the escalations, `summary.json` `status` is `blocked` (distinct from `failed`), and there is no
    server-side regenerate.
  - `continue` records are kept in `summary.json` and `result_summary`.
  - Records from an older run id never block a new run.
- **`run_wave.py`**:
  - Reports blocked documents in their own `## Blocked` section of `wave-summary.md`, with the stop escalations and what
    they need.
  - A re-run skips them (`blocked_previous`, the entry is kept) unless `--retry-blocked` is given; that relaunches them with
    the launcher's `--resume` once the coordinator has fixed the cause.
  - `--stop-file PATH` (default `<out-dir>/STOP`): while the file exists, no new document is launched, and running ones
    finish. The coordinator halts the wave with `touch`.
- **Coordinator command.** At wave start (dry run included), with `--coordinator-name`, it prints the command to start the
  coordinator, from the main checkout:

  ```
  PI_AGENT_NAME=<name> pi --provider deepseek --model deepseek-v4-pro --thinking max
  ```

  It also prints how to join the mesh (ask the session to call `pi_messenger` `join`, or put `autoRegister: true` in the main
  checkout's `.pi/pi-messenger.json`).
  - `max` is the highest level `pi --help` lists (`off, minimal, low, medium, high, xhigh, max`; pi 1.0.0, no model call).
  - deepseek-v4-pro's `thinkingLevelMap` in `~/.pi/agent/models-store.json` maps only `high` and `max`, so `xhigh` is not a
    level of this model.
  - Pi exposes `xhigh` and `max` "only when supported by the selected model" (pi `docs/rpc-commands.md`).
  - The coordinator is an interactive, separately billed deepseek-v4-pro session that the user starts and watches; every
    escalation message costs it a turn.

**Real-data check** (read-only, `--no-retry-count`, 2026-10-02 about 22:10 CEST, my own run):

- `video/a-basket-case-acts-9-20-31-a-sermon-by-r-c-sproul` (done, translated 2026-09-21):
  - PASS: `curate`, `chunk_and_clean`, `translation` (272/272), `assemble`.
  - FIX on `stt_verification` and `review`: no dispositions file (STT worklist 91 rows, review worklist 2 rows).
  - FIX on `gates`: 1 Segond `DIFFERS` at cue 224 and 1 `space_before_punct` at cue 237. The document predates the gates.
  - `final`: FIX on those three stages; all five log entries present.
- `video/abiding-love-loved-by-god-with-r-c-sproul` (untranslated):
  - `curate` FIX: 180/180 included chunks have no `sequence_index`.
  - `stt_verification` FIX: curate fails, 53 worklist rows undisposed, status `none`.
  - Every later stage FIX: no log, no translate stage, no `.fr.md`.
- A doc id with no chunk stage gives ESCALATE (`data_problem`) and prints the `escalate.py` command.

## Tests

[tests/test_pi_wave.py](../../../tests/test_pi_wave.py) runs without network, model or paid call. It uses three fakes: in-memory
telemetry, a fake `pi` executable on `PATH` that writes two synthetic session JSONL files, and a throwaway git repo. It covers:

- the formula and its wave margin;
- condensed mode's `pi` arguments;
- the sum over several session files;
- refusal on several chunk stages;
- `--resume` placeholders;
- success, timeout, cost-cap kill, incomplete stage, and `pi` failing to start (each ends with the right run status and
  teardown);
- stale merged and unmerged branches;
- the untracked-ADF copy;
- the dry run creating nothing;
- the wave's dry run without consent, its cumulative cap, resume, and concurrency limit;
- the agent name; `pi_messenger` excluded only without a coordinator; the messenger config merge; the agent's environment and
  the `{{COORDINATOR}}`/`{{ESCALATION_DIR}}` placeholders; a `continue` escalation and an older run's `stop` not blocking;
  a `stop` escalation blocking the run (no regenerate); the coordinator dry run;
- the wave's blocked section, the skip without `--retry-blocked` and the `--resume` relaunch with it, the stop file (before
  and during a wave), and the printed coordinator command.

[tests/test_pi_stage_check.py](../../../tests/test_pi_stage_check.py) covers every stage's PASS/FIX/ESCALATE paths, the
retry-to-escalate counter and its reset, the dispositions format, coverage and stale lines, the gate exit mapping, the
assemble mismatch, `final`, `--json`, and `escalate.py`'s record, log line and message, with and without its environment.

## Not done

- **SermonIndex documents** still have no chunk stage, so the runner reports them as `no_chunk_stage`. The idempotent chunk
  store for any source (audit C1) is not built.
- **The prompt text** for the new placeholders, the condensed context files, and the skill fixes (audit A5, A7 and A8) are
  separate work.
- **`deepseek-flash` at low thinking (the default worker tier everywhere above) is only confirmed on video/sermon
  content — untested on dense written documents.** Every real wave measured here (ten-sermon wave, sproul-100,
  sproul-200) translated spoken, conversational sermon transcripts. Whether the same low-thinking tier stays faithful
  on formally structured theological prose (the Westminster Confession of Faith, Westminster Larger Catechism,
  Heidelberg Catechism — ingested `adf/`, 2026-10-11, English only, not yet translated) is open. Run a small
  side-by-side test (a handful of chunks at `deepseek-flash` low thinking vs. a stronger tier) and an independent
  `verify-translation` read before committing a real document-translation wave to this tier — see CLAUDE.md's
  "Working rules" for the same note.

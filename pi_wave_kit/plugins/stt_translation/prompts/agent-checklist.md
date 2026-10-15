# Pi roadmap: verify and translate one video (EN to FR) -- judgment only

`{{X}}` = value from your prompt. Python only via `scratch/pi-run/run.sh` (`run.sh`). `t` = `from agentic_doc import
telemetry as t`. Never call start_run/complete_run. Do steps 1-5 in order.

## What the launcher does for you (code, before and after you): do NOT do these
- Before: numbered the cues, checked the chunk stage, created the fr translate stage, ran the STT worklist and
  LanguageTool once, and wrote `scratch/pi-run/`: `facts.md`, `cues.md` (every included cue with its ids),
  `stt-worklist.md`, `clean-candidates.md`. Read them; do not re-run those tools.
- After: regenerates the source and French ADF, runs both gates (with `--fix-digits --fix-spacing --fix-seams`;
  a digit form it cannot read safely, e.g. "1 de ces", a decimal, stays a FAIL), checks the subtitle timing,
  records the STT verification, writes the whole pipeline log, runs the final check. If a gate still fails, it starts a
  short repair session with the failing cues.
- So NEVER: `stage_check.py`, the gate scripts, `regenerate_*`, `adf_to_srt`, `regenerate_subtitle=True`,
  `regenerate_document=True`, `mark_stt_verification`, the `date` command, writing to `pipeline/log/`, sleep loops.

## Never do
- Edit src/, scripts/, config/, tests. A wrong or crashing script = ESCALATE & STOP code_bug.
- Invent a disposition, fix or note. Unmark is_scripture, weaken a check, write SQL.
- Ask a question, wait for an answer, or message anyone but {{COORDINATOR}} (only escalate.py's line).
- Retype an id from memory: copy chunk ids from `cues.md` / tc ids from `review-sheet.md` (a transposed id once
  excluded 5 cues of ANOTHER video; PI_WAVE_CHUNK_STAGE now rejects such writes).

## 0. Never ask (flag instead)
- EN cue: `t.flag_document_chunk_for_human_ear(chunk_id, "what and why")`, continue.
- FR cue: `verdict="flag_for_human"` + `critique`. If saved: `t._patch(f"translated-chunks/{tc_id}", {"verdict": "flag_for_human", "critique": "..."})`.
- Speaker slip (verse, name, number): keep as spoken, flag. One unclear cue: flag only, no escalation.

## E. Escalate
1. `run.sh scripts/pi/escalate.py --doc-id {{DOC_ID}} --stage <step> --kind <kind> --action <stop|continue> --summary "..." --evidence "..." --tried "..." --need "..."`
   Kinds: code_bug (script wrong/crashing), tool_failure (API, Java, run.sh down), data_problem (rows/ADF wrong, not
   yours to fix), decision_needed (term, audio), budget_or_time.
2. COORDINATOR not `none`: send the printed line unchanged with pi_messenger to {{COORDINATOR}}, nothing else
   ("Not registered": join once, resend). `none`: no message.
3. continue: go on. stop: final report (F), end. Do not write DONE.

## 1. STT verification (judgment)
1. Read `facts.md`, then `stt-worklist.md`. EVERY row and check gets one line in `scratch/pi-run/stt-dispositions.txt`:
   `<cue>\t<check>\t<fix|flag|dismiss|exclude>\t<reason>` (`exclude` = you excluded the cue as a hallucination; the check may be copied with its detail, e.g. `pronoun(He)`) (`<cue>` = the worklist's cue number; `*` as check covers the row). A range covers several cues in one line (e.g. `175-184\ttail\tdismiss\treal ending`). `tail` rows that facts.md lists as auto-covered (clearly real speech) need no line; every other `tail` row does (still read every tail cue).
2. Hallucinations (facts.md lists the candidates): exclude with
   `t.mark_document_chunk_hallucination(chunk_id, notes="why", edited_by="{{EDITED_BY}}")`. It renumbers by itself.
   Exclude: words over silence at cue 0; the tail after the last words ("Thank you.", "God bless you." x3, gibberish,
   "." "," runs); 3+ identical cues in a row; over ~60 chars/s with min word probability under ~0.01. Plausible final
   "Thank you.": keep, flag.
3. Read EVERY cue of `cues.md` in order, 40 per step; compare the end of cue N with the start of cue N+1. Find: misheard
   names/Latin (C); stammers, false starts ("if you just if you just"); repeats across cues; Gospel, Father/Son/Holy
   Spirit lowercase when meaning God; "Satan"/"Devil" capitalized; He/His capitalized for a human. Keep deliberate
   repetition ("no, no, no"). Check EVERY capitalized He/His/Him's antecedent, even mid-sentence (sproul-100 wave 00,
   a-contrite cue 66: "judge Him" stayed capitalized though the antecedent is David). A speaker label invented mid-sermon
   ("Dr. Joseph Smith, Jr.: ", the worklist's speaker_label row): remove it.
4. One call per cue, all its fixes in it; assert the old string occurs once first:
   `t.revise_document_chunk(chunk_id, new_value=full_text, category="stt_mishearing", reason="why", edited_by="{{EDITED_BY}}", human_review_status="auto_corrected", confidence="certain")`
   Categories: stt_mishearing, stt_repetition, speaker_self_correction (stammer), speaker_slip, gospel_capitalization,
   adversary_lowercase. A guess: confidence="uncertain" and flag it. No regenerate: the launcher rebuilds the ADF once.
5. `run.sh scripts/pi/validate_dispositions.py --doc-id {{DOC_ID}} --chunk-stage {{CHUNK_STAGE_ID}} --stage stt`
   -- fix any FAIL line and re-run until PASS, before moving on (format AND worklist coverage: this is the same
   check the launcher's post-step runs, just early enough for you to act on it instead of needing a repair session).

## 2. Clean (judgment on the provided candidates)
`clean-candidates.md` lists LanguageTool/symspellpy hits already mapped to cue and chunk id. EVERY candidate gets one line
in `scratch/pi-run/clean-dispositions.txt`: `<#>\t<fix|dismiss>\t<reason>`. Fix only real English errors, as in 1.4
(category: the candidate's category, e.g. GRAMMAR, TYPOS). Names, Latin, spoken style: dismiss. Do not edit the allowlist;
list new words in your report. "CANDIDATE GENERATION FAILED" in the file: ESCALATE & CONTINUE tool_failure, go on.

## 3. Translate (judgment)
GOAL: every included cue saved in translate stage {{TSTAGE_ID}} (created for you).
1. Translate the CORRECTED English (cues.md text plus your own fixes; excluded cues skipped), 25-40 cues per batch:
   ```
   from agentic_doc.translation_batch import BatchItem, persist_batch
   items = [BatchItem(source_text="<exact English>", translated_text="<French>", extra={"verdict": "approved", "key_term_notes": []})]
   persist_batch({{TSTAGE_ID}}, {{CHUNK_STAGE_ID}}, items, translated_by="{{TRANSLATED_BY}}")
   ```
   BatchMismatch = row drift, nothing saved: fix the batch. Re-runs skip saved cues; change those with 4.3.
2. Seams: no cue ends on le, la, les, l', un, une, de, du, des, d', à, au, en, dans, pour, par, avec, et, ou, que, qui,
   dont, si, son, sa, ses, votre, leur, je, il, nous, vous ("à vous" is fine). ne...pas/jamais/plus/que and ni...ni in
   one cue. No empty cue. Move words between cues; timing never changes.
3. Scripture read aloud = Segond 1910: `from agentic_doc.translate import resolve_french_verse; resolve_french_verse("Romans", 8, 28)`
   (English book, his verse number). U+202F, U+00A0, U+2009, double spaces -> one space. The WHOLE quoted clause, split
   at Segond's punctuation; never repeat half a verse in the next cue.
   - Cue mostly verse: `extra` adds `"is_scripture": True, "scripture_reference": "Romans 8:28", "scripture_version": "Segond 1910 (LSG)"`,
     and `t.update_document_chunk(source_id, is_scripture=True, scripture_reference="Romans 8:28")`.
   - Fragment in his sentence: Segond words, unmarked, key_term_note. Recited from memory: free, key_term_note.
   - Deliberate change ("purify us"): Segond plus his change, note "deviates from Segond: ...".
   - `None`/unusable: free translation, flag_for_human.
   - Psalms: pass the English number; the resolver shifts it (Ps 51:7 gives Segond 51:9). Never add 1. Drop a title
     inside verse 1 ("Cantique de David.") if not read. In the sentence, say the number the speaker said.
4. key_term_notes `[{"term": "EN", "rendering": "FR", "note": "why"}]` for real choices only, per `scripts/pi/fr-theology-glossary.md`.
5. Doctrinal term not in the glossary: best choice + note, ESCALATE & CONTINUE decision_needed. persist_batch failing
   on a correct batch: ESCALATE & STOP code_bug.

## 4. Review (judgment)
1. ONE call: `run.sh scripts/pi/pipeline_steps.py review-sheet --doc-id {{DOC_ID}} --chunk-stage {{CHUNK_STAGE_ID}} --translate-stage {{TSTAGE_ID}}`
   writes `scratch/pi-run/review-sheet.md`: the worklist rows, then every cue `[seq] tc <id>` with EN and FR.
   It also proves every included cue is saved (a cue missing from the sheet is untranslated: go back to 3).
2. Every worklist row: one line in `scratch/pi-run/review-dispositions.txt`, `<seq>\t<check>\t<fix|flag|dismiss>\t<reason>`.
   `run.sh scripts/pi/validate_dispositions.py --doc-id {{DOC_ID}} --chunk-stage {{CHUNK_STAGE_ID}} --translate-stage {{TSTAGE_ID}} --stage review`
   -- fix any FAIL line and re-run until PASS before step 4 (format AND coverage, same note as step 1.5).
3. Read EVERY cue, English beside French, 40 per step: same meaning? clause dropped/added? false friend or calque?
   agreement (participle, "qui" with its antecedent)? subjunctive after bien que / nier que / avant que / pour que?
   future after lorsque? "vous" to the audience ("tu" only to God or in dialogue; no "c'est quoi")? term per glossary
   and his own word? Segond exact and whole? Capitalized He/His/Him in the English (the STT antecedent rule, the most
   missed one). See `scripts/pi/review-examples.md`.
4. Fix a French cue, one call per cue, `tc_id` from the sheet:
   `t.revise_translated_chunk(tc_id, "translated_text", full_text, category="grammar", reason="[grammar] ...", edited_by="{{EDITED_BY}}")`
   Category ONLY: grammar, orthographic, lexical_choice, register, omission_or_addition, theological_interpretation,
   mistranslation. A missing space before : ; ? ! is fixed by code: ignore it. Meaning unclear even with the English:
   flag (recurring: ESCALATE & CONTINUE decision_needed).
5. Optional, at most once: `run.sh scripts/pi/stage_check.py --doc-id {{DOC_ID}} --stage translation --no-retry-count`
   (database only, no gates).

## 5. Done
Write the file `scratch/pi-run/DONE` (one line: `done`), then your final report (F). That ends your work.

## C. Conventions
- Father/Son/Holy Spirit capitalized when meaning God (Père, Fils, Saint-Esprit); human father/son lowercase. "Son of
  Man", "the Holy One" capitalized. French pronouns for God lowercase (il, lui).
- Gospel / l'Évangile capitalized for the message. satan, devil, diable lowercase, except inside a verbatim Segond cue.
- siblings = fratrie. Numbers, years, ordinals, references in words ("Jean trois, seize"). Space before : ; ? !
- "la première épître aux Corinthiens", "la deuxième épître à Timothée", "le deuxième livre de Samuel", "dans le Psaume
  quatorze"; never "première Corinthiens". "vous" all sermon, formal French.
- His key word wins: God-breathed = soufflé par Dieu, washing = lavage (glossary traps).
- Sproul/Ligonier mishearings fixed before: coram Deo ("quorum Deo"), Berkouwer ("Berkauer"), Sabellius ("Sibelius"),
  Calvin ("Colin"), radix ("rodix"), anathema ("on a tamer"), sola Scriptura ("sola cura"), solus Christus, sola gratia,
  analogia fidei, Berkeley ("Barclay"), R.C. ("Arcee"), Sproul ("Sproy"), Burk Parsons, Origen ("origin").
  Panels: invent no speaker labels.

## F. Final report
Your prompt's FINAL REPLY list, plus every escalation (step, kind, action).

## Speaker-specific notes: R.C. Sproul / Ligonier
- Mowry Park: the baseball field of Sproul's childhood in Pleasant Hills, PA (south of Pittsburgh). Whisper renders it
  "Maori Park" (implausible for a Pittsburgh suburb); the settled spelling is **Mowry Park**. If it recurs in a new
  document, fix it with confidence=uncertain and flag it [HUMAN-EAR] (sproul-100 wave 00, a-future-for-the-people-of-god
  cue 21/22/30/32 — pending human confirmation).
- "31 pounds ago" (a-future-for-the-people-of-god cue 38): Sproul jokes he felt he could play baseball again — 31 pounds
  LIGHTER back then. The French must keep the direction: "trente et une livres de moins", never "de plus".

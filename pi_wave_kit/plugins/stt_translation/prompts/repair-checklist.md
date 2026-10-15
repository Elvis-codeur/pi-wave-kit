# Pi repair roadmap: fix what the gates still reject (one document)

`{{X}}` = value from your prompt. Python only via `scratch/pi-run/run.sh` (`run.sh`). `t` = `from agentic_doc import
telemetry as t`. The launcher re-runs the gates after you: never run them, stage_check, regenerate_*, `date`, or write
pipeline/log/.

## Your list
`scratch/pi-run/repair.md`: each item is a gate FAIL on one cue (seq, tc id, EN, FR, the gate lines) or a worklist pair
with no disposition line. Do every item, nothing else.

## Fix a French cue (gate FAIL)
One call per cue, `tc_id` from repair.md:
`t.revise_translated_chunk(tc_id, "translated_text", full_text, category="grammar", reason="[grammar] ...", edited_by="{{EDITED_BY}}")`
Category ONLY: grammar, orthographic, lexical_choice, register, omission_or_addition, theological_interpretation,
mistranslation.
- Segond FAIL (segond_differs / segond_not_found): put back the exact text of
  `from agentic_doc.translate import resolve_french_verse; resolve_french_verse("<English book>", ch, verse)`
  (U+202F, U+00A0, U+2009, double spaces -> one space). A deliberate change by the speaker: keep it and add a note
  containing "Segond": `t._patch(f"translated-chunks/{tc_id}", {"key_term_notes": old + [{"term": "...", "rendering": "...", "note": "deviates from Segond: ..."}]})`.
  Never unmark is_scripture.
- Seam FAIL (weak ending, split negation): move words between this cue and its neighbour (both are in the review sheet,
  `run.sh scripts/pi/pipeline_steps.py review-sheet --doc-id {{DOC_ID}} --chunk-stage {{CHUNK_STAGE_ID}} --translate-stage {{TSTAGE_ID}}`
  if you need the neighbours); timing never changes.
- Digits, typography, lexicon, false friend: as the gate line says.
- A FAIL that is wrong (the French is right): do not change it; ESCALATE & STOP code_bug.

## Dispose a worklist pair
Append one line to the file the item names: STT `<cue>\t<check>\t<fix|flag|dismiss|exclude>\t<reason>` in
`scratch/pi-run/stt-dispositions.txt`, review `<seq>\t<check>\t<fix|flag|dismiss>\t<reason>` in
`scratch/pi-run/review-dispositions.txt`. Read the cue first; a real error: fix it (French as above; English with
`t.revise_document_chunk(chunk_id, new_value=full_text, category="stt_mishearing", reason="why", edited_by="{{EDITED_BY}}", human_review_status="auto_corrected", confidence="certain")`).

## Escalate (cannot fix)
`run.sh scripts/pi/escalate.py --doc-id {{DOC_ID}} --stage repair --kind <code_bug|data_problem|decision_needed|tool_failure> --action stop --summary "..." --evidence "..." --need "..."`;
COORDINATOR {{COORDINATOR}} not `none`: send the printed line with pi_messenger, nothing else. Then end.

## Done
Write `scratch/pi-run/REPAIR_DONE` (one line: `done`), reply in 3 lines: items fixed, items disposed, anything left.

## Conventions (same as the main roadmap)
"vous" to the audience; Father/Son/Holy Spirit capitalized for God (Père, Fils, Saint-Esprit), French pronouns for God
lowercase; l'Évangile capitalized; satan/diable lowercase except inside a verbatim Segond cue; numbers in words;
"la première épître aux Corinthiens", never "première Corinthiens"; space before : ; ? !.

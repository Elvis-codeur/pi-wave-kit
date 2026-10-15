# stt_translation plugin

The real, production-tested STT-verification + theological-document-translation pipeline this whole
library was extracted from, packaged as an optional plugin — not baked into `pi_wave_kit`'s core, which
stays domain-agnostic. This is "data you add to the library for a specific case," per the project's own
description of what this should be.

## What's here, and where it came from

| File | What it is | Ported how |
|---|---|---|
| `prompts/translate-video-prompt.md` | The real system prompt given to each headless translation worker | Verbatim copy, unmodified |
| `prompts/agent-checklist.md` | The real step-by-step procedure ("Pi roadmap") workers followed | Verbatim copy, unmodified |
| `prompts/repair-prompt.md` / `repair-checklist.md` | The real short follow-up session run when a gate still fails after the main pass | Verbatim copy, unmodified |
| `prompts/fr-theology-glossary.md` | The real EN→FR Reformed-theology glossary, 173 lines, every entry sourced (a real Segond 1910 verse, a corpus-frequency count, or a specific past correction) | Verbatim copy, unmodified |
| `prompts/review-examples.md` | 36 real fixes from an independent review of a real 10-sermon production wave (108 real content edits over 6,583 cues) | Verbatim copy, unmodified |
| `pipeline_steps.py` | Cue/chunk numbering, dispositions-file parsing, worklist/candidate rendering | Ported as pure functions (dicts/strings in, dicts/strings out) — zero changes to the logic itself |
| `stage_check.py` | The 8 concrete PASS/FIX/WARN/ESCALATE conditions (curate, stt_verification, chunk_and_clean, translation, gates, assemble, review, final) | Ported faithfully, generalized against a `DocContext` Protocol instead of a hard import of the original project's Django API |

**Why the prompts/glossary/examples are verbatim but the code is generalized**: the prompts and glossary
ARE the actual knowledge this pipeline accumulated (real sourced terminology choices, real confirmed
mistranslation patterns) — rewriting them would lose exactly the content that makes them valuable. The
code, by contrast, calls into one specific project's database/ORM; porting it faithfully meant
separating what was genuinely generic (numbering, text parsing, rendering — real pure functions,
unchanged) from what needed a real database behind it (fetching chunks, running gate scripts) — the
latter is expressed as a documented interface (`stage_check.DocContext`) instead, so this plugin works
for any project with a similar shape, not only the one it came from.

## Using it

```python
from pi_wave_kit.plugins.stt_translation import pipeline_steps, stage_check

# Pure functions, no setup needed:
plan = pipeline_steps.numbering_plan(my_chunks)
entries, errors = pipeline_steps.parse_dispositions(my_dispositions_file)

# Stage checks need your own DocContext implementation (see stage_check.py's module docstring
# for the exact Protocol and a worked example):
conditions = stage_check.evaluate_one(my_ctx, "curate")
from pi_wave_kit.stage_check import render
print(render(conditions))
```

To actually run workers against the real prompts, read them as plain text and fill in the `{{DOUBLE_BRACE}}`
placeholders yourself (doc id, chunk stage id, translate stage id, your agent identity, coordinator
name, escalation directory) — they're plain string templates, no templating engine needed:

```python
from importlib import resources
template = (resources.files("pi_wave_kit.plugins.stt_translation") / "prompts" / "translate-video-prompt.md").read_text()
prompt = template.replace("{{DOC_ID}}", my_doc_id).replace("{{CHUNK_STAGE_ID}}", str(my_chunk_stage_id))  # ...
```

## What you still have to wire up

This plugin does NOT depend on `agentic_doc` (it isn't published as an installable package, and
`pi_wave_kit` is meant to be usable without it) — so it does not fetch real chunks, run real gate
scripts, or know what a real `DocumentChunk` looks like. You supply:
- A `DocContext` implementation (see `stage_check.py`'s module docstring for the exact shape).
- A gate-runner callable per gate (anything that returns `.returncode`/`.stdout`/`.stderr`).
- An `adf_roundtrip` callable for the `assemble` stage's structural-integrity check.

If you ARE using `agentic_doc` (the project this came from), the real adapter wiring these onto its
actual API lives in that project's own `scripts/pi/stage_check.py` and `scripts/pi/pipeline_steps.py` —
not duplicated here, since it would immediately drift from whichever one gets updated first.

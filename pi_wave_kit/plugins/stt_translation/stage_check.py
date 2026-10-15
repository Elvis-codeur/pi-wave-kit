"""The 8 concrete stage-check conditions from agentic-doc-treatement's real scripts/pi/stage_check.py
(curate, stt_verification, chunk_and_clean, translation, gates, assemble, review, final), ported
faithfully and generalized against a documented Protocol instead of a hard import of `agentic_doc`.

This is the DOMAIN-SPECIFIC content `pi_wave_kit.stage_check` (the core library) deliberately does not
ship -- these 8 conditions are specific to one document-translation pipeline's actual data model (chunk
stages, translate stages, Scripture-fidelity and mechanics gates, ADF files). Shipped here, as a
plugin, so a project with the SAME or a similar data model doesn't have to re-derive the real,
production-tested thresholds and wording from scratch -- but it still has to write the small adapter
that implements `DocContext` against its own real functions (agentic_doc's own, or an equivalent).

## What you have to wire up

```python
class MyContext:
    doc_id: str
    root: Path            # repo root, for making paths relative in messages
    log: Path             # pipeline/log/<source>/<slug>.pipeline.md -- or wherever yours lives
    adf: Path             # source-language ADF file
    fr_adf: Path          # target-language ADF file

    def chunk_stage(self) -> dict: ...          # {"id": int, ...}
    def translate_stage(self) -> dict | None: ...  # {"id": int, "method": str, ...} or None if none exists yet
    def included(self) -> list[dict]: ...       # included, non-superseded chunks: [{"id", "sequence_index", ...}]
    def translated(self) -> dict[int, dict]: ... # {source_chunk_id: {"translated_text": str, ...}}
    def log_stages(self) -> set[str]: ...        # stage names already present in the pipeline log
    def stt_worklist_rows(self) -> list[tuple[int, list[str]]]: ...  # (cue, [check, ...]) pairs still to dispose
    def review_worklist_rows(self) -> list[tuple[int, list[str]]]: ...
    def stt_dispositions_path(self) -> Path: ...
    def review_dispositions_path(self) -> Path: ...
    def stt_auto_covered(self) -> set[int]: ...  # cues code already cleared without a worker line
    def human_ear_flags(self) -> list: ...        # chunks flagged for a human ear
    def stt_verification_status(self) -> str | None: ...

gates = [
    ("scripture_fidelity_gate", lambda ctx: run_my_scripture_gate(ctx), "restore the exact reference text..."),
    ("mechanics_gate", lambda ctx: run_my_mechanics_gate(ctx), "fix each FAIL cue with your revise function..."),
]
adf_roundtrip = lambda ctx: my_adf_to_srt_check(ctx)  # -> (ok: bool, detail: str, is_code_bug: bool)
```

Then call `evaluate_all(ctx, gates=gates, adf_roundtrip=adf_roundtrip)` to get every stage's conditions,
or call the individual `check_*` functions directly for one stage."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Protocol

from pi_wave_kit.stage_check import Condition, escalate, fix, passed, reduce, warn

HUMAN_EAR_WARN_MIN = 5
HUMAN_EAR_WARN_FRACTION = 0.05
STAGES = ("curate", "stt_verification", "chunk_and_clean", "translation", "gates", "assemble", "review", "final")
FINAL_LOG_STAGES = ("chunk_and_store", "stt_verification", "chunk_and_clean", "translation", "translation_verification")


class DocContext(Protocol):
    doc_id: str
    root: Path
    log: Path
    adf: Path
    fr_adf: Path

    def chunk_stage(self) -> dict: ...
    def translate_stage(self) -> dict | None: ...
    def included(self) -> list[dict]: ...
    def translated(self) -> dict[int, dict]: ...
    def log_stages(self) -> set[str]: ...
    def stt_worklist_rows(self) -> list[tuple[int, list[str]]]: ...
    def review_worklist_rows(self) -> list[tuple[int, list[str]]]: ...
    def stt_dispositions_path(self) -> Path: ...
    def review_dispositions_path(self) -> Path: ...
    def stt_auto_covered(self) -> set[int]: ...
    def human_ear_flags(self) -> list: ...
    def stt_verification_status(self) -> str | None: ...


def _listed(items, limit: int = 8) -> str:
    items = list(items)
    shown = ", ".join(str(x) for x in items[:limit])
    return shown + (f" (+{len(items) - limit} more)" if len(items) > limit else "")


def _disposition_conditions(rows: list[tuple[int, list[str]]], path: Path, rel_hint: str, auto: set | frozenset = frozenset()) -> list[Condition]:
    from .pipeline_steps import uncovered

    gaps = uncovered(rows, path, auto)
    if not rows:
        return [passed("worklist_covered", "no worklist rows for this stage")]
    if gaps:
        return [fix("worklist_covered", f"{len(gaps)} (cue, check) pair(s) with no disposition line: {_listed(gaps)}",
                    f"append one line per pair to {rel_hint} (<cue>\\t<check>\\t<fix|flag|dismiss>\\t<reason>)")]
    return [passed("worklist_covered", f"all {len(rows)} worklist row(s) disposed")]


def check_curate(ctx: DocContext) -> list[Condition]:
    cs = ctx.chunk_stage()
    included = ctx.included()
    if not included:
        return [escalate("chunks_present", f"chunk stage {cs['id']} has no included, non-superseded chunk", "data_problem")]
    no_index = [c for c in included if c.get("sequence_index") is None]
    out = []
    if no_index:
        out.append(fix("sequence_index_set", f"{len(no_index)} of {len(included)} included chunks have no sequence_index",
                       "set sequence_index 0..N-1 in original_index order BEFORE any exclusion"))
    else:
        out.append(passed("sequence_index_set", f"all {len(included)} included chunks have a sequence_index"))
    indices = sorted(c["sequence_index"] for c in included if c.get("sequence_index") is not None)
    if not no_index and indices != list(range(len(indices))):
        dupes = sorted({i for i in indices if indices.count(i) > 1})
        gaps_list = sorted(set(range(max(indices) + 1)) - set(indices))
        out.append(fix("included_contiguous", f"included sequence_index values are not 0..{len(indices) - 1}"
                       + (f", duplicates {_listed(dupes)}" if dupes else "") + (f", gaps {_listed(gaps_list)}" if gaps_list else ""),
                       "renumber the included chunks 0..N-1 in reading order (exclusions renumber by themselves)"))
    elif indices:
        out.append(passed("included_contiguous", f"included sequence_index runs 0..{len(indices) - 1}"))
    return out


def check_stt_verification(ctx: DocContext) -> list[Condition]:
    out = [c for c in check_curate(ctx) if c.status != "PASS"] or [passed("curate", "curate PASS")]
    rows = ctx.stt_worklist_rows()
    out += _disposition_conditions(rows, ctx.stt_dispositions_path(), "the STT dispositions file", ctx.stt_auto_covered())
    status = ctx.stt_verification_status()
    if status != "done":
        out.append(fix("stt_verification_recorded", f"stt_verification_status is {status!r}, not 'done'",
                       "after every row and cue is done, mark the chunk stage's STT verification done"))
    else:
        out.append(passed("stt_verification_recorded", "stt_verification_status done"))
    flags = ctx.human_ear_flags()
    limit = max(HUMAN_EAR_WARN_MIN, HUMAN_EAR_WARN_FRACTION * len(ctx.included()))
    if len(flags) > limit:
        out.append(warn("human_ear_flags", f"{len(flags)} cues flagged for the human ear (more than {limit:.0f}): name them in the log entry"))
    else:
        out.append(passed("human_ear_flags", f"{len(flags)} cue(s) flagged for the human ear"))
    return out


def check_chunk_and_clean(ctx: DocContext) -> list[Condition]:
    rel = ctx.log.relative_to(ctx.root) if ctx.log.is_relative_to(ctx.root) else ctx.log
    if not ctx.log.is_file() or "chunk_and_clean" not in ctx.log_stages():
        return [fix("log_chunk_and_clean", f"{rel} has no chunk_and_clean stage entry",
                    f"append the chunk_and_clean entry (date, stage, status, counts) to {rel}")]
    return [passed("log_chunk_and_clean", f"{rel} has a chunk_and_clean entry")]


def check_translation(ctx: DocContext) -> list[Condition]:
    cs = ctx.chunk_stage()["id"]
    ts = ctx.translate_stage()
    if ts is None:
        return [fix("translate_stage_unique", f"no translate stage on chunk stage {cs}",
                    "create the translate stage, or reuse the existing one, and translate every included cue")]
    out = [passed("translate_stage_unique", f"translate stage {ts['id']} ({ts.get('method', '?')})")]
    included, translated = ctx.included(), ctx.translated()
    missing = [c for c in included if c["id"] not in translated]
    if missing:
        out.append(fix("all_included_translated", f"{len(missing)} of {len(included)} included chunks have no translation",
                       f"translate the {len(missing)} missing included chunks into stage {ts['id']}"))
    else:
        out.append(passed("all_included_translated", f"all {len(included)} included chunks translated"))
    by_id = {c["id"]: c for c in included}
    empty = [by_id[sid] for sid, t in translated.items() if sid in by_id and not (t.get("translated_text") or "").strip()]
    if empty:
        out.append(fix("no_empty_translation", f"{len(empty)} empty translated chunk(s)", "give each empty chunk its real translation"))
    else:
        out.append(passed("no_empty_translation", "no empty translated chunk"))
    return out


def check_gates(ctx: DocContext, gates: list[tuple[str, Callable[[DocContext], object], str]]) -> list[Condition]:
    """Each gate tuple is (id, run_fn, fix_hint). run_fn(ctx) must return an object with `.returncode`,
    `.stdout`, `.stderr` (e.g. subprocess.CompletedProcess) -- the SAME shape your own gate-running code
    already produces if it shells out to a script, per the original project's convention."""
    out = []
    for gate_id, run_fn, how in gates:
        try:
            proc = run_fn(ctx)
        except Exception as exc:
            out.append(escalate(gate_id, f"gate did not run: {type(exc).__name__}: {exc}", "tool_failure"))
            continue
        lines = (proc.stdout or "").strip().splitlines()
        last = lines[-1] if lines else ""
        if "Traceback (most recent call last)" in (proc.stderr or "") or proc.returncode not in (0, 1):
            err = ((proc.stderr or "").strip().splitlines() or ["no stderr"])[-1]
            out.append(escalate(gate_id, f"gate crashed (exit {proc.returncode}): {err[:200]}", "tool_failure"))
        elif proc.returncode == 1:
            fails = [ln.strip() for ln in lines if ln.startswith("FAIL")]
            out.append(fix(gate_id, f"{last} -- {_listed(fails, 5)}", how))
        else:
            warns = [ln.strip() for ln in lines if ln.startswith("WARN")]
            out.append(warn(gate_id, f"{last} -- {_listed(warns, 5)}") if warns else passed(gate_id, last or "exit 0"))
    return out


def check_assemble(ctx: DocContext, adf_roundtrip: Callable[[DocContext], tuple[bool, str, bool]]) -> list[Condition]:
    """`adf_roundtrip(ctx)` must return (ok, detail, is_code_bug) -- your own equivalent of
    `adf_to_srt(fr, source_body_markdown=en)`: does the assembled target-language document's structure
    (cue count, ordering, timing, whatever your format's analogous invariant is) still match the
    source? `is_code_bug=True` routes a non-data failure to ESCALATE(code_bug) instead of FIX."""
    if not ctx.adf.is_file():
        return [escalate("source_adf_exists", f"{ctx.adf} does not exist", "data_problem")]
    if not ctx.fr_adf.is_file():
        return [fix("fr_adf_exists", f"{ctx.fr_adf} does not exist", "assemble/regenerate the target-language document")]
    out = [passed("fr_adf_exists", f"{ctx.fr_adf} exists")]
    try:
        ok, detail, is_code_bug = adf_roundtrip(ctx)
    except Exception as exc:
        out.append(escalate("roundtrip", f"the roundtrip check raised {type(exc).__name__}: {str(exc)[:200]}", "data_problem"))
        return out
    if ok:
        out.append(passed("roundtrip", detail or "roundtrip check passed"))
    elif is_code_bug:
        out.append(escalate("roundtrip", detail, "code_bug"))
    else:
        out.append(fix("roundtrip", detail, "re-assemble from the corrected source, then re-run this check"))
    return out


def check_review(ctx: DocContext) -> list[Condition]:
    return _disposition_conditions(ctx.review_worklist_rows(), ctx.review_dispositions_path(), "the review dispositions file")


def check_final(ctx: DocContext, *, gates: list[tuple[str, Callable, str]], adf_roundtrip: Callable) -> list[Condition]:
    out = []
    for stage in STAGES[:-1]:
        conds = evaluate_one(ctx, stage, gates=gates, adf_roundtrip=adf_roundtrip)
        result = reduce(conds)
        if result == "PASS":
            out.append(passed(f"stage_{stage}", "PASS"))
        elif result == "WARN":
            out.append(warn(f"stage_{stage}", "WARN (" + ", ".join(c.id for c in conds if c.status == "WARN") + ")"))
        elif result == "FIX":
            out.append(fix(f"stage_{stage}", "FIX (" + ", ".join(c.id for c in conds if c.action == "fix") + ")",
                           f"run the {stage} check and fix what it lists"))
        else:
            first = next(c for c in conds if c.action == "escalate")
            out.append(escalate(f"stage_{stage}", f"ESCALATE ({first.id}: {first.detail[:150]})", first.kind))
    missing = [s for s in FINAL_LOG_STAGES if s not in ctx.log_stages()]
    if missing:
        out.append(fix("log_entries", f"pipeline log lacks stage entries: {', '.join(missing)}", f"append the missing entries ({', '.join(missing)})"))
    else:
        out.append(passed("log_entries", "pipeline log has all five stage entries"))
    return out


def evaluate_one(ctx: DocContext, stage: str, *, gates: list[tuple[str, Callable, str]] = (), adf_roundtrip: Callable | None = None) -> list[Condition]:
    if stage == "curate":
        return check_curate(ctx)
    if stage == "stt_verification":
        return check_stt_verification(ctx)
    if stage == "chunk_and_clean":
        return check_chunk_and_clean(ctx)
    if stage == "translation":
        return check_translation(ctx)
    if stage == "gates":
        return check_gates(ctx, list(gates))
    if stage == "assemble":
        return check_assemble(ctx, adf_roundtrip)
    if stage == "review":
        return check_review(ctx)
    if stage == "final":
        return check_final(ctx, gates=list(gates), adf_roundtrip=adf_roundtrip)
    raise ValueError(f"unknown stage {stage!r}; expected one of {STAGES}")

"""The GENERIC, pure-function part of agentic-doc-treatement's scripts/pi/pipeline_steps.py and
stage_check.py, ported verbatim where the logic never touched agentic_doc's Django API -- pure
functions over plain dicts/strings. Everything here is immediately usable without agentic_doc
installed; the parts that DID need agentic_doc (fetching real chunks, running STT worklist generation,
LanguageTool candidates, the gate scripts) are NOT ported -- they are the calling project's job to
supply, documented in README.md's wiring table.

Why this split, not a full port: this is the "move mechanical work out of the model into code" layer
that made cheap-tier (deepseek-flash, low thinking) workers reliable in real production use (see
../../docs/pi-messenger-and-subagents-tested-claims.md section 6 for the real numbers this bought).
Shipping a plugin that only works with agentic_doc installed would make pi-wave-kit itself depend on a
project-specific library it was built to NOT depend on; shipping only the generic pieces, clearly
labeled, lets another project reuse the proven pattern against its OWN chunk/document model."""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path


# ------------------------------------------------------------------ numbering / ordering (pure dict ops)


def numbering_plan(chunks: list[dict]) -> list[tuple[int, int]]:
    """(chunk id, new sequence_index) for every included, non-superseded chunk whose index is not
    already its place in original_index order. A chunk dict needs: id, original_index, sequence_index,
    include_in_output, superseded. Excluded chunks keep sequence_index None by convention -- this
    function never touches them."""
    included = sorted(
        (c for c in chunks if not c.get("superseded") and c.get("include_in_output", True)),
        key=lambda c: (c.get("original_index") if c.get("original_index") is not None else 10**9, c["id"]),
    )
    return [(c["id"], i) for i, c in enumerate(included) if c.get("sequence_index") != i]


def included_in_order(chunks: list[dict]) -> list[dict]:
    rows = [c for c in chunks if not c.get("superseded") and c.get("include_in_output", True) and c.get("sequence_index") is not None]
    return sorted(rows, key=lambda c: c["sequence_index"])


# ------------------------------------------------------------------ dispositions file parsing (pure text)

DISPOSITIONS = ("fix", "flag", "dismiss", "exclude")
DISPOSITION_SYNONYMS = {
    **{c: "fix" for c in ("fixed", "corrected", "revised", "grammar", "orthographic", "lexical_choice", "register",
                          "omission_or_addition", "theological_interpretation", "mistranslation", "stt_mishearing",
                          "speaker_self_correction", "capitalization")},
    **{c: "dismiss" for c in ("no action", "no-action", "none", "ok", "keep", "kept", "false positive",
                              "false_positive", "no change", "no_change", "dismissed")},
    **{c: "exclude" for c in ("excluded", "hallucination")},
    **{c: "flag" for c in ("flagged", "human-ear", "human_ear", "flag_for_human")},
}


def parse_dispositions(path: Path) -> tuple[dict[tuple[int, str], tuple[str, str]], list[str]]:
    """({(cue, check): (disposition, reason)}, format errors). `check` may be "*" (covers every check
    of that row). Tolerates real worker mistakes found in production: a category word instead of the
    verb ("grammar" -> fix), a compound "fix+flag", a range "175-184" or a list "172/173", a check
    written with its own detail attached ("pronoun(He)") -- all handled the same way the original did,
    because workers really did write all of these forms in real production runs."""
    entries, errors = {}, []
    for n, raw in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in (line.split("\t", 3) if "\t" in line else line.split(None, 3))]
        if len(parts) < 4 or not parts[3]:
            errors.append(f"line {n}: needs 4 fields <cue> <check> <fix|flag|dismiss> <reason>: {raw[:60]!r}")
            continue
        cue, check, disp, reason = parts
        cue = cue.removeprefix("cue:").removeprefix("cue").strip()
        try:
            cues_n = []
            for item in re.split(r"\s*[/,]\s*", cue.strip()):
                if re.fullmatch(r"\d+\s*[-–]\s*\d+", item):
                    lo, hi = (int(x) for x in re.split(r"\s*[-–]\s*", item))
                    if hi < lo or hi - lo > 500:
                        raise ValueError
                    cues_n += list(range(lo, hi + 1))
                else:
                    cues_n.append(int(item))
        except ValueError:
            errors.append(f"line {n}: cue {cue!r} is not a number, a range like 175-184 or a list like 172/173")
            continue
        disp = DISPOSITION_SYNONYMS.get(disp.lower().strip(), disp)
        compound = [DISPOSITION_SYNONYMS.get(x.strip().lower(), x.strip().lower()) for x in re.split(r"\s*[+/&]\s*", disp)]
        if len(compound) > 1 and all(x in DISPOSITIONS for x in compound):
            disp = "flag" if "flag" in compound else compound[0]
        if disp.lower() not in DISPOSITIONS:
            first = (re.match(r"[A-Za-z_-]+", reason.strip()) or [""])[0].lower()
            first = DISPOSITION_SYNONYMS.get(first, first)
            if first in DISPOSITIONS:
                disp = first
        if disp.lower() not in DISPOSITIONS:
            errors.append(f"line {n}: disposition {disp!r} is not one of {'|'.join(DISPOSITIONS)}")
            continue
        check = re.sub(r"\(.*\)$", "", check).strip() or check
        for cue_n in cues_n:
            entries[(cue_n, check)] = (disp.lower(), reason)
    return entries, errors


def uncovered(rows: list[tuple[int, list[str]]], path: Path, auto: frozenset | set = frozenset()) -> list[tuple[int, str]]:
    """(cue, check) pairs with no line in the dispositions file and not auto-covered by code."""
    entries = parse_dispositions(path)[0] if Path(path).is_file() else {}
    out = []
    for cue, checks in rows:
        for check in dict.fromkeys(checks):
            if (cue, check) not in entries and (cue, "*") not in entries and (cue, check) not in auto:
                out.append((cue, check))
    return out


def disposition_counts(path: Path) -> dict:
    if not Path(path).is_file():
        return {"lines": 0}
    entries, errors = parse_dispositions(path)
    counts = Counter(d for d, _ in entries.values())
    return {"lines": len(entries), **{k: counts.get(k, 0) for k in DISPOSITIONS}, "format_errors": len(errors)}


def clean_disposition_counts(path: Path, n_candidates: int) -> dict:
    out = {"lines": 0, "fix": 0, "dismiss": 0, "uncovered": n_candidates}
    if not Path(path).is_file():
        return out
    seen = {}
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        parts = raw.strip().split("\t") if "\t" in raw else raw.strip().split(None, 2)
        if len(parts) >= 2 and parts[0].lstrip("#").isdigit():
            seen[int(parts[0].lstrip("#"))] = parts[1].strip().lower()
    c = Counter(seen.values())
    out.update(lines=len(seen), fix=c.get("fix", 0), dismiss=c.get("dismiss", 0),
               uncovered=len(set(range(1, n_candidates + 1)) - set(seen)))
    return out


# ------------------------------------------------------------------ rendering (pure string building)


def _one(text: str, width: int = 0) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text if not width or len(text) <= width else text[: width - 1] + "…"


def render_cues(cues: list[dict], *, number_field: str = "sequence_index") -> str:
    """`cues` need: id, source_text, and `number_field` (sequence_index by default, or a cue-anchor
    number if the caller extracts one first -- this module has no opinion on cue anchors, that's a
    video-specific concept the calling project owns)."""
    lines = ["# Chunks (included, in order): read EVERY one", "",
             f"`{number_field}` is this file's own ordering; `chunk` is the id to pass to your revise/exclude functions.",
             "Copy ids from this file, never retype them from memory.", ""]
    for c in cues:
        lines.append(f"{number_field} {c.get(number_field)} | chunk {c['id']} | {_one(c['source_text'])}")
    return "\n".join(lines) + "\n"


def render_clean(cands: list[dict], error: str = "") -> str:
    """Each candidate dict needs: k (1-based display number), chunk_id, kind, rule, category, text,
    suggestions (list), message, context."""
    lines = ["# Chunk-and-clean candidates (mechanical tool output, run once by the launcher)", ""]
    if error:
        return "\n".join(lines + [f"CANDIDATE GENERATION FAILED: {error}", ""])
    lines += [f"{len(cands)} candidate(s). For EACH, one line in the dispositions file: `<#>\\t<fix|dismiss>\\t<reason>`.", ""]
    for c in cands:
        sugg = f" -> {', '.join(c['suggestions'])}" if c.get("suggestions") else ""
        lines.append(f"#{c['k']} | chunk {c['chunk_id']} | {c['kind']}/{c.get('rule', '')}/{c.get('category', '')} | "
                      f"\"{c['text']}\"{sugg} | {c.get('message', '')} | …{c.get('context', '')}…")
    return "\n".join(lines) + "\n"

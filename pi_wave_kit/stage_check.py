"""A generic PASS/FIX/WARN/ESCALATE framework for checking whether a pipeline stage is actually done --
deliberately with NO concrete stages or conditions baked in. The real scripts/pi/stage_check.py
(agentic-doc-treatement) has eight stages and ~20 conditions, but every single one of them is specific
to that project's document-translation pipeline (curate, stt_verification, translation, ...) -- porting
them here would make this library useful for exactly one project, the opposite of the point. What DOES
generalize, and is ported, is the *shape*: a Condition has an id, a status, and a detail message; a
Stage reduces its conditions to one overall verdict; FAIL conditions are either fixable by the worker
itself (FIX) or need a human/coordinator decision (ESCALATE).

A calling project defines its own stages by writing check functions with this shape and composing them
with `evaluate()`/`reduce()`:

    def check_translation(ctx) -> list[Condition]:
        conditions = [passed("chunks_exist", "...")] if ctx.chunks else [escalate("chunks_exist", "no chunks found", "data_problem")]
        ...
        return conditions

    STAGES = {"translation": check_translation, ...}
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

Status = str  # "PASS" | "FAIL" | "WARN"
Action = str  # "none" | "fix" | "escalate"


@dataclass
class Condition:
    id: str
    status: Status
    detail: str
    action: Action = "none"
    fix_hint: str = ""
    kind: str = ""  # an escalate.py `kind`, only meaningful when action == "escalate"


def passed(id: str, detail: str) -> Condition:
    return Condition(id=id, status="PASS", detail=detail)


def warn(id: str, detail: str) -> Condition:
    return Condition(id=id, status="WARN", detail=detail)


def fix(id: str, detail: str, fix_hint: str) -> Condition:
    return Condition(id=id, status="FAIL", detail=detail, action="fix", fix_hint=fix_hint)


def escalate(id: str, detail: str, kind: str) -> Condition:
    return Condition(id=id, status="FAIL", detail=detail, action="escalate", kind=kind)


Result = str  # "PASS" | "WARN" | "FIX" | "ESCALATE"


def reduce(conditions: list[Condition]) -> Result:
    """The single most severe verdict across every condition: an ESCALATE beats a FIX beats a WARN beats
    a clean PASS -- same priority order a worker should act in (it can't fix its way past something that
    needs a human, so check for that first)."""
    if any(c.action == "escalate" for c in conditions):
        return "ESCALATE"
    if any(c.action == "fix" for c in conditions):
        return "FIX"
    if any(c.status == "WARN" for c in conditions):
        return "WARN"
    return "PASS"


def evaluate(stage: str, ctx, stages: dict[str, Callable[[object], list[Condition]]]) -> list[Condition]:
    if stage not in stages:
        raise ValueError(f"unknown stage {stage!r}; expected one of {sorted(stages)}")
    return stages[stage](ctx)


def render(conditions: list[Condition]) -> str:
    lines = [f"[{c.status}] {c.id}: {c.detail}" for c in conditions]
    result = reduce(conditions)
    lines.append(f"RESULT: {result}")
    failing = [c for c in conditions if c.action == "fix"]
    escalating = [c for c in conditions if c.action == "escalate"]
    if escalating:
        lines.append(f"NEXT: escalate ({escalating[0].kind}): {escalating[0].detail}")
    elif failing:
        lines.append(f"NEXT: {failing[0].fix_hint}")
    elif result == "WARN":
        lines.append("NEXT: note the WARN line(s) in your report; nothing to fix.")
    else:
        lines.append("NEXT: proceed to the next stage.")
    return "\n".join(lines)

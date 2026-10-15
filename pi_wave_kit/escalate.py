"""Record that a worker cannot proceed on a work item, and build the one-line message it should send to
the wave's coordinator. Never calls a model. Generalized from scripts/pi/escalate.py
(agentic-doc-treatement) -- that version was already almost entirely domain-agnostic; the only change
here is dropping its document/video-specific path splitting and config module.

Kinds: code_bug (a script/library is wrong), data_problem (the data is inconsistent, something upstream
is missing), decision_needed (a judgment the worker must not make alone, or a check that keeps
failing), tool_failure (an external tool/service crashed), budget_or_time (the work won't fit the cost
cap or the timeout)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

KINDS = ("code_bug", "data_problem", "decision_needed", "tool_failure", "budget_or_time")
ACTIONS = ("stop", "continue")
STOP_LINE = "Now stop: reply with your final report and end."


def _slug(item_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", item_id)


def _one_line(text: str | None) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


@dataclass
class Escalation:
    item_id: str
    stage: str
    kind: str
    action: str
    summary: str
    evidence: str = ""
    tried: str = ""
    need: str = ""
    agent: str | None = None
    run_id: str | None = None
    coordinator: str | None = None
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    file: str = ""

    def __post_init__(self):
        if self.kind not in KINDS:
            raise ValueError(f"kind must be one of {KINDS}, got {self.kind!r}")
        if self.action not in ACTIONS:
            raise ValueError(f"action must be one of {ACTIONS}, got {self.action!r}")
        if not _one_line(self.summary):
            raise ValueError("summary must not be empty")
        self.summary, self.evidence, self.tried, self.need = (
            _one_line(self.summary), _one_line(self.evidence), _one_line(self.tried), _one_line(self.need)
        )

    def message_line(self) -> str:
        return f"ESCALATION {self.item_id} {self.stage} {self.kind} {self.action}: {self.summary} [file: {self.file}]"

    def instructions(self) -> str:
        msg = self.message_line()
        out = [f"Escalation recorded: {self.file}"]
        if self.coordinator:
            out += [f'Send this message now to "{self.coordinator}":', msg]
        else:
            out += ["No coordinator for this run: the record is the escalation; send no message.", msg]
        out.append(STOP_LINE if self.action == "stop" else "Continue with the next step you can do; do not wait for a reply.")
        return "\n".join(out)


def write_record(escalation: Escalation, escalation_dir: str | Path) -> Escalation:
    folder = Path(escalation_dir) / _slug(escalation.item_id)
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    path, n = folder / f"{stamp}.json", 2
    while path.exists():
        path, n = folder / f"{stamp}-{n}.json", n + 1
    escalation.file = str(path.resolve())
    path.write_text(json.dumps(escalation.__dict__, ensure_ascii=False, indent=1), encoding="utf-8")
    return escalation


def read_records(escalation_dir: str | Path, item_id: str | None = None) -> list[dict]:
    """Every escalation record under escalation_dir, optionally filtered to one item_id. Used by a
    coordinator (or a launcher) to check whether any worker run escalated with action="stop"."""
    root = Path(escalation_dir)
    if not root.is_dir():
        return []
    folders = [root / _slug(item_id)] if item_id else [p for p in root.iterdir() if p.is_dir()]
    records = []
    for folder in folders:
        if not folder.is_dir():
            continue
        for f in sorted(folder.glob("*.json")):
            records.append(json.loads(f.read_text(encoding="utf-8")))
    return records


def is_blocked(escalation_dir: str | Path, item_id: str, run_id: str | None = None) -> bool:
    """True if any escalation for this item (optionally restricted to one run_id) has action="stop" --
    the signal a launcher uses to mark a job "blocked" rather than treating a clean exit as success."""
    for record in read_records(escalation_dir, item_id):
        if record.get("action") == "stop" and (run_id is None or record.get("run_id") == run_id):
            return True
    return False

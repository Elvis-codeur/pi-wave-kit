"""Helpers for the coordinator role: the one agent watching a wave of workers, handling escalations,
deciding whether to keep going. This role does NOT have to be a Pi session -- a Claude Code session (or
any other agent with shell + file read access) can read escalation records and the wave summary and
decide just as well. The ORIGINAL design this library was extracted from assumed an interactive Pi
session exclusively; it was later confirmed, in real production use, that a Claude Code session running
this exact role (reading escalations/summaries directly instead of over `pi_messenger`, since it has no
such tool) produced real, correct output -- see this library's own README for the story. Nothing here
assumes one or the other."""

from __future__ import annotations

from pathlib import Path

from .escalate import read_records
from .wave import WaveSummary


def pi_coordinator_command(*, provider: str = "deepseek", model: str, thinking: str = "max", agent_name: str | None = None) -> str:
    """The shell command to start an INTERACTIVE Pi coordinator session, if that's the role you want
    (as opposed to driving the wave from the current agent session directly)."""
    prefix = f"PI_AGENT_NAME={agent_name} " if agent_name else ""
    return f"{prefix}pi --provider {provider} --model {model} --thinking {thinking}"


def pending_stop_escalations(escalation_dir: str | Path, item_id: str | None = None) -> list[dict]:
    """Every escalation whose action is "stop" -- the ones a coordinator (Pi or Claude Code) must act on
    before that work item can be retried."""
    return [r for r in read_records(escalation_dir, item_id) if r.get("action") == "stop"]


def summarize_for_coordinator(summary: WaveSummary, escalation_dir: str | Path) -> str:
    """A short, human-readable status report -- what a coordinator should read first, whichever agent
    is playing that role."""
    lines = [
        f"Wave: {len(summary.launched)} launched, committed ${summary.committed_usd:.4f}"
        + (f", stopped ({summary.stop_reason})" if summary.stop_reason else ""),
    ]
    not_ok = summary.not_successful()
    if not_ok:
        lines.append(f"Not successful ({len(not_ok)}): " + ", ".join(not_ok))
    stops = pending_stop_escalations(escalation_dir)
    if stops:
        lines.append(f"Pending stop-escalations ({len(stops)}):")
        for r in stops:
            lines.append(f"  {r.get('item_id')} [{r.get('stage')}] {r.get('kind')}: {r.get('summary')}")
    if summary.not_launched:
        lines.append(f"Not launched this invocation ({len(summary.not_launched)}): " + ", ".join(summary.not_launched))
    return "\n".join(lines)

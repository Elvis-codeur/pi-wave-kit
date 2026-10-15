from pi_wave_kit.coordinator import pending_stop_escalations, pi_coordinator_command, summarize_for_coordinator
from pi_wave_kit.escalate import Escalation, write_record
from pi_wave_kit.wave import WaveSummary, WaveJobResult


def test_pi_coordinator_command_includes_the_given_model_and_agent_name():
    cmd = pi_coordinator_command(model="deepseek-v4-pro", agent_name="coord-1")
    assert "deepseek-v4-pro" in cmd and "PI_AGENT_NAME=coord-1" in cmd and "pi --provider deepseek" in cmd


def test_pending_stop_escalations_filters_out_continue_actions(tmp_path):
    write_record(Escalation(item_id="x", stage="s", kind="decision_needed", action="continue", summary="fyi"), tmp_path)
    write_record(Escalation(item_id="y", stage="s", kind="data_problem", action="stop", summary="broken"), tmp_path)
    pending = pending_stop_escalations(tmp_path)
    assert len(pending) == 1 and pending[0]["item_id"] == "y"


def test_summarize_for_coordinator_includes_failures_and_pending_escalations(tmp_path):
    summary = WaveSummary(
        launched=["j0", "j1"],
        finished={"j0": WaveJobResult(job_id="j0", status="success"), "j1": WaveJobResult(job_id="j1", status="failed", reason="oops")},
        committed_usd=1.23,
    )
    write_record(Escalation(item_id="j1", stage="translation", kind="data_problem", action="stop", summary="broken data"), tmp_path)
    text = summarize_for_coordinator(summary, tmp_path)
    assert "committed $1.2300" in text
    assert "j1" in text and "broken data" in text

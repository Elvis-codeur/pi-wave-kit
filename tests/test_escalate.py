import pytest

from pi_wave_kit.escalate import Escalation, is_blocked, read_records, write_record


def test_a_stop_escalation_renders_the_stop_line():
    esc = Escalation(item_id="doc/x", stage="translation", kind="data_problem", action="stop", summary="broken")
    assert "Now stop" in esc.instructions()
    assert "ESCALATION doc/x translation data_problem stop: broken" in esc.message_line()


def test_a_continue_escalation_does_not_render_the_stop_line():
    esc = Escalation(item_id="doc/x", stage="translation", kind="decision_needed", action="continue", summary="fyi")
    assert "Now stop" not in esc.instructions()
    assert "Continue with the next step" in esc.instructions()


def test_invalid_kind_raises():
    with pytest.raises(ValueError, match="kind"):
        Escalation(item_id="x", stage="s", kind="not-a-kind", action="stop", summary="x")


def test_empty_summary_raises():
    with pytest.raises(ValueError, match="summary"):
        Escalation(item_id="x", stage="s", kind="code_bug", action="stop", summary="   ")


def test_multiline_fields_are_collapsed_to_one_line():
    esc = Escalation(item_id="x", stage="s", kind="code_bug", action="continue", summary="line one\nline two")
    assert esc.summary == "line one line two"


class TestWriteAndReadRecords:
    def test_write_record_creates_a_json_file_under_the_items_own_folder(self, tmp_path):
        esc = Escalation(item_id="video/some slug", stage="translation", kind="tool_failure", action="stop", summary="x")
        write_record(esc, tmp_path)
        files = list((tmp_path / "video_some_slug").glob("*.json"))
        assert len(files) == 1
        assert esc.file == str(files[0].resolve())

    def test_read_records_returns_every_record_for_an_item(self, tmp_path):
        for i in range(3):
            write_record(Escalation(item_id="x", stage="s", kind="code_bug", action="continue", summary=f"note {i}"), tmp_path)
        records = read_records(tmp_path, "x")
        assert len(records) == 3

    def test_read_records_with_no_item_id_reads_every_item(self, tmp_path):
        write_record(Escalation(item_id="a", stage="s", kind="code_bug", action="continue", summary="x"), tmp_path)
        write_record(Escalation(item_id="b", stage="s", kind="code_bug", action="continue", summary="y"), tmp_path)
        assert len(read_records(tmp_path)) == 2

    def test_read_records_on_a_missing_directory_is_empty(self, tmp_path):
        assert read_records(tmp_path / "does-not-exist") == []

    def test_is_blocked_true_only_for_a_stop_action(self, tmp_path):
        write_record(Escalation(item_id="x", stage="s", kind="decision_needed", action="continue", summary="fyi"), tmp_path)
        assert is_blocked(tmp_path, "x") is False
        write_record(Escalation(item_id="x", stage="s", kind="data_problem", action="stop", summary="broken"), tmp_path)
        assert is_blocked(tmp_path, "x") is True

    def test_is_blocked_can_be_scoped_to_one_run_id(self, tmp_path):
        write_record(Escalation(item_id="x", stage="s", kind="data_problem", action="stop", summary="b", run_id="run-1"), tmp_path)
        assert is_blocked(tmp_path, "x", run_id="run-2") is False
        assert is_blocked(tmp_path, "x", run_id="run-1") is True

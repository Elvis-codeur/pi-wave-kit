"""The stt_translation plugin: pure-function ports + the generalized stage-check conditions."""

from importlib import resources
from pathlib import Path

from pi_wave_kit.plugins.stt_translation import pipeline_steps, stage_check


class TestPromptsShipAsPackageData:
    def test_every_real_prompt_file_is_bundled_and_non_empty(self):
        names = ["translate-video-prompt.md", "agent-checklist.md", "repair-prompt.md",
                 "repair-checklist.md", "fr-theology-glossary.md", "review-examples.md"]
        for name in names:
            text = (resources.files("pi_wave_kit.plugins.stt_translation") / "prompts" / name).read_text(encoding="utf-8")
            assert len(text) > 100, f"{name} looks empty or truncated"

    def test_the_real_prompt_still_has_its_placeholder_markers(self):
        text = (resources.files("pi_wave_kit.plugins.stt_translation") / "prompts" / "translate-video-prompt.md").read_text(encoding="utf-8")
        assert "{{DOC_ID}}" in text and "{{CHUNK_STAGE_ID}}" in text


class TestNumberingPlan:
    def test_renumbers_included_chunks_in_original_index_order(self):
        chunks = [
            {"id": 1, "original_index": 0, "sequence_index": None, "include_in_output": True},
            {"id": 2, "original_index": 1, "sequence_index": None, "include_in_output": True},
        ]
        assert pipeline_steps.numbering_plan(chunks) == [(1, 0), (2, 1)]

    def test_excluded_chunks_are_never_touched(self):
        chunks = [{"id": 1, "original_index": 0, "sequence_index": None, "include_in_output": False}]
        assert pipeline_steps.numbering_plan(chunks) == []

    def test_already_correct_numbering_produces_an_empty_plan(self):
        chunks = [{"id": 1, "original_index": 0, "sequence_index": 0, "include_in_output": True}]
        assert pipeline_steps.numbering_plan(chunks) == []


class TestParseDispositions:
    def test_a_well_formed_line_parses(self, tmp_path):
        path = tmp_path / "disp.txt"
        path.write_text("5\ttail\tfix\treal speech\n", encoding="utf-8")
        entries, errors = pipeline_steps.parse_dispositions(path)
        assert entries == {(5, "tail"): ("fix", "real speech")} and errors == []

    def test_a_range_covers_every_cue_in_it(self, tmp_path):
        path = tmp_path / "disp.txt"
        path.write_text("175-178\ttail\tdismiss\treal ending\n", encoding="utf-8")
        entries, _ = pipeline_steps.parse_dispositions(path)
        assert set(entries) == {(c, "tail") for c in range(175, 179)}

    def test_a_category_word_is_mapped_to_fix_via_synonyms(self, tmp_path):
        path = tmp_path / "disp.txt"
        path.write_text("3\tgrammar\tgrammar\tagreement fixed\n", encoding="utf-8")
        entries, errors = pipeline_steps.parse_dispositions(path)
        assert entries[(3, "grammar")][0] == "fix" and errors == []

    def test_a_malformed_disposition_is_reported_as_an_error(self, tmp_path):
        path = tmp_path / "disp.txt"
        path.write_text("3\tcheck\tnonsense\treason text\n", encoding="utf-8")
        entries, errors = pipeline_steps.parse_dispositions(path)
        assert entries == {} and len(errors) == 1

    def test_a_check_with_its_own_detail_is_keyed_on_the_bare_code(self, tmp_path):
        path = tmp_path / "disp.txt"
        path.write_text("5\tpronoun(He)\tfix\tfixed antecedent\n", encoding="utf-8")
        entries, _ = pipeline_steps.parse_dispositions(path)
        assert (5, "pronoun") in entries


class TestUncoveredAndCounts:
    def test_uncovered_reports_rows_with_no_disposition_line(self, tmp_path):
        path = tmp_path / "disp.txt"
        path.write_text("1\tcheck_a\tfix\tdone\n", encoding="utf-8")
        gaps = pipeline_steps.uncovered([(1, ["check_a"]), (2, ["check_b"])], path)
        assert gaps == [(2, "check_b")]

    def test_auto_covered_pairs_are_not_reported_as_gaps(self, tmp_path):
        path = tmp_path / "disp.txt"
        path.write_text("", encoding="utf-8")
        gaps = pipeline_steps.uncovered([(1, ["tail"])], path, auto={(1, "tail")})
        assert gaps == []

    def test_disposition_counts_on_a_missing_file_is_zero_lines(self, tmp_path):
        assert pipeline_steps.disposition_counts(tmp_path / "nope.txt") == {"lines": 0}

    def test_disposition_counts_tallies_by_kind(self, tmp_path):
        path = tmp_path / "disp.txt"
        path.write_text("1\ta\tfix\tx\n2\tb\tdismiss\ty\n", encoding="utf-8")
        counts = pipeline_steps.disposition_counts(path)
        assert counts["fix"] == 1 and counts["dismiss"] == 1 and counts["lines"] == 2


class TestRendering:
    def test_render_cues_includes_every_chunk(self):
        text = pipeline_steps.render_cues([{"id": 1, "sequence_index": 0, "source_text": "Grace alone."}])
        assert "chunk 1" in text and "Grace alone." in text

    def test_render_clean_shows_the_failure_message_when_candidate_generation_failed(self):
        text = pipeline_steps.render_clean([], error="LanguageTool down")
        assert "CANDIDATE GENERATION FAILED: LanguageTool down" in text


class _FakeCtx:
    """A minimal real implementation of the DocContext Protocol, for testing the conditions
    against real (if small) data rather than mocks of the functions themselves."""

    def __init__(self, **kw):
        self.doc_id = kw.get("doc_id", "doc/x")
        self.root = kw.get("root")
        self.log = kw.get("log")
        self.adf = kw.get("adf")
        self.fr_adf = kw.get("fr_adf")
        self._chunk_stage = kw.get("chunk_stage", {"id": 1})
        self._translate_stage = kw.get("translate_stage")
        self._included = kw.get("included", [])
        self._translated = kw.get("translated", {})
        self._log_stages = kw.get("log_stages", set())

    def chunk_stage(self):
        return self._chunk_stage

    def translate_stage(self):
        return self._translate_stage

    def included(self):
        return self._included

    def translated(self):
        return self._translated

    def log_stages(self):
        return self._log_stages

    def stt_worklist_rows(self):
        return []

    def review_worklist_rows(self):
        return []

    def stt_dispositions_path(self):
        return Path("/nonexistent")

    def review_dispositions_path(self):
        return Path("/nonexistent")

    def stt_auto_covered(self):
        return set()

    def human_ear_flags(self):
        return []

    def stt_verification_status(self):
        return "done"


class TestStageChecks:
    def test_check_curate_escalates_on_no_included_chunks(self):
        result = stage_check.check_curate(_FakeCtx(included=[]))
        assert result[0].action == "escalate" and result[0].kind == "data_problem"

    def test_check_curate_fixes_missing_sequence_index(self):
        result = stage_check.check_curate(_FakeCtx(included=[{"id": 1, "sequence_index": None}]))
        assert any(c.action == "fix" and c.id == "sequence_index_set" for c in result)

    def test_check_curate_passes_on_clean_contiguous_numbering(self):
        included = [{"id": 1, "sequence_index": 0}, {"id": 2, "sequence_index": 1}]
        result = stage_check.check_curate(_FakeCtx(included=included))
        assert all(c.status == "PASS" for c in result)

    def test_check_translation_fixes_missing_translations(self):
        ctx = _FakeCtx(translate_stage={"id": 5, "method": "agent_manual"},
                        included=[{"id": 1, "sequence_index": 0}, {"id": 2, "sequence_index": 1}],
                        translated={1: {"translated_text": "Grâce seule."}})
        result = stage_check.check_translation(ctx)
        assert any(c.action == "fix" and c.id == "all_included_translated" for c in result)

    def test_check_translation_catches_an_empty_translated_chunk(self):
        ctx = _FakeCtx(translate_stage={"id": 5}, included=[{"id": 1, "sequence_index": 0}],
                        translated={1: {"translated_text": "   "}})
        result = stage_check.check_translation(ctx)
        assert any(c.action == "fix" and c.id == "no_empty_translation" for c in result)

    def test_check_gates_reports_fail_lines_from_a_fake_gate_runner(self):
        class FakeProc:
            returncode = 1
            stdout = "FAIL space_before_punct cue 4\nRESULT: FIX"
            stderr = ""

        gates = [("mechanics_gate", lambda ctx: FakeProc(), "fix the spacing")]
        result = stage_check.check_gates(_FakeCtx(), gates)
        assert result[0].action == "fix" and "FAIL" in result[0].detail

    def test_check_gates_escalates_on_a_crash(self):
        class CrashProc:
            returncode = 1
            stdout = ""
            stderr = "Traceback (most recent call last):\nZeroDivisionError"

        gates = [("mechanics_gate", lambda ctx: CrashProc(), "n/a")]
        result = stage_check.check_gates(_FakeCtx(), gates)
        assert result[0].action == "escalate" and result[0].kind == "tool_failure"

    def test_check_assemble_escalates_when_the_source_document_is_missing(self, tmp_path):
        ctx = _FakeCtx(adf=tmp_path / "missing.md", fr_adf=tmp_path / "missing.fr.md")
        result = stage_check.check_assemble(ctx, adf_roundtrip=lambda c: (True, "ok", False))
        assert result[0].action == "escalate" and result[0].kind == "data_problem"

    def test_check_assemble_passes_on_a_clean_roundtrip(self, tmp_path):
        (tmp_path / "en.md").write_text("x", encoding="utf-8")
        (tmp_path / "fr.md").write_text("y", encoding="utf-8")
        ctx = _FakeCtx(adf=tmp_path / "en.md", fr_adf=tmp_path / "fr.md")
        result = stage_check.check_assemble(ctx, adf_roundtrip=lambda c: (True, "roundtrip ok", False))
        assert all(c.status == "PASS" for c in result)

    def test_evaluate_one_dispatches_correctly(self):
        result = stage_check.evaluate_one(_FakeCtx(included=[]), "curate")
        assert result[0].kind == "data_problem"

    def test_evaluate_one_rejects_an_unknown_stage(self):
        import pytest
        with pytest.raises(ValueError, match="unknown stage"):
            stage_check.evaluate_one(_FakeCtx(), "not-a-stage")

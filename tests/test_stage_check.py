from pi_wave_kit.stage_check import Condition, escalate, evaluate, fix, passed, reduce, render, warn


def test_reduce_priority_escalate_beats_fix_beats_warn_beats_pass():
    assert reduce([passed("a", "ok")]) == "PASS"
    assert reduce([passed("a", "ok"), warn("b", "hmm")]) == "WARN"
    assert reduce([warn("b", "hmm"), fix("c", "bad", "do x")]) == "FIX"
    assert reduce([fix("c", "bad", "do x"), escalate("d", "need human", "decision_needed")]) == "ESCALATE"


def test_empty_conditions_list_is_pass():
    assert reduce([]) == "PASS"


def test_evaluate_dispatches_to_the_registered_stage_function():
    def my_stage(ctx):
        return [passed("ok", f"got {ctx}")]
    result = evaluate("mine", "context-object", {"mine": my_stage})
    assert result == [Condition(id="ok", status="PASS", detail="got context-object")]


def test_evaluate_unknown_stage_raises():
    import pytest
    with pytest.raises(ValueError, match="unknown stage"):
        evaluate("nope", None, {"mine": lambda ctx: []})


def test_render_shows_escalate_hint_first_even_if_a_fix_condition_also_exists():
    conditions = [fix("c", "bad", "do x"), escalate("d", "need human", "decision_needed")]
    text = render(conditions)
    assert "RESULT: ESCALATE" in text
    assert "NEXT: escalate (decision_needed): need human" in text


def test_render_shows_fix_hint_when_no_escalation_present():
    text = render([fix("c", "bad thing", "run the fixer script")])
    assert "RESULT: FIX" in text
    assert "NEXT: run the fixer script" in text


def test_render_on_a_clean_pass():
    text = render([passed("a", "all good")])
    assert "RESULT: PASS" in text
    assert "NEXT: proceed to the next stage." in text

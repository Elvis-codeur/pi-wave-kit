"""The mechanical half of CONTRIBUTING.md's commit-message protocol (scripts/check_commit_message.py),
installed as a pre-commit commit-msg hook (.pre-commit-config.yaml)."""

import importlib.util
import pathlib

_SPEC = importlib.util.spec_from_file_location(
    "check_commit_message",
    pathlib.Path(__file__).resolve().parent.parent / "scripts" / "check_commit_message.py",
)
_mod = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_mod)
check = _mod.check


def test_accepts_a_well_formed_message():
    msg = "Add a thing\n\nThis explains why the thing was added, across a wrapped body.\n"
    assert check(msg) == []


def test_rejects_an_empty_subject():
    assert check("") != []
    assert check("\n\n   \n") != []


def test_rejects_a_too_long_subject():
    long_subject = "x" * 73
    assert any("72" in p for p in check(long_subject))


def test_accepts_a_subject_at_exactly_seventy_two_chars():
    subject = "x" * 72
    assert check(subject) == []


def test_rejects_a_subject_ending_in_a_period():
    assert any("period" in p for p in check("Fix the thing."))


def test_rejects_a_missing_blank_line_before_the_body():
    msg = "Fix the thing\nbecause it was broken\n"
    assert any("blank" in p for p in check(msg))


def test_ignores_comment_lines_git_leaves_in_the_editor_buffer():
    msg = "# Please enter the commit message\nFix the thing\n\nbody here\n"
    assert check(msg) == []


def test_subject_only_with_no_body_is_fine():
    assert check("Fix the thing") == []

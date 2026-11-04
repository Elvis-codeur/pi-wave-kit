"""Issue #21: every console script's --help is the discoverable documentation -- each one exists, has
examples, and points at the other commands, so an agent that reads only --help finds every capability."""

import importlib
import re
from pathlib import Path

import pytest

PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"
SCRIPTS = dict(re.findall(r'^(pi-wave-[a-z]+) = "([\w.]+:\w+)"', PYPROJECT.read_text(encoding="utf-8"), re.M))


def test_the_three_console_scripts_are_registered():
    assert set(SCRIPTS) == {"pi-wave-job", "pi-wave-session", "pi-wave-run"}


@pytest.mark.parametrize("script", sorted(SCRIPTS))
def test_help_has_examples_and_names_the_other_commands(script, capsys):
    module, func = SCRIPTS[script].split(":")
    main = getattr(importlib.import_module(module), func)
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert f"usage: {script}" in out and "examples:" in out
    for other in set(SCRIPTS) - {script}:
        assert other in out, f"{script} --help does not mention {other}"

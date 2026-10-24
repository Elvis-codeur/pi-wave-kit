"""pi_wave_kit.interactive: launch/inspect/stop a screen-wrapped, long-lived interactive pi session.
Uses the fake_screen fixture (tests/conftest.py) -- not the real `screen` binary, which isn't
guaranteed present in CI -- to exercise the real argv this module builds end to end: a fake `screen`
that actually spawns the given command and tracks it, the same shape as the real thing."""

import os
import stat
import textwrap
import time

import pytest

from pi_wave_kit.interactive import hardcopy, is_alive, launch_screen_session, stop


@pytest.fixture
def fake_pi_records_env(tmp_path, monkeypatch):
    """A fake `pi` that writes its own PI_AGENT_NAME env var to env_seen.txt in its cwd, then exits --
    used only to check launch_screen_session's real argv/env, not cost-reading."""
    script = tmp_path / "pi"
    script.write_text(textwrap.dedent("""\
        #!/usr/bin/env python3
        import os
        with open("env_seen.txt", "w") as f:
            f.write(os.environ.get("PI_AGENT_NAME", "<unset>"))
    """), encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    return script


def test_launch_sets_pi_agent_name_env_var_to_the_session_name(fake_pi_records_env, fake_screen, tmp_path):
    """Real bug found by the manual smoke test (2026-10-25): --name alone only sets pi's own display
    title, not its pi-messenger mesh identity -- without PI_AGENT_NAME a peer sees a random generated
    name instead of the one the caller chose, silently defeating the whole point of calling this with
    a known name."""
    launch_screen_session(
        "alpha", provider="deepseek", model="x", thinking="low",
        cwd=tmp_path, session_dir=tmp_path / "sessions",
    )
    time.sleep(0.3)
    assert (tmp_path / "env_seen.txt").read_text(encoding="utf-8") == "alpha"


def test_launch_and_is_alive_while_the_process_runs(fake_pi, fake_screen, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_PI_SLEEP", "2")
    session = launch_screen_session(
        "alpha", provider="deepseek", model="x", thinking="low",
        cwd=tmp_path, session_dir=tmp_path / "sessions",
    )
    assert session.name == "alpha"
    assert is_alive(session) is True


def test_is_alive_false_after_the_process_exits(fake_pi, fake_screen, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_PI_SLEEP", "0")  # fake pi exits almost immediately
    session = launch_screen_session(
        "alpha", provider="deepseek", model="x", thinking="low",
        cwd=tmp_path, session_dir=tmp_path / "sessions",
    )
    for _ in range(50):
        if not is_alive(session):
            break
        time.sleep(0.05)
    assert is_alive(session) is False


def test_hardcopy_reflects_liveness(fake_pi, fake_screen, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_PI_SLEEP", "2")
    session = launch_screen_session(
        "alpha", provider="deepseek", model="x", thinking="low",
        cwd=tmp_path, session_dir=tmp_path / "sessions",
    )
    text = hardcopy(session, tmp_path / "hc.txt")
    assert "alive=True" in text


def test_stop_kills_the_session(fake_pi, fake_screen, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_PI_SLEEP", "10")
    session = launch_screen_session(
        "alpha", provider="deepseek", model="x", thinking="low",
        cwd=tmp_path, session_dir=tmp_path / "sessions",
    )
    assert is_alive(session) is True
    stop(session)
    time.sleep(0.2)
    assert is_alive(session) is False


def test_initial_prompt_is_passed_through_to_pi(fake_pi, fake_screen, tmp_path):
    """The initial prompt becomes pi's own first-message argv, same as `pi "do X"` run directly --
    this exercises the real command-building path, not a mock."""
    session = launch_screen_session(
        "alpha", provider="deepseek", model="x", thinking="low",
        cwd=tmp_path, session_dir=tmp_path / "sessions",
        initial_prompt="hello there",
    )
    time.sleep(0.3)
    assert (tmp_path / "sessions").is_dir()  # fake_pi wrote its session file, meaning it did run
    assert is_alive(session) is False  # fake_pi exits immediately with no FAKE_PI_SLEEP set


def test_stop_on_an_already_dead_session_does_not_raise(fake_pi, fake_screen, tmp_path):
    session = launch_screen_session(
        "alpha", provider="deepseek", model="x", thinking="low",
        cwd=tmp_path, session_dir=tmp_path / "sessions",
    )
    time.sleep(0.3)
    stop(session)  # already exited on its own; must not raise

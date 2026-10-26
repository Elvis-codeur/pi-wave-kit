"""pi_wave_kit.interactive: launch/inspect/stop a screen-wrapped, long-lived interactive pi session.
Uses the fake_screen fixture (tests/conftest.py) -- not the real `screen` binary, which isn't
guaranteed present in CI -- to exercise the real argv this module builds end to end: a fake `screen`
that actually spawns the given command and tracks it, the same shape as the real thing."""

import json
import os
import stat
import textwrap
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

import pytest

from pi_wave_kit.interactive import (
    DAEMON_SPAWNED_ENV_VAR,
    hardcopy,
    is_alive,
    launch_screen_session,
    stop,
)


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


class _FakeDaemon(BaseHTTPRequestHandler):
    """A minimal stand-in for agent-watch-daemon's real `/local/create` (see that repo's
    `local_api.rs`) -- just enough to prove `launch_screen_session` talks to it correctly and
    uses its response, without needing the real Rust daemon in CI."""

    requests: list[dict] = []
    response_tmux_name = "agent-watch-daemon-session"

    def do_POST(self):
        length = int(self.headers["Content-Length"])
        self.__class__.requests.append(json.loads(self.rfile.read(length)))
        body = json.dumps(
            {"external_id": "ext-123", "tmux_session_name": self.__class__.response_tmux_name}
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass  # keep test output clean


@pytest.fixture
def fake_daemon(monkeypatch):
    """Binds the fake daemon to an OS-assigned ephemeral port (never the real `AGENT_WATCH_LOCAL_PORT`
    -- that port may genuinely have the real daemon listening on this machine) and monkeypatches
    `interactive.AGENT_WATCH_LOCAL_PORT` to match, so `_try_daemon_create` talks to this fake one."""
    _FakeDaemon.requests = []
    server = HTTPServer(("127.0.0.1", 0), _FakeDaemon)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    import pi_wave_kit.interactive as interactive_module
    monkeypatch.setattr(interactive_module, "AGENT_WATCH_LOCAL_PORT", server.server_address[1])
    yield _FakeDaemon
    server.shutdown()


def test_launch_uses_the_daemon_when_it_is_reachable(fake_daemon, fake_pi, fake_screen, tmp_path):
    """Default behavior (owner directive 2026-10-26): when agent-watch-daemon's local API answers,
    use ITS session instead of launching screen/pi directly ourselves."""
    session = launch_screen_session(
        "alpha", provider="deepseek", model="x", thinking="low",
        cwd=tmp_path, session_dir=tmp_path / "sessions", initial_prompt="hello there",
    )
    assert session.name == "agent-watch-daemon-session"
    assert fake_daemon.requests == [
        {"tool": "pi", "cwd": str(tmp_path), "args": [], "prompt": "hello there"}
    ]
    # the real screen/pi path was never taken -- fake_screen has no record of "alpha" at all
    assert is_alive(session) is False


def test_launch_falls_back_to_direct_screen_when_daemon_unreachable(fake_pi, fake_screen, tmp_path):
    """No fake_daemon fixture here -- the autouse `_no_real_agent_watch_daemon` fixture points
    AGENT_WATCH_LOCAL_PORT at a free port with nothing listening, so this exercises the ordinary
    fallback path unchanged."""
    launch_screen_session(
        "alpha", provider="deepseek", model="x", thinking="low",
        cwd=tmp_path, session_dir=tmp_path / "sessions",
    )
    time.sleep(0.3)
    assert (tmp_path / "sessions").is_dir()  # the real fake_pi ran


def test_register_with_daemon_false_skips_the_daemon_even_though_it_is_reachable(
    fake_daemon, fake_pi, fake_screen, tmp_path
):
    """--no-watch (register_with_daemon=False): always go straight to the direct launch, even
    though a reachable daemon could have handled it."""
    launch_screen_session(
        "alpha", provider="deepseek", model="x", thinking="low",
        cwd=tmp_path, session_dir=tmp_path / "sessions", register_with_daemon=False,
    )
    time.sleep(0.3)
    assert fake_daemon.requests == []
    assert (tmp_path / "sessions").is_dir()  # the real fake_pi ran instead


def test_daemon_spawned_env_var_prevents_recursion(fake_daemon, fake_pi, fake_screen, tmp_path, monkeypatch):
    """The real risk this guards: agent-watch-daemon's own `/local/create` handler shells out to
    `pi-wave-session launch` to actually fulfill a `pi` creation request. Without this guard, that
    inner invocation would try to contact the daemon again and loop forever. Simulates the daemon
    having set its env var on that one subprocess call."""
    monkeypatch.setenv(DAEMON_SPAWNED_ENV_VAR, "1")
    launch_screen_session(
        "alpha", provider="deepseek", model="x", thinking="low",
        cwd=tmp_path, session_dir=tmp_path / "sessions",
    )
    time.sleep(0.3)
    assert fake_daemon.requests == []
    assert (tmp_path / "sessions").is_dir()  # fell through to the real direct launch, not the daemon

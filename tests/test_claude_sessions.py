"""pi_wave_kit.claude_sessions / claude_cli against fake `claude` and `screen` executables.

Same technique as tests/test_agents.py and the fake_screen fixture in tests/conftest.py: the fake
binaries are real subprocesses on PATH that record their argv/env and replay the exact output
shapes captured live from Claude Code 2.1.330 (2026-11-23). Nothing here invokes the real `claude`
(which would cost money) or the real `screen` (not guaranteed present in CI), and no test needs
network.
"""

import json
import os
import shutil
import stat
import sys
import textwrap

import pytest

from pi_wave_kit import claude_sessions
from pi_wave_kit.claude_sessions import (
    ClaudeCommandError,
    ClaudeError,
    ClaudeSessionAmbiguousError,
    ClaudeSessionNotFoundError,
    ClaudeUnavailableError,
    ClaudeUnsupportedError,
    ClaudeWaitTimeoutError,
    ScreenNotFoundError,
    WorkspaceNotTrustedError,
)

#: Absolute interpreter path for the fake binaries' shebangs: one test narrows PATH to a directory
#: holding only a fake claude, and `#!/usr/bin/env python3` would then have no python to find.
PYTHON = os.path.abspath(sys.executable)

#: One-shot `claude -p --output-format json` object, captured live 2026-10-30 (as in test_agents.py).
CLAUDE_RESULT = {
    "type": "result", "subtype": "success", "is_error": False, "result": "KUMQUAT",
    "session_id": "8ac734fb-claude", "total_cost_usd": 0.00431512,
    "usage": {"input_tokens": 2, "cache_creation_input_tokens": 20983, "cache_read_input_tokens": 11382,
              "output_tokens": 9, "output_tokens_details": {"thinking_tokens": 0},
              "server_tool_use": {"web_search_requests": 0, "web_fetch_requests": 0},
              "cache_creation": {"ephemeral_1h_input_tokens": 20983, "ephemeral_5m_input_tokens": 0}},
    "modelUsage": {"claude-haiku-5-5": {"inputTokens": 2, "outputTokens": 9}},
}

FAKE_CLAUDE = """\
#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
with open(os.environ["FAKE_CLAUDE_CALLS"], "a") as f:
    f.write(json.dumps({"argv": args, "env": dict(os.environ), "cwd": os.getcwd()}) + "\\n")
if "--version" in args:
    print(os.environ.get("FAKE_CLAUDE_VERSION", "2.1.330 (Claude Code)"))
    sys.exit(0)
if args[:1] == ["agents"]:
    fail = os.environ.get("FAKE_CLAUDE_AGENTS_FAIL", "")
    if fail:
        sys.stderr.write(fail)
        sys.exit(int(os.environ.get("FAKE_CLAUDE_AGENTS_EXIT", "1")))
    key = "FAKE_CLAUDE_AGENTS_ALL" if "--all" in args else "FAKE_CLAUDE_AGENTS"
    path = os.environ.get(key) or os.environ.get("FAKE_CLAUDE_AGENTS")
    if path and os.path.exists(path):
        sys.stdout.write(open(path).read())
    else:
        print("[]")
    sys.exit(0)
if args[:1] == ["logs"]:
    sys.stdout.write(os.environ.get("FAKE_CLAUDE_LOGS", ""))
    sys.exit(int(os.environ.get("FAKE_CLAUDE_LOGS_EXIT", "0")))
if args[:1] in (["stop"], ["rm"]):
    fail = os.environ.get("FAKE_CLAUDE_ACTION_FAIL", "")
    if fail:
        sys.stderr.write(fail)
        sys.exit(1)
    sys.exit(0)
if "--bg" in args:
    fail = os.environ.get("FAKE_CLAUDE_BG_FAIL", "")
    if fail:
        sys.stderr.write(fail)
        sys.exit(int(os.environ.get("FAKE_CLAUDE_BG_EXIT", "1")))
    out = os.environ.get("FAKE_CLAUDE_BG_STDOUT")
    if out is None:
        name = args[args.index("-n") + 1] if "-n" in args else "unknown"
        out = ("backgrounded \u00b7 1efcedf4 \u00b7 " + name + "\\n"
               "claude agents             list sessions\\n"
               "claude attach 1efcedf4    open in this terminal\\n"
               "claude logs 1efcedf4      show recent output\\n"
               "claude stop 1efcedf4      stop this session\\n")
    sys.stdout.write(out)
    sys.exit(0)
sys.stdout.write(os.environ.get("FAKE_CLAUDE_RESULT", "{}"))
sys.exit(int(os.environ.get("FAKE_CLAUDE_RESULT_EXIT", "0")))
"""

FAKE_SCREEN = """\
#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
STATE = os.environ["FAKE_SCREEN_STATE"]
with open(os.environ["FAKE_SCREEN_CALLS"], "a") as f:
    f.write(json.dumps({"argv": args, "cwd": os.getcwd()}) + "\\n")

def alive(name):
    return os.path.join(STATE, name + ".alive")

if "-dmS" in args:
    i = args.index("-dmS")
    with open(alive(args[i + 1]), "w") as f:
        f.write("1")
elif "-ls" in args:
    for fn in os.listdir(STATE):
        if fn.endswith(".alive"):
            print("\\t1234." + fn[:-6] + "\\t(11/23/2026 00:00:00 AM)\\t(Detached)")
elif "-X" in args:
    name = args[args.index("-S") + 1]
    action = args[args.index("-X") + 1]
    if action == "stuff":
        with open(os.path.join(STATE, name + ".typed"), "a") as f:
            f.write(args[args.index("-X") + 2])
    elif action == "quit":
        try:
            os.remove(alive(name))
        except FileNotFoundError:
            pass
"""


class FakeTools:
    """Fake claude/screen on PATH plus typed helpers to set their canned output and read calls."""

    def __init__(self, tmp_path, monkeypatch):
        self.tmp_path = tmp_path
        self.bin_dir = tmp_path / "bin"
        self.bin_dir.mkdir()
        self.claude_calls_path = tmp_path / "claude-calls.jsonl"
        self.screen_calls_path = tmp_path / "screen-calls.jsonl"
        self.screen_state = tmp_path / "screen-state"
        self.screen_state.mkdir()
        for name, body in (("claude", FAKE_CLAUDE), ("screen", FAKE_SCREEN)):
            path = self.bin_dir / name
            script = textwrap.dedent(body)
            # Absolute interpreter: the screen-missing test narrows PATH to a directory that holds
            # only this fake claude, and `/usr/bin/env python3` would then have no python to find.
            path.write_text(f"#!{PYTHON}\n" + script.split("\n", 1)[1], encoding="utf-8")
            path.chmod(path.stat().st_mode | stat.S_IEXEC)
        monkeypatch.setenv("PATH", str(self.bin_dir) + os.pathsep + os.environ["PATH"])
        monkeypatch.setenv("FAKE_CLAUDE_CALLS", str(self.claude_calls_path))
        monkeypatch.setenv("FAKE_SCREEN_CALLS", str(self.screen_calls_path))
        monkeypatch.setenv("FAKE_SCREEN_STATE", str(self.screen_state))
        monkeypatch.setenv("FAKE_CLAUDE_RESULT", json.dumps(CLAUDE_RESULT))
        self.monkeypatch = monkeypatch

    def claude_calls(self):
        return _calls(self.claude_calls_path)

    def screen_calls(self):
        return _calls(self.screen_calls_path)

    def set_env(self, **values):
        for key, value in values.items():
            if value is None:
                self.monkeypatch.delenv(key, raising=False)
            else:
                self.monkeypatch.setenv(key, str(value))

    def set_sessions(self, active, completed=(), *, active_raw=None, all_raw=None):
        active_path = self.tmp_path / "agents-active.json"
        all_path = self.tmp_path / "agents-all.json"
        active_path.write_text(active_raw if active_raw is not None else json.dumps(active), encoding="utf-8")
        all_path.write_text(all_raw if all_raw is not None else json.dumps([*active, *completed]), encoding="utf-8")
        self.monkeypatch.setenv("FAKE_CLAUDE_AGENTS", str(active_path))
        self.monkeypatch.setenv("FAKE_CLAUDE_AGENTS_ALL", str(all_path))


def _calls(path):
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


@pytest.fixture
def fake_tools(tmp_path, monkeypatch):
    return FakeTools(tmp_path, monkeypatch)


def _record(short_id, name, cwd, *, kind="background", status="busy", state="working", pid=4242):
    return {
        "id": short_id, "name": name, "cwd": str(cwd), "kind": kind, "status": status,
        "state": state, "sessionId": f"{short_id}-full-session-id",
        "startedAt": "2026-11-23T00:30:00.000Z", "pid": pid,
    }


def _work(tmp_path):
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    return work


# --------------------------------------------------------------------------------------------------
# Availability and launch
# --------------------------------------------------------------------------------------------------


def test_claude_command_falls_back_to_local_bin_when_path_lacks_it(tmp_path, monkeypatch):
    """Claude Code is commonly installed in ~/.local/bin, which is not on every non-login PATH
    (this machine's own bash tool hits exactly that). The library should find it without the
    caller mutating PATH, and should say where to look when it genuinely is not installed."""
    home = tmp_path / "home"
    script = home / ".local" / "bin" / "claude"
    script.parent.mkdir(parents=True)
    script.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    script.chmod(0o755)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    assert claude_sessions.claude_command() == str(script)


def test_claude_command_missing_names_the_likely_install_locations(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    with pytest.raises(ClaudeUnavailableError) as exc:
        claude_sessions.claude_command()
    assert "PATH" in str(exc.value) and ".local/bin" in str(exc.value)


def test_version_uses_the_installed_binary(fake_tools):
    assert claude_sessions.claude_version() == "2.1.330 (Claude Code)"
    assert fake_tools.claude_calls()[-1]["argv"] == ["--version"]


def test_start_background_uses_bg_and_parses_the_backgrounded_line(fake_tools, tmp_path, monkeypatch):
    work = _work(tmp_path)
    monkeypatch.setenv("CLAUDECODE", "1")  # as when launched from inside a parent Claude Code session
    session = claude_sessions.start_background(
        "reformation-bg-test", "do the thing", cwd=work, model="haiku",
        env={"CLAUDE_CONFIG_DIR": "/tmp/claude-client-a"},
    )
    assert session.short_id == "1efcedf4" and session.id == "1efcedf4"
    assert session.name == "reformation-bg-test" and session.kind == "background"
    assert session.cwd == str(work.resolve())
    call = fake_tools.claude_calls()[-1]
    assert call["argv"] == ["--bg", "-n", "reformation-bg-test", "--model", "haiku", "do the thing"]
    assert "-p" not in call["argv"] and "--print" not in call["argv"]
    # Controlled env: the client's config dir reaches this one process, the parent's marker does not.
    assert call["env"]["CLAUDE_CONFIG_DIR"] == "/tmp/claude-client-a" and "CLAUDECODE" not in call["env"]


def test_start_background_rejects_print_mode_before_spawning(fake_tools, tmp_path):
    with pytest.raises(ClaudeError, match="--bg and --print conflict"):
        claude_sessions.start_background("n", "p", cwd=_work(tmp_path), extra_args=["-p"])
    assert fake_tools.claude_calls() == []  # no real argv was ever attempted


def test_start_background_surfaces_workspace_trust_verbatim(fake_tools, tmp_path):
    fake_tools.set_env(FAKE_CLAUDE_BG_FAIL="Workspace not trusted\nAccept trust in this directory first.\n")
    with pytest.raises(WorkspaceNotTrustedError) as exc:
        claude_sessions.start_background("n", "p", cwd=_work(tmp_path))
    assert "Workspace not trusted" in str(exc.value)
    assert "Accept trust in this directory first." in exc.value.stderr
    assert exc.value.returncode == 1


def test_start_background_failure_surfaces_stderr(fake_tools, tmp_path):
    fake_tools.set_env(FAKE_CLAUDE_BG_FAIL="Error: model 'haiku' is not available\n")
    with pytest.raises(ClaudeCommandError) as exc:
        claude_sessions.start_background("n", "p", cwd=_work(tmp_path))
    assert not isinstance(exc.value, WorkspaceNotTrustedError)
    assert "model 'haiku' is not available" in str(exc.value)


def test_start_background_unparseable_output_is_a_clear_error(fake_tools, tmp_path):
    fake_tools.set_env(FAKE_CLAUDE_BG_STDOUT="started somehow\n")
    with pytest.raises(ClaudeCommandError, match="backgrounded"):
        claude_sessions.start_background("n", "p", cwd=_work(tmp_path))


# --------------------------------------------------------------------------------------------------
# Listing, resolving, waiting, logs
# --------------------------------------------------------------------------------------------------


def test_list_sessions_active_all_and_cwd_filter(fake_tools, tmp_path):
    work, other = _work(tmp_path), tmp_path / "other"
    other.mkdir()
    active = _record("aaaa1111", "alpha", work)
    done = _record("bbbb2222", "beta", work, status="idle", state="done")
    outside = _record("cccc3333", "gamma", other, status="idle", state="done")
    fake_tools.set_sessions([active], [done, outside])

    assert [s.short_id for s in claude_sessions.list_sessions()] == ["aaaa1111"]
    assert [s.short_id for s in claude_sessions.list_sessions(include_completed=True)] == [
        "aaaa1111", "bbbb2222", "cccc3333"]
    assert [s.short_id for s in claude_sessions.list_sessions(include_completed=True, cwd=work)] == [
        "aaaa1111", "bbbb2222"]
    assert "--all" not in fake_tools.claude_calls()[0]["argv"]
    assert "--all" in fake_tools.claude_calls()[1]["argv"]


def test_list_sessions_tolerates_a_warning_line_before_the_json(fake_tools, tmp_path):
    work = _work(tmp_path)
    raw = "warning: config migration in progress\n" + json.dumps([_record("aaaa1111", "alpha", work)])
    fake_tools.set_sessions([], [], active_raw=raw)
    assert [s.short_id for s in claude_sessions.list_sessions()] == ["aaaa1111"]


def test_list_sessions_older_claude_without_all_degrades_with_a_clear_error(fake_tools):
    fake_tools.set_env(FAKE_CLAUDE_AGENTS_FAIL="error: unknown option '--all'\n", FAKE_CLAUDE_AGENTS_EXIT=1)
    with pytest.raises(ClaudeUnsupportedError, match="upgrade Claude Code"):
        claude_sessions.list_sessions(include_completed=True)


def test_get_session_matches_short_id_full_session_id_and_exact_name(fake_tools, tmp_path):
    work = _work(tmp_path)
    session = _record("aaaa1111", "alpha", work)
    fake_tools.set_sessions([session], [])
    assert claude_sessions.get_session("aaaa1111").short_id == "aaaa1111"
    assert claude_sessions.get_session("aaaa1111-full-session-id").short_id == "aaaa1111"
    assert claude_sessions.get_session("alpha").short_id == "aaaa1111"
    with pytest.raises(ClaudeSessionNotFoundError):
        claude_sessions.get_session("nope")


def test_get_session_refuses_an_ambiguous_name(fake_tools, tmp_path):
    work = _work(tmp_path)
    fake_tools.set_sessions([_record("aaaa1111", "same", work), _record("bbbb2222", "same", work)], [])
    with pytest.raises(ClaudeSessionAmbiguousError) as exc:
        claude_sessions.get_session("same")
    assert "aaaa1111" in str(exc.value) and "bbbb2222" in str(exc.value)


def test_strip_ansi_removes_colours_osc_and_cursor_sequences():
    text = "\x1b[31mred\x1b[0m\r\n\x1b]0;window title\x07ok \x1b[2K\x1b[1Gdone"
    assert claude_sessions.strip_ansi(text) == "red\r\nok done"


def test_wait_for_returns_a_completed_session_from_the_all_list(fake_tools, tmp_path):
    work = _work(tmp_path)
    done = _record("bbbb2222", "beta", work, status="idle", state="done")
    fake_tools.set_sessions([], [done])  # already finished, so no longer in the active list
    result = claude_sessions.wait_for("beta", timeout=1, poll=0.01)
    assert result.short_id == "bbbb2222" and result.is_done


def test_wait_for_times_out_with_the_last_known_state(fake_tools, tmp_path):
    work = _work(tmp_path)
    fake_tools.set_sessions([_record("aaaa1111", "alpha", work)], [])
    with pytest.raises(ClaudeWaitTimeoutError) as exc:
        claude_sessions.wait_for("aaaa1111", timeout=0.1, poll=0.02)
    assert exc.value.last.state == "working"
    assert "working" in str(exc.value)


def test_logs_strips_ansi_by_default_and_keeps_it_with_raw(fake_tools, tmp_path):
    work = _work(tmp_path)
    fake_tools.set_sessions([_record("aaaa1111", "alpha", work)], [])
    fake_tools.set_env(FAKE_CLAUDE_LOGS="\x1b[32mHELLO\x1b[0m\n")
    assert claude_sessions.logs("alpha") == "HELLO\n"
    assert "\x1b[32m" in claude_sessions.logs("alpha", raw=True)
    assert fake_tools.claude_calls()[-1]["argv"] == ["logs", "aaaa1111"]


# --------------------------------------------------------------------------------------------------
# Screen attach / typing / steering
# --------------------------------------------------------------------------------------------------


def test_attach_in_screen_is_idempotent_and_uses_claude_attach(fake_tools, tmp_path):
    work = _work(tmp_path)
    record = _record("aaaa1111", "alpha", work)
    fake_tools.set_sessions([record], [])
    live = claude_sessions.get_session("alpha")
    name = claude_sessions.attach_in_screen(live, wait=0)
    assert name == "claude-aaaa1111"
    dm = [c["argv"] for c in fake_tools.screen_calls() if "-dmS" in c["argv"]]
    assert len(dm) == 1
    i = dm[0].index("-dmS")
    assert dm[0][i + 1] == name
    assert os.path.basename(dm[0][i + 2]) == "claude" and dm[0][i + 3:] == ["attach", "aaaa1111"]
    assert claude_sessions.attach_in_screen(live, wait=0) == name
    assert len([c for c in fake_tools.screen_calls() if "-dmS" in c["argv"]]) == 1


def test_attach_in_screen_without_screen_names_the_missing_binary(fake_tools, tmp_path, monkeypatch):
    work = _work(tmp_path)
    record = _record("aaaa1111", "alpha", work)
    fake_tools.set_sessions([record], [])
    no_screen = tmp_path / "no-screen"
    no_screen.mkdir()
    shutil.copy2(fake_tools.bin_dir / "claude", no_screen / "claude")
    monkeypatch.setenv("PATH", str(no_screen))
    with pytest.raises(ScreenNotFoundError, match="screen executable not found"):
        claude_sessions.attach_in_screen(claude_sessions.get_session("alpha"))


def test_type_into_sends_ctrl_u_text_enter_and_audits(fake_tools, tmp_path):
    work = _work(tmp_path)
    record = _record("aaaa1111", "alpha", work)
    fake_tools.set_sessions([record], [])
    live = claude_sessions.get_session("alpha")
    claude_sessions.attach_in_screen(live, wait=0)
    audit = tmp_path / "inject.jsonl"
    result = claude_sessions.type_into(live, "fix ^C now", audit_path=audit)
    stuffs = [c["argv"][-1] for c in fake_tools.screen_calls() if c["argv"][-2:-1] == ["stuff"]]
    assert stuffs == ["\x15", "fix \\^C now", "\r"]  # ^C is escaped, so it is not a real Ctrl-C
    assert (fake_tools.screen_state / "claude-aaaa1111.typed").read_bytes() == b"\x15fix \\^C now\r"
    line = json.loads(audit.read_text().strip())
    assert line["type"] == "inject" and line["target"] == "aaaa1111" and line["text"] == "fix ^C now"
    assert line["enter"] is True and result["screen"] == "claude-aaaa1111"


def test_type_into_no_enter_and_steer_attaches_a_fresh_session(fake_tools, tmp_path):
    work = _work(tmp_path)
    fake_tools.set_sessions([_record("aaaa1111", "alpha", work)], [])
    live = claude_sessions.get_session("alpha")
    claude_sessions.attach_in_screen(live, wait=0)
    claude_sessions.type_into(live, "without enter", enter=False)
    last = [c["argv"][-1] for c in fake_tools.screen_calls() if c["argv"][-2:-1] == ["stuff"]][-2:]
    assert last == ["\x15", "without enter"]

    other = _record("bbbb2222", "beta", work)
    fake_tools.set_sessions([_record("aaaa1111", "alpha", work), other], [])
    audit = tmp_path / "jobs" / "beta" / "inject.jsonl"
    claude_sessions.steer("beta", "continue", audit_path=audit)
    dm = [c["argv"] for c in fake_tools.screen_calls() if "-dmS" in c["argv"]]
    assert len(dm) == 2 and dm[-1][dm[-1].index("-dmS") + 1] == "claude-bbbb2222"
    beta_stuffs = [c["argv"][-1] for c in fake_tools.screen_calls()
                   if c["argv"][-2:-1] == ["stuff"] and "claude-bbbb2222" in c["argv"]]
    assert beta_stuffs == ["\x15", "continue", "\r"]
    assert json.loads(audit.read_text().strip())["text"] == "continue"


# --------------------------------------------------------------------------------------------------
# Stop / remove identifier safety
# --------------------------------------------------------------------------------------------------


def test_stop_and_remove_use_the_resolved_short_id_never_the_name(fake_tools, tmp_path):
    work = _work(tmp_path)
    alpha = _record("aaaa1111", "alpha", work)
    beta = _record("bbbb2222", "beta", work, status="idle", state="done")
    fake_tools.set_sessions([alpha], [beta])

    claude_sessions.stop("alpha")
    assert fake_tools.claude_calls()[-1]["argv"] == ["stop", "aaaa1111"]

    claude_sessions.remove(claude_sessions.get_session("beta"))
    assert fake_tools.claude_calls()[-1]["argv"] == ["rm", "bbbb2222"]
    action_args = [c["argv"] for c in fake_tools.claude_calls() if c["argv"][:1] in (["stop"], ["rm"])]
    assert all("alpha" not in argv and "beta" not in argv for argv in action_args)


def test_stop_and_remove_refuse_unknown_or_ambiguous_names_without_touching_claude(fake_tools, tmp_path):
    work = _work(tmp_path)
    fake_tools.set_sessions([_record("aaaa1111", "dup", work), _record("bbbb2222", "dup", work)], [])
    with pytest.raises(ClaudeSessionAmbiguousError):
        claude_sessions.stop("dup")
    with pytest.raises(ClaudeSessionNotFoundError):
        claude_sessions.remove("does-not-exist")
    actions = [c["argv"] for c in fake_tools.claude_calls() if c["argv"][:1] in (["stop"], ["rm"])]
    assert actions == []


def test_stop_surfaces_claude_stderr(fake_tools, tmp_path):
    work = _work(tmp_path)
    fake_tools.set_sessions([_record("aaaa1111", "alpha", work)], [])
    fake_tools.set_env(FAKE_CLAUDE_ACTION_FAIL="Error: session is still working\n")
    with pytest.raises(ClaudeCommandError) as exc:
        claude_sessions.stop("alpha")
    assert "still working" in str(exc.value)


# --------------------------------------------------------------------------------------------------
# CLI: pi-wave-claude
# --------------------------------------------------------------------------------------------------


def test_run_job_uses_the_local_bin_fallback_for_the_real_subprocess(tmp_path, monkeypatch):
    """`claude_command()` can find ~/.local/bin/claude when PATH does not; the delegated one-shot
    path must then actually run THAT binary, not a plain "claude" that Popen cannot find."""
    home = tmp_path / "home"
    script = home / ".local" / "bin" / "claude"
    script.parent.mkdir(parents=True)
    script.write_text(
        f"#!{PYTHON}\nimport json\nprint(json.dumps({CLAUDE_RESULT!r}))\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    work = _work(tmp_path)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    result = claude_sessions.run_job("j1", prompt="say it", model="haiku", cwd=work, out_dir=tmp_path / "out")
    assert result.ok and result.text == "KUMQUAT" and result.session_id == "8ac734fb-claude"


def test_cli_job_writes_clean_result_json(fake_tools, tmp_path):
    from pi_wave_kit.claude_cli import main

    work = _work(tmp_path)
    prompt = tmp_path / "prompt.md"
    prompt.write_text("say it", encoding="utf-8")
    jobs = tmp_path / "jobs"
    assert main(["job", "j1", str(prompt), "--cwd", str(work), "--model", "haiku",
                 "--jobs-dir", str(jobs)]) == 0
    payload = json.loads((jobs / "j1" / "result.json").read_text(encoding="utf-8"))
    assert payload["text"] == "KUMQUAT" and payload["session_id"] == "8ac734fb-claude"
    assert payload["model"] == "anthropic/claude-haiku-5-5" and payload["cost_usd"] == pytest.approx(0.00431512)
    assert payload["usage"]["prompt_tokens"] == 2 and payload["usage"]["cache_creation_tokens"] == 20983
    argv = [c["argv"] for c in fake_tools.claude_calls() if c["argv"][:1] == ["-p"]][-1]
    assert "--bg" not in argv and argv[-1] == "say it"

    assert main(["job", "j2", str(prompt), "--cwd", str(work), "--jobs-dir", str(jobs),
                 "--session", payload["session_id"]]) == 0
    resumed_argv = [c["argv"] for c in fake_tools.claude_calls() if c["argv"][:1] == ["-p"]][-1]
    assert resumed_argv[-3:] == ["--resume", payload["session_id"], "say it"]


def test_cli_job_failure_still_records_the_result_and_exits_1(fake_tools, tmp_path):
    from pi_wave_kit.claude_cli import main

    work = _work(tmp_path)
    prompt = tmp_path / "prompt.md"
    prompt.write_text("say it", encoding="utf-8")
    fake_tools.set_env(FAKE_CLAUDE_RESULT_EXIT=1)
    assert main(["job", "j1", str(prompt), "--cwd", str(work), "--jobs-dir", str(tmp_path / "jobs")]) == 1
    payload = json.loads((tmp_path / "jobs" / "j1" / "result.json").read_text(encoding="utf-8"))
    assert payload["returncode"] == 1 and payload["error"] and payload["text"] == "KUMQUAT"


def test_cli_start_list_status_and_logs(fake_tools, tmp_path, capsys):
    from pi_wave_kit.claude_cli import main

    work = _work(tmp_path)
    jobs = tmp_path / "jobs"
    assert main(["start", "alpha", "--prompt", "do it", "--cwd", str(work), "--model", "haiku",
                 "--jobs-dir", str(jobs)]) == 0
    record = json.loads((jobs / "alpha" / "session.json").read_text(encoding="utf-8"))
    assert record["id"] == "1efcedf4" and record["name"] == "alpha" and record["kind"] == "background"
    assert "1efcedf4" in capsys.readouterr().out

    fake_tools.set_sessions([_record("1efcedf4", "alpha", work)], [])
    assert main(["list", "--cwd", str(work)]) == 0
    assert "1efcedf4" in capsys.readouterr().out

    assert main(["list", "--all", "--json"]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert [s["short_id"] for s in listed] == ["1efcedf4"] and listed[0]["raw"]["pid"] == 4242

    assert main(["status", "alpha"]) == 0
    assert "status=busy" in capsys.readouterr().out

    fake_tools.set_env(FAKE_CLAUDE_LOGS="\x1b[32mHELLO\x1b[0m\n")
    assert main(["logs", "alpha"]) == 0
    assert capsys.readouterr().out == "HELLO\n"
    assert main(["logs", "alpha", "--raw"]) == 0
    assert "\x1b[32m" in capsys.readouterr().out


def test_cli_steer_stop_and_rm(fake_tools, tmp_path):
    from pi_wave_kit.claude_cli import main

    work = _work(tmp_path)
    jobs = tmp_path / "jobs"
    fake_tools.set_sessions([_record("1efcedf4", "alpha", work)], [])
    assert main(["steer", "alpha", "continue", "--jobs-dir", str(jobs)]) == 0
    text_file = tmp_path / "instruction.txt"
    text_file.write_text("from a file", encoding="utf-8")
    assert main(["steer", "alpha", "--text-file", str(text_file), "--jobs-dir", str(jobs)]) == 0
    audits = [json.loads(line) for line in (jobs / "alpha" / "inject.jsonl").read_text().splitlines()]
    assert [a["text"] for a in audits] == ["continue", "from a file"]
    assert main(["stop", "alpha"]) == 0
    assert fake_tools.claude_calls()[-1]["argv"] == ["stop", "1efcedf4"]
    assert main(["rm", "alpha"]) == 0
    assert fake_tools.claude_calls()[-1]["argv"] == ["rm", "1efcedf4"]


def test_cli_wait_reports_success_and_timeout(fake_tools, tmp_path, capsys):
    from pi_wave_kit.claude_cli import main

    work = _work(tmp_path)
    fake_tools.set_sessions([], [_record("1efcedf4", "alpha", work, status="idle", state="done")])
    assert main(["wait", "alpha", "--timeout", "1", "--poll", "0.01"]) == 0
    assert "finished" in capsys.readouterr().out

    fake_tools.set_sessions([_record("1efcedf4", "alpha", work)], [])
    assert main(["wait", "alpha", "--timeout", "0.1", "--poll", "0.02"]) == 4
    assert "timed out" in capsys.readouterr().err


def test_cli_start_and_job_pass_claude_permission_options(fake_tools, tmp_path):
    from pi_wave_kit.claude_cli import main

    work = _work(tmp_path)
    prompt = tmp_path / "prompt.md"
    prompt.write_text("do it", encoding="utf-8")
    assert main([
        "start", "alpha", "--prompt-file", str(prompt), "--cwd", str(work),
        "--allowed-tools", "Read,Grep,Glob", "--permission-mode", "dontAsk",
        "--add-dir", str(tmp_path), "--extra-arg=--append-system-prompt", "--extra-arg=guardrails",
        "--jobs-dir", str(tmp_path / "jobs"),
    ]) == 0
    argv = [c["argv"] for c in fake_tools.claude_calls() if "--bg" in c["argv"]][-1]
    assert argv[-9:] == [
        "--append-system-prompt", "guardrails",
        "--allowedTools", "Read,Grep,Glob", "--permission-mode", "dontAsk",
        "--add-dir", str(tmp_path), "do it",
    ]
    # The job path must carry the same options before the prompt.
    assert main([
        "job", "one", str(prompt), "--cwd", str(work),
        "--allowed-tools", "Read", "--permission-mode", "dontAsk",
        "--jobs-dir", str(tmp_path / "jobs2"),
    ]) == 0
    argv = [c["argv"] for c in fake_tools.claude_calls() if c["argv"][:1] == ["-p"]][-1]
    assert argv[-5:] == ["--allowedTools", "Read", "--permission-mode", "dontAsk", "do it"]


def test_cli_start_surfaces_the_trust_error_and_exit_code(fake_tools, tmp_path, capsys):
    from pi_wave_kit.claude_cli import main

    work = _work(tmp_path)
    fake_tools.set_env(FAKE_CLAUDE_BG_FAIL="Workspace not trusted\n")
    assert main(["start", "alpha", "--prompt", "do it", "--cwd", str(work)]) == 3
    err = capsys.readouterr().err
    assert "Workspace not trusted" in err and "accept the workspace trust" in err


def test_cli_unknown_session_is_exit_1_and_does_not_stop_anything(fake_tools, capsys):
    from pi_wave_kit.claude_cli import main

    fake_tools.set_sessions([], [])
    assert main(["stop", "not-a-session"]) == 1
    assert "no active and completed Claude session" in capsys.readouterr().err
    assert [c for c in fake_tools.claude_calls() if c["argv"][:1] == ["stop"]] == []

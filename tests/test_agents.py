"""pi_wave_kit.agents against fake opencode/codex/claude executables that print the exact output
shapes captured live from the real binaries (2026-10-30), and record their argv and environment --
same technique as conftest's fake_pi: the real subprocess + parsing path runs, nothing is mocked."""

import json
import os
import stat
import textwrap

import pytest

from pi_wave_kit import agents
from pi_wave_kit.wave import WaveJob, run_wave

# Real output lines, captured 2026-10-30 (ids shortened).
OPENCODE_OUT = [
    {"type": "step_start", "sessionID": "ses_A", "part": {"type": "step-start", "sessionID": "ses_A"}},
    {"type": "text", "sessionID": "ses_A", "part": {"type": "text", "text": "KUMQUAT", "sessionID": "ses_A"}},
    {"type": "step_finish", "sessionID": "ses_A", "part": {
        "type": "step-finish", "reason": "stop", "sessionID": "ses_A",
        "tokens": {"total": 17400, "input": 15731, "output": 5, "reasoning": 0, "cache": {"write": 0, "read": 1664}},
        "cost": 0.002367642}},
]
CODEX_OUT = [
    {"type": "thread.started", "thread_id": "01a18c63-thread"},
    {"type": "turn.started"},
    {"type": "item.completed", "item": {"id": "item_0", "type": "agent_message", "text": "KUMQUAT"}},
    {"type": "turn.completed", "usage": {"input_tokens": 14710, "cached_input_tokens": 4000,
                                         "cache_write_input_tokens": 0, "output_tokens": 8,
                                         "reasoning_output_tokens": 3}},
]
CODEX_FAILED = [
    {"type": "thread.started", "thread_id": "01a18c62-thread"},
    {"type": "turn.failed", "error": {"message": "The 'gpt-5.6-sol' model is not supported when using Codex "
                                                 "with a ChatGPT account."}},
]
CLAUDE_OUT = {
    "type": "result", "subtype": "success", "is_error": False, "result": "KUMQUAT",
    "session_id": "8ac734fb-claude", "total_cost_usd": 0.00431512,
    "usage": {"input_tokens": 2, "cache_creation_input_tokens": 20983, "cache_read_input_tokens": 11382,
              "output_tokens": 9, "output_tokens_details": {"thinking_tokens": 0}},
    "modelUsage": {"claude-haiku-5-5": {"inputTokens": 2, "outputTokens": 9}},
}


@pytest.fixture
def fake_agents(tmp_path, monkeypatch):
    """Fake opencode/codex/claude on PATH. Each appends {"argv", "env"} to calls.jsonl and prints the
    output from $FAKE_<NAME>_OUTPUT (a file of lines), exiting with $FAKE_<NAME>_EXIT (default 0)."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "calls.jsonl"
    for name in ("opencode", "codex", "claude"):
        script = bin_dir / name
        script.write_text(textwrap.dedent(f"""\
            #!/usr/bin/env python3
            import json, os, sys
            with open({str(calls)!r}, "a") as f:
                f.write(json.dumps({{"tool": {name!r}, "argv": sys.argv[1:], "env": dict(os.environ)}}) + "\\n")
            out = os.environ.get("FAKE_{name.upper()}_OUTPUT")
            if out:
                sys.stdout.write(open(out).read())
            sys.exit(int(os.environ.get("FAKE_{name.upper()}_EXIT", "0")))
        """), encoding="utf-8")
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ["PATH"])

    def set_output(name, lines, exit_code=0):
        path = tmp_path / f"{name}.out"
        if isinstance(lines, dict):
            path.write_text(json.dumps(lines), encoding="utf-8")
        else:
            path.write_text("".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8")
        monkeypatch.setenv(f"FAKE_{name.upper()}_OUTPUT", str(path))
        monkeypatch.setenv(f"FAKE_{name.upper()}_EXIT", str(exit_code))

    def read_calls():
        return [json.loads(line) for line in calls.read_text().splitlines()] if calls.exists() else []

    return set_output, read_calls


class _Ledger:
    def __init__(self):
        self.calls = []

    def log_call(self, run_pk, **kw):
        self.calls.append((run_pk, kw))


def test_opencode_job_reads_text_session_and_tokens(fake_agents, tmp_path):
    set_output, read_calls = fake_agents
    set_output("opencode", OPENCODE_OUT)
    ledger = _Ledger()
    r = agents.run_agent("opencode", "j1", prompt="say it", model="deepseek/deepseek-flash", cwd=tmp_path,
                         out_dir=tmp_path / "j1", ledger=ledger, run_pk=7)
    assert r.ok and r.text == "KUMQUAT" and r.session_id == "ses_A"
    assert (r.provider, r.model) == ("deepseek", "deepseek/deepseek-flash")
    assert (r.prompt_tokens, r.completion_tokens, r.cache_read_tokens) == (15731, 5, 1664)
    assert r.reported_cost_usd == pytest.approx(0.002367642)
    assert read_calls()[0]["argv"] == ["run", "--format", "json", "-m", "deepseek/deepseek-flash", "say it"]
    run_pk, logged = ledger.calls[0]
    assert run_pk == 7 and logged["billing"] == "api" and logged["external_id"] == "pi-wave-kit:opencode:j1"
    assert logged["prompt_tokens"] == 15731 and logged["api_equivalent_cost_usd"] == pytest.approx(0.002368)


def test_codex_splits_cached_input_out_of_input_tokens(fake_agents, tmp_path, monkeypatch):
    monkeypatch.delenv("CODEX_API_KEY", raising=False)
    set_output, read_calls = fake_agents
    set_output("codex", CODEX_OUT)
    r = agents.run_agent("codex", "j2", prompt="say it", model="gpt-5.6-luna", cwd=tmp_path, out_dir=tmp_path / "j2")
    assert r.ok and r.text == "KUMQUAT" and r.session_id == "01a18c63-thread"
    # input_tokens includes the cached part: 14710 - 4000 fresh, 4000 cached -- never priced twice.
    assert (r.prompt_tokens, r.cache_read_tokens, r.completion_tokens) == (10710, 4000, 8)
    assert (r.provider, r.model, r.reported_cost_usd) == ("openai", "openai/gpt-5.6-luna", 0.0)
    assert r.billing == "subscription"  # no CODEX_API_KEY: the ChatGPT login
    assert read_calls()[0]["argv"] == ["exec", "--json", "--skip-git-repo-check", "-m", "gpt-5.6-luna", "say it"]


def test_codex_failure_message_is_surfaced(fake_agents, tmp_path):
    set_output, _ = fake_agents
    set_output("codex", CODEX_FAILED, exit_code=1)
    r = agents.run_agent("codex", "j3", prompt="x", model="gpt-5.6-sol", cwd=tmp_path, out_dir=tmp_path / "j3")
    assert not r.ok and "not supported when using Codex with a ChatGPT account" in r.error
    assert agents.to_wave_result(r).status == "failed"


def test_claude_job_reads_result_object(fake_agents, tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    set_output, _ = fake_agents
    set_output("claude", CLAUDE_OUT)
    r = agents.run_agent("claude", "j4", prompt="say it", model="haiku", cwd=tmp_path, out_dir=tmp_path / "j4")
    assert r.ok and r.text == "KUMQUAT" and r.session_id == "8ac734fb-claude"
    assert (r.provider, r.model) == ("anthropic", "anthropic/claude-haiku-5-5")  # the real model, not the alias
    assert (r.prompt_tokens, r.cache_creation_tokens, r.cache_read_tokens, r.completion_tokens) == (2, 20983, 11382, 9)
    assert r.billing == "subscription"


def test_resume_passes_each_agents_own_session_flag(fake_agents, tmp_path):
    set_output, read_calls = fake_agents
    set_output("opencode", OPENCODE_OUT)
    set_output("codex", CODEX_OUT)
    set_output("claude", CLAUDE_OUT)
    for agent, model, sid in [("opencode", "deepseek/deepseek-flash", "ses_A"), ("codex", "gpt-5.6-luna", "T1"),
                              ("claude", "haiku", "S1")]:
        r = agents.run_agent(agent, f"r-{agent}", prompt="and now?", model=model, cwd=tmp_path,
                             out_dir=tmp_path / agent, session_id=sid)
        assert r.extra == {"resumed_session": sid}
    argv = {c["tool"]: c["argv"] for c in read_calls()}
    assert argv["opencode"] == ["run", "--format", "json", "-m", "deepseek/deepseek-flash", "--session", "ses_A",
                                "and now?"]
    assert argv["codex"] == ["exec", "resume", "--json", "--skip-git-repo-check", "-m", "gpt-5.6-luna", "T1",
                             "and now?"]
    assert argv["claude"] == ["-p", "--output-format", "json", "--model", "haiku", "--resume", "S1", "and now?"]


def test_resume_is_logged_under_its_own_external_id(fake_agents, tmp_path):
    set_output, _ = fake_agents
    set_output("claude", CLAUDE_OUT)
    ledger = _Ledger()
    agents.run_agent("claude", "j", prompt="a", model="haiku", cwd=tmp_path, out_dir=tmp_path / "a",
                     ledger=ledger, run_pk=1)
    agents.run_agent("claude", "j", prompt="b", model="haiku", cwd=tmp_path, out_dir=tmp_path / "b",
                     session_id="8ac734fb-claude", ledger=ledger, run_pk=1)
    ids = [kw["external_id"] for _, kw in ledger.calls]
    assert ids == ["pi-wave-kit:claude:j", "pi-wave-kit:claude:j:resume:8ac734fb-claude"]


def test_env_reaches_only_that_job_and_api_key_means_api_billing(fake_agents, tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    set_output, read_calls = fake_agents
    set_output("claude", CLAUDE_OUT)
    monkeypatch.setenv("CLAUDECODE", "1")  # as when run from inside a Claude Code session
    r = agents.run_agent("claude", "client-a", prompt="x", model="haiku", cwd=tmp_path, out_dir=tmp_path / "a",
                         env={"ANTHROPIC_API_KEY": "sk-client-a", "CLAUDE_CONFIG_DIR": "/tmp/claude-client-a"})
    agents.run_agent("claude", "client-b", prompt="x", model="haiku", cwd=tmp_path, out_dir=tmp_path / "b")
    env_a, env_b = (c["env"] for c in read_calls())
    assert env_a["ANTHROPIC_API_KEY"] == "sk-client-a" and env_a["CLAUDE_CONFIG_DIR"] == "/tmp/claude-client-a"
    assert "ANTHROPIC_API_KEY" not in env_b
    assert "CLAUDECODE" not in env_a  # a parent session's variables would stop the child saving its transcript
    assert r.billing == "api"
    assert "ANTHROPIC_API_KEY" not in os.environ  # the caller's own environment is untouched


def test_no_usage_means_nothing_logged(fake_agents, tmp_path):
    set_output, _ = fake_agents
    set_output("codex", CODEX_FAILED, exit_code=1)
    ledger = _Ledger()
    agents.run_agent("codex", "j", prompt="x", model="m", cwd=tmp_path, out_dir=tmp_path / "j", ledger=ledger, run_pk=1)
    assert ledger.calls == []


def test_timeout_kills_the_job(fake_agents, tmp_path, monkeypatch):
    set_output, _ = fake_agents
    bin_dir = tmp_path / "bin"
    (bin_dir / "codex").write_text("#!/bin/sh\nsleep 30\n")
    r = agents.run_agent("codex", "slow", prompt="x", model="m", cwd=tmp_path, out_dir=tmp_path / "s",
                         timeout_seconds=0.5)
    assert r.timed_out and not r.ok


def test_pi_goes_through_run_pi_and_can_be_resumed(fake_pi_resumable, tmp_path):
    first = agents.run_agent("pi", "p1", prompt="hi", model="deepseek/deepseek-flash", cwd=tmp_path,
                             out_dir=tmp_path / "p1")
    assert first.ok and first.session_id.endswith(".jsonl")
    assert (first.provider, first.model) == ("deepseek", "deepseek/deepseek-flash")
    again = agents.run_agent("pi", "p2", prompt="and?", model="deepseek/deepseek-flash", cwd=tmp_path,
                             out_dir=tmp_path / "p2", session_id=first.session_id)
    assert again.ok and again.session_id == first.session_id
    assert again.extra["records_before"] >= 1 and again.extra["records_after"] > again.extra["records_before"]


def test_run_wave_schedules_mixed_agents(fake_agents, fake_pi, tmp_path):
    set_output, _ = fake_agents
    set_output("opencode", OPENCODE_OUT)
    set_output("codex", CODEX_OUT)
    set_output("claude", CLAUDE_OUT)
    plan = {"a": ("opencode", "deepseek/deepseek-flash"), "b": ("codex", "gpt-5.6-luna"), "c": ("claude", "haiku"),
            "d": ("pi", "deepseek/deepseek-flash")}
    jobs = [WaveJob(job_id=j, cap_usd=0.5) for j in plan]
    summary = run_wave(
        jobs,
        launch_fn=lambda job: agents.start_agent(plan[job.job_id][0], job.job_id, prompt="go",
                                                 model=plan[job.job_id][1], cwd=tmp_path,
                                                 out_dir=tmp_path / "wave" / job.job_id),
        collect_fn=lambda handle, timed_out: agents.to_wave_result(
            agents.collect_agent_result(handle, timed_out=timed_out)),
        is_timed_out=agents.kill_if_timed_out,
        concurrency=4, wave_cap_usd=5.0, summary_path=tmp_path / "summary.json", poll_seconds=0.05,
    )
    assert summary.not_successful() == []
    assert {j: r.extra["agent"] for j, r in summary.finished.items()} == {k: v[0] for k, v in plan.items()}


def test_unknown_agent_is_rejected(tmp_path):
    with pytest.raises(ValueError):
        agents.start_agent("cursor", "x", prompt="p", model="m", cwd=tmp_path, out_dir=tmp_path)


def test_cli_agent_flag_runs_codex_and_writes_result_json(fake_agents, tmp_path):
    from pi_wave_kit.cli import main

    set_output, read_calls = fake_agents
    set_output("codex", CODEX_OUT)
    prompt = tmp_path / "prompt.md"
    prompt.write_text("say it", encoding="utf-8")
    rc = main(["cx-1", "gpt-5.6-luna", str(tmp_path), str(prompt), "--agent", "codex",
               "--jobs-dir", str(tmp_path / "jobs")])
    assert rc == 0
    payload = json.loads((tmp_path / "jobs" / "cx-1" / "result.json").read_text())
    assert payload["agent"] == "codex" and payload["text"] == "KUMQUAT"
    assert payload["session_id"] == "01a18c63-thread" and payload["model"] == "openai/gpt-5.6-luna"

    rc = main(["cx-2", "gpt-5.6-luna", str(tmp_path), str(prompt), "--agent", "codex",
               "--session", payload["session_id"], "--jobs-dir", str(tmp_path / "jobs")])
    assert rc == 0
    assert read_calls()[-1]["argv"][:3] == ["exec", "resume", "--json"]


def test_cli_without_agent_flag_still_runs_pi(fake_pi, tmp_path):
    from pi_wave_kit.cli import main

    prompt = tmp_path / "prompt.md"
    prompt.write_text("x", encoding="utf-8")
    assert main(["p", "deepseek-flash", str(tmp_path), str(prompt), "--jobs-dir", str(tmp_path / "jobs")]) == 0
    payload = json.loads((tmp_path / "jobs" / "p" / "result.json").read_text())
    assert "agent" not in payload and payload["prompt_tokens"] == 100  # the unchanged pi payload

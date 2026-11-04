"""Live per-job cost cap (issue #17): a running job's spend is read from its own session files and the job's
process group is killed once it exceeds its cap. Fake session files and a fake `pi` that spends, then hangs --
no model call anywhere."""

import json
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

from pi_wave_kit.run_pi import (
    PiHandle,
    PiResumeHandle,
    collect_pi_result,
    cost_capped,
    kill_reason,
    run_pi,
    session_cost_usd,
    start_pi,
)
from pi_wave_kit.wave import WaveJob, WaveJobResult, run_wave


def _usage_line(cost, as_number=False):
    usage = {"input": 10, "output": 5, "cost": cost if as_number else {"total": cost}}
    rid = f"r-{time.time_ns()}"
    return json.dumps({"type": "message", "id": rid, "timestamp": "2026-11-04T00:00:00Z",
                       "message": {"role": "assistant", "provider": "deepseek", "model": "deepseek-flash", "responseId": rid,
                                   "timestamp": "2026-11-04T00:00:00Z", "usage": usage, "content": []}}) + "\n"


def _sleeper():
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], start_new_session=True)


def _handle(tmp_path, proc, before=()):
    sessions = tmp_path / "sessions"
    sessions.mkdir(exist_ok=True)
    return PiHandle(job_id="j0", proc=proc, session_dir=sessions, session_files_before=set(before),
                    log_file=subprocess.DEVNULL, started_monotonic=time.monotonic(), timeout_seconds=None)


def test_session_cost_counts_only_new_files_and_tolerates_a_half_written_line(tmp_path):
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    old = sessions / "old.jsonl"
    old.write_text(_usage_line(5.0), encoding="utf-8")
    new = sessions / "new.jsonl"
    new.write_text(json.dumps({"type": "session"}) + "\n" + _usage_line(0.25) + _usage_line(0.5, as_number=True)
                   + '{"type": "message", "message": {"usage": {"cost', encoding="utf-8")  # truncated mid-write
    handle = SimpleNamespace(session_dir=sessions, session_files_before={old})
    assert session_cost_usd(handle) == pytest.approx(0.75)


def test_session_cost_of_a_resumed_session_counts_only_the_appended_records(tmp_path):
    session = tmp_path / "s.jsonl"
    session.write_text(_usage_line(1.0) + _usage_line(2.0) + _usage_line(0.125), encoding="utf-8")
    handle = PiResumeHandle(job_id="j", proc=None, session_path=session, records_before=2, log_file=None,
                            started_monotonic=0.0, timeout_seconds=None)
    assert session_cost_usd(handle) == pytest.approx(0.125)


def test_session_cost_unwraps_an_agents_pi_handle_and_is_zero_for_other_agents(tmp_path):
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    (sessions / "a.jsonl").write_text(_usage_line(0.3), encoding="utf-8")
    inner = SimpleNamespace(session_dir=sessions, session_files_before=set())
    assert session_cost_usd(SimpleNamespace(pi_handle=inner)) == pytest.approx(0.3)
    assert session_cost_usd(SimpleNamespace(pi_handle=None, output_path=None)) == 0.0


def test_cost_capped_kills_the_process_group_once_spend_exceeds_the_cap(tmp_path):
    proc = _sleeper()
    handle = _handle(tmp_path, proc)
    check = cost_capped(lambda h: False, cap_usd=0.10, min_interval_seconds=0)
    assert check(handle) is False  # nothing spent yet: the wrapped hook decides (False)
    (handle.session_dir / "s.jsonl").write_text(_usage_line(0.08) + _usage_line(0.07), encoding="utf-8")
    assert check(handle) is True
    assert proc.returncode is not None  # killed and reaped
    assert handle.kill_reason == "cost cap: spent $0.1500 > cap $0.1000"
    assert kill_reason(handle) == handle.kill_reason
    result = collect_pi_result(handle, timed_out=True)
    assert result.extra["kill_reason"].startswith("cost cap")
    assert result.cost_usd == pytest.approx(0.15)


def test_cost_capped_under_the_cap_delegates_to_the_wrapped_timeout_hook(tmp_path):
    proc = _sleeper()
    try:
        handle = _handle(tmp_path, proc)
        (handle.session_dir / "s.jsonl").write_text(_usage_line(0.05), encoding="utf-8")
        calls = []
        check = cost_capped(lambda h: calls.append(h) or False, cap_usd=1.0, min_interval_seconds=0)
        assert check(handle) is False and calls == [handle]
        assert handle.kill_reason == ""
    finally:
        proc.kill()
        proc.wait()


def test_cost_capped_requires_a_cap():
    with pytest.raises(ValueError):
        cost_capped(lambda h: False)


def test_run_pi_cap_usd_kills_a_runaway_job(spending_pi, tmp_path):
    result = run_pi("j0", provider="deepseek", model="deepseek-flash", thinking="low", prompt="x",
                    cwd=tmp_path, session_dir=tmp_path / "s", cap_usd=0.5, poll_seconds=0.05)
    assert result.timed_out
    assert result.extra["kill_reason"] == "cost cap: spent $1.0000 > cap $0.5000"


def test_run_wave_live_cost_cap_kills_records_and_never_resumes(spending_pi, tmp_path):
    def launch(job):
        return start_pi(job.job_id, provider="deepseek", model="deepseek-flash", thinking="low", prompt="x",
                        cwd=tmp_path, session_dir=tmp_path / "s" / job.job_id)

    def collect(h, timed_out):
        r = collect_pi_result(h, timed_out=timed_out)
        return WaveJobResult(h.job_id, "failed" if timed_out else "success", cost_usd=r.cost_usd,
                             reason="timed out" if timed_out else "")

    resumed = []
    summary = run_wave(
        [WaveJob("j0", cap_usd=0.5)], launch_fn=launch, collect_fn=collect, is_timed_out=lambda h: False,
        concurrency=1, wave_cap_usd=5.0, summary_path=tmp_path / "summary.json", poll_seconds=0.05,
        live_cost_cap=True, cost_poll_seconds=0, resume_fn=lambda *a: resumed.append(a), max_resumes=3,
    )
    r = summary.finished["j0"]
    assert r.status == "failed"
    assert r.reason.startswith("cost cap: spent $1.0000 > cap $0.5000")
    assert r.extra["kill_reason"].startswith("cost cap")
    assert resumed == []
    assert summary.committed_usd == pytest.approx(1.0)
    raw = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert raw["jobs"]["j0"]["reason"].startswith("cost cap")


def test_run_wave_without_live_cost_cap_lets_the_job_finish(spending_pi, tmp_path, monkeypatch):
    """Default off: same job, short hang, finishes normally whatever it spent (backward compatible)."""
    monkeypatch.setenv("FAKE_PI_HANG", "0.2")

    def launch(job):
        return start_pi(job.job_id, provider="deepseek", model="deepseek-flash", thinking="low", prompt="x",
                        cwd=tmp_path, session_dir=tmp_path / "s" / job.job_id)

    summary = run_wave(
        [WaveJob("j0", cap_usd=0.5)], launch_fn=launch,
        collect_fn=lambda h, t: WaveJobResult(h.job_id, "success", cost_usd=collect_pi_result(h, timed_out=t).cost_usd),
        is_timed_out=lambda h: False, concurrency=1, wave_cap_usd=5.0, summary_path=tmp_path / "summary.json",
        poll_seconds=0.05,
    )
    assert summary.finished["j0"].status == "success"

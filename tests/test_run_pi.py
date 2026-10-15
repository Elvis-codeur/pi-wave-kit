from pi_wave_kit.run_pi import collect_pi_result, kill_if_timed_out, run_pi, start_pi


def test_run_pi_reads_real_cost_from_the_session_file(fake_pi, tmp_path):
    result = run_pi(
        "job-1", provider="deepseek", model="deepseek-flash", thinking="low",
        cwd=tmp_path, session_dir=tmp_path / "sessions",
    )
    assert result.returncode == 0
    assert result.session_file is not None
    assert result.cost_usd == 0.001
    assert not result.timed_out


def test_run_pi_also_reports_real_token_counts_not_just_pis_own_cost_claim(fake_pi, tmp_path):
    """Real gap found during live testing (2026-10-15): only cost_usd (Pi's own reported figure, never
    trusted by a ledger service) was surfaced, so every real call was logged at a silent $0.00 until
    this was fixed -- a ledger needs raw token counts to compute real cost itself."""
    result = run_pi("job-1", provider="deepseek", model="deepseek-flash", thinking="low",
                      cwd=tmp_path, session_dir=tmp_path / "sessions")
    assert result.prompt_tokens == 100
    assert result.completion_tokens == 50
    assert result.provider == "deepseek"
    assert result.model == "deepseek/deepseek-flash"


def test_run_pi_reports_the_processs_real_exit_code(fake_pi, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_PI_EXIT_CODE", "3")
    result = run_pi("job-1", provider="deepseek", model="x", thinking="low", cwd=tmp_path, session_dir=tmp_path / "sessions")
    assert result.returncode == 3


def test_run_pi_kills_a_process_that_exceeds_its_timeout(fake_pi, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_PI_SLEEP", "5")
    result = run_pi("job-1", provider="deepseek", model="x", thinking="low", cwd=tmp_path,
                      session_dir=tmp_path / "sessions", timeout_seconds=0.2)
    assert result.timed_out
    assert result.returncode == -9  # killed by SIGKILL


def test_start_and_collect_non_blocking_pair(fake_pi, tmp_path):
    handle = start_pi("job-1", provider="deepseek", model="x", thinking="low", cwd=tmp_path, session_dir=tmp_path / "sessions")
    handle.proc.wait()  # test-only: a real caller polls, this just waits for the fake process to finish
    result = collect_pi_result(handle)
    assert result.returncode == 0 and result.cost_usd == 0.001


def test_kill_if_timed_out_only_kills_once_the_deadline_passes(fake_pi, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_PI_SLEEP", "5")
    handle = start_pi("job-1", provider="deepseek", model="x", thinking="low", cwd=tmp_path,
                        session_dir=tmp_path / "sessions", timeout_seconds=0.1)
    assert kill_if_timed_out(handle) is False  # too soon
    import time
    time.sleep(0.2)
    assert kill_if_timed_out(handle) is True
    assert handle.proc.poll() is not None


def test_two_concurrent_processes_sharing_one_session_dir_are_not_attributed_to_either(fake_pi, tmp_path):
    """The real collision case: two processes writing to the SAME session_dir concurrently -- each
    one's "before" snapshot predates the other's file, so both see 2 new files at the end. Must not
    crash or silently pick the wrong one for either -- session_file stays None, visible in `extra`."""
    shared = tmp_path / "shared-sessions"
    h1 = start_pi("job-1", provider="deepseek", model="x", thinking="low", cwd=tmp_path, session_dir=shared)
    h2 = start_pi("job-2", provider="deepseek", model="x", thinking="low", cwd=tmp_path, session_dir=shared)
    h1.proc.wait()
    h2.proc.wait()
    r1 = collect_pi_result(h1)
    r2 = collect_pi_result(h2)
    assert r1.session_file is None and r1.cost_usd == 0.0
    assert r2.session_file is None and r2.cost_usd == 0.0
    assert len(r1.extra["new_session_files"]) == 2


class _FakeLedger:
    """Records what log_call() was called with -- no real HTTP, this is purely for asserting the
    embedded-logging contract (what gets logged, not whether LedgerClient itself works)."""

    def __init__(self):
        self.calls = []

    def log_call(self, run_pk, **kwargs):
        self.calls.append((run_pk, kwargs))
        return {"id": len(self.calls)}


def test_run_pi_logs_to_the_ledger_automatically_when_given_one(fake_pi, tmp_path):
    """The actual point of embedding this: the caller does NOT call log_call() itself -- passing
    ledger+run_pk to run_pi() is the only thing it has to do, logging happens as a side effect."""
    ledger = _FakeLedger()
    result = run_pi(
        "job-1", provider="deepseek", model="deepseek-flash", thinking="low",
        cwd=tmp_path, session_dir=tmp_path / "sessions", ledger=ledger, run_pk=42,
    )
    assert len(ledger.calls) == 1
    run_pk, kwargs = ledger.calls[0]
    assert run_pk == 42
    assert kwargs["provider"] == result.provider
    assert kwargs["model"] == result.model
    assert kwargs["prompt_tokens"] == 100
    assert kwargs["completion_tokens"] == 50
    assert kwargs["billing"] == "api"
    assert kwargs["external_id"] == "pi-wave-kit:job-1"


def test_run_pi_does_not_log_when_no_ledger_is_given(fake_pi, tmp_path):
    """Backward-compatible: omitting ledger/run_pk changes nothing about existing behavior."""
    result = run_pi("job-1", provider="deepseek", model="x", thinking="low", cwd=tmp_path, session_dir=tmp_path / "sessions")
    assert result.cost_usd == 0.001  # unaffected


def test_run_pi_does_not_log_when_run_pk_is_missing_even_with_a_ledger(fake_pi, tmp_path):
    ledger = _FakeLedger()
    run_pi("job-1", provider="deepseek", model="x", thinking="low", cwd=tmp_path, session_dir=tmp_path / "sessions", ledger=ledger)
    assert ledger.calls == []


def test_collect_pi_result_does_not_log_when_the_process_produced_no_usage(fake_pi, tmp_path):
    """Two concurrent processes sharing a session_dir both end up with session_file=None/no usage --
    there's nothing real to log, and this must not crash or log a bogus zero-usage call."""
    ledger = _FakeLedger()
    shared = tmp_path / "shared-sessions"
    h1 = start_pi("job-1", provider="deepseek", model="x", thinking="low", cwd=tmp_path, session_dir=shared)
    h2 = start_pi("job-2", provider="deepseek", model="x", thinking="low", cwd=tmp_path, session_dir=shared)
    h1.proc.wait()
    h2.proc.wait()
    collect_pi_result(h1, ledger=ledger, run_pk=1)
    collect_pi_result(h2, ledger=ledger, run_pk=1)
    assert ledger.calls == []

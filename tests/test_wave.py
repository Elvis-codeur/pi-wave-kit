"""The budget-aware rolling pool, with a FAKE launch_fn/collect_fn -- no real subprocess needed to
exercise the scheduling logic itself (test_run_pi.py covers the real-subprocess integration)."""

from pi_wave_kit.wave import WaveJob, WaveJobResult, run_wave


class _FakeHandle:
    def __init__(self, job_id, cost_usd=0.1, status="success"):
        self.job_id = job_id
        self.cost_usd = cost_usd
        self.status = status
        self.proc = self

    def poll(self):
        return 0  # always "finished" the moment it's checked -- these tests are about the SCHEDULING


def _launcher(costs):
    def launch(job):
        return _FakeHandle(job.job_id, cost_usd=costs.get(job.job_id, 0.1))
    return launch


def _collector(handle, timed_out):
    return WaveJobResult(job_id=handle.job_id, status="failed" if timed_out else handle.status, cost_usd=handle.cost_usd)


def test_launches_every_job_when_well_under_budget(tmp_path):
    jobs = [WaveJob(f"j{i}", cap_usd=0.5) for i in range(3)]
    summary = run_wave(
        jobs, launch_fn=_launcher({}), collect_fn=_collector, is_timed_out=lambda h: False,
        concurrency=3, wave_cap_usd=10, summary_path=tmp_path / "summary.json",
    )
    assert sorted(summary.launched) == ["j0", "j1", "j2"]
    assert summary.not_launched == []
    assert all(r.status == "success" for r in summary.finished.values())


def test_stops_launching_once_the_wave_cap_would_be_exceeded(tmp_path):
    jobs = [WaveJob("j0", cap_usd=5.0), WaveJob("j1", cap_usd=5.0), WaveJob("j2", cap_usd=5.0)]
    summary = run_wave(
        jobs, launch_fn=_launcher({"j0": 5.0, "j1": 5.0}), collect_fn=_collector, is_timed_out=lambda h: False,
        concurrency=3, wave_cap_usd=10.0, summary_path=tmp_path / "summary.json",
    )
    # j0 and j1 commit $5 each = $10, exactly the cap; j2 can never fit after that
    assert "j2" in summary.not_launched
    assert summary.stop_reason


def test_a_single_job_whose_cap_alone_exceeds_the_wave_cap_never_launches(tmp_path):
    jobs = [WaveJob("too-big", cap_usd=100.0)]
    summary = run_wave(
        jobs, launch_fn=_launcher({}), collect_fn=_collector, is_timed_out=lambda h: False,
        concurrency=1, wave_cap_usd=10.0, summary_path=tmp_path / "summary.json",
    )
    assert summary.not_launched == ["too-big"]
    assert "wave cap" in summary.stop_reason


def test_resuming_skips_jobs_already_successful_in_the_summary_file(tmp_path):
    summary_path = tmp_path / "summary.json"
    jobs = [WaveJob("j0", cap_usd=1.0), WaveJob("j1", cap_usd=1.0)]
    events = []
    run_wave(jobs, launch_fn=_launcher({}), collect_fn=_collector, is_timed_out=lambda h: False,
              concurrency=2, wave_cap_usd=10, summary_path=summary_path, on_event=events.append)
    assert "j0" not in " ".join(e for e in events if e.startswith("skip"))

    events2 = []
    # re-run the SAME job list: both already succeeded, so neither should be launched again
    summary2 = run_wave(jobs, launch_fn=_launcher({}), collect_fn=_collector, is_timed_out=lambda h: False,
                          concurrency=2, wave_cap_usd=10, summary_path=summary_path, on_event=events2.append)
    assert summary2.launched == []
    assert any("skip j0" in e for e in events2) and any("skip j1" in e for e in events2)


def test_stop_file_halts_new_launches_but_lets_running_jobs_finish(tmp_path):
    stop = tmp_path / "STOP"
    stop.write_text("", encoding="utf-8")
    jobs = [WaveJob("j0", cap_usd=1.0)]
    summary = run_wave(jobs, launch_fn=_launcher({}), collect_fn=_collector, is_timed_out=lambda h: False,
                         concurrency=1, wave_cap_usd=10, summary_path=tmp_path / "summary.json", stop_file=stop)
    assert summary.not_launched == ["j0"]
    assert "stop file" in summary.stop_reason


def test_a_job_that_fails_to_even_start_is_recorded_as_failed_not_a_crash(tmp_path):
    def exploding_launch(job):
        raise RuntimeError("no such executable")

    jobs = [WaveJob("j0", cap_usd=1.0)]
    summary = run_wave(jobs, launch_fn=exploding_launch, collect_fn=_collector, is_timed_out=lambda h: False,
                         concurrency=1, wave_cap_usd=10, summary_path=tmp_path / "summary.json")
    assert summary.finished["j0"].status == "failed"
    assert "no such executable" in summary.finished["j0"].reason


def test_committed_cost_accumulates_from_real_finished_job_costs(tmp_path):
    jobs = [WaveJob("j0", cap_usd=1.0), WaveJob("j1", cap_usd=1.0)]
    summary = run_wave(jobs, launch_fn=_launcher({"j0": 0.3, "j1": 0.4}), collect_fn=_collector,
                         is_timed_out=lambda h: False, concurrency=2, wave_cap_usd=10, summary_path=tmp_path / "summary.json")
    assert summary.committed_usd == 0.7


def test_not_successful_reports_failed_jobs(tmp_path):
    jobs = [WaveJob("j0", cap_usd=1.0)]
    summary = run_wave(jobs, launch_fn=_launcher({}), collect_fn=lambda h, t: WaveJobResult(job_id=h.job_id, status="failed", reason="oops"),
                         is_timed_out=lambda h: False, concurrency=1, wave_cap_usd=10, summary_path=tmp_path / "summary.json")
    assert summary.not_successful() == ["j0"]


class _TimeoutOnceHandle(_FakeHandle):
    def __init__(self, job_id, cost_usd=0.1, status="success", times_out=False):
        super().__init__(job_id, cost_usd, status)
        self.times_out = times_out


def test_a_timed_out_job_is_resumed_and_its_earlier_spend_still_counts(tmp_path):
    started = []

    def launch(job):
        started.append("first")
        return _TimeoutOnceHandle(job.job_id, cost_usd=0.2, times_out=True)

    def resume(job, handle, result):
        started.append("resume")
        assert result.cost_usd == 0.2
        return _TimeoutOnceHandle(job.job_id, cost_usd=0.3)

    summary = run_wave(
        [WaveJob("j0", cap_usd=1.0)], launch_fn=launch, collect_fn=_collector, is_timed_out=lambda h: h.times_out,
        concurrency=1, wave_cap_usd=5, summary_path=tmp_path / "summary.json", resume_fn=resume, max_resumes=2,
    )
    assert started == ["first", "resume"]
    assert summary.finished["j0"].status == "success"
    assert round(summary.committed_usd, 2) == 0.5  # 0.2 (timed-out attempt) + 0.3 (resumed attempt)


def test_resumes_stop_after_max_resumes_and_the_job_fails(tmp_path):
    def launch(job):
        return _TimeoutOnceHandle(job.job_id, cost_usd=0.1, times_out=True)

    summary = run_wave(
        [WaveJob("j0", cap_usd=1.0)], launch_fn=launch, collect_fn=_collector, is_timed_out=lambda h: h.times_out,
        concurrency=1, wave_cap_usd=5, summary_path=tmp_path / "summary.json",
        resume_fn=lambda job, h, r: _TimeoutOnceHandle(job.job_id, cost_usd=0.1, times_out=True), max_resumes=2,
    )
    assert summary.finished["j0"].status == "failed"
    assert round(summary.committed_usd, 2) == 0.3  # first attempt + 2 resumed attempts, all counted


def test_without_resume_fn_a_timeout_is_still_a_failure(tmp_path):
    summary = run_wave(
        [WaveJob("j0", cap_usd=1.0)], launch_fn=lambda job: _TimeoutOnceHandle(job.job_id, times_out=True), collect_fn=_collector,
        is_timed_out=lambda h: h.times_out, concurrency=1, wave_cap_usd=5, summary_path=tmp_path / "summary.json",
    )
    assert summary.finished["j0"].status == "failed"

"""pi-wave-run (issue #20): a capped wave over prompt files. Dry run by default; real runs only against fake
`pi` executables (conftest), never a model."""

import json
import os
import stat
import textwrap

import pytest

from pi_wave_kit.wave_cli import _parse_args, load_jobs, main

FAST = ["--poll-seconds", "0.05", "--cost-poll-seconds", "0"]


def _prompts(tmp_path, names=("a", "b")):
    d = tmp_path / "prompts"
    d.mkdir()
    for n in names:
        (d / f"{n}.md").write_text(f"task {n}", encoding="utf-8")
    return d


def test_load_jobs_from_a_prompts_dir_uses_file_stems_in_order(tmp_path):
    d = _prompts(tmp_path, ("b", "a"))
    (d / "notes.txt").write_text("ignored", encoding="utf-8")
    jobs = load_jobs(_parse_args(["--prompts-dir", str(d), "--wave-cap-usd", "1", "--job-cap-usd", "0.2"]))
    assert [(j.job_id, j.cap_usd) for j in jobs] == [("a", 0.2), ("b", 0.2)]


def test_load_jobs_from_a_job_list_with_ids_caps_and_comments(tmp_path):
    d = _prompts(tmp_path)
    lst = tmp_path / "jobs.txt"
    lst.write_text("# wave 3\nprompts/a.md\njob-b prompts/b.md 0.5   # bigger\n\n", encoding="utf-8")
    jobs = load_jobs(_parse_args(["--job-list", str(lst), "--wave-cap-usd", "1", "--job-cap-usd", "0.2"]))
    assert [(j.job_id, j.prompt_file, j.cap_usd) for j in jobs] == [("a", d / "a.md", 0.2), ("job-b", d / "b.md", 0.5)]


@pytest.mark.parametrize("content,needle", [
    ("x prompts/a.md\nx prompts/b.md\n", "duplicate job id"),
    ("prompts/missing.md\n", "no such prompt file"),
    ("j prompts/a.md lots\n", "not a number"),
])
def test_load_jobs_rejects_bad_lists(tmp_path, content, needle):
    _prompts(tmp_path)
    lst = tmp_path / "jobs.txt"
    lst.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError, match=needle):
        load_jobs(_parse_args(["--job-list", str(lst), "--wave-cap-usd", "1", "--job-cap-usd", "0.2"]))


def test_a_source_and_both_caps_are_required(capsys):
    with pytest.raises(SystemExit):
        _parse_args(["--wave-cap-usd", "1", "--job-cap-usd", "0.2"])
    with pytest.raises(SystemExit):
        _parse_args(["--prompts-dir", "p", "--job-cap-usd", "0.2"])


def test_dry_run_is_the_default_prints_projection_and_worst_case_and_launches_nothing(tmp_path, capsys):
    d = _prompts(tmp_path)
    out = tmp_path / "out"
    rc = main(["--prompts-dir", str(d), "--wave-cap-usd", "5", "--job-cap-usd", "0.4", "--out-dir", str(out)])
    assert rc == 0
    text = capsys.readouterr().out
    assert "2 jobs, 2 to run" in text
    assert "projected: $0.40 (ASSUMPTION" in text
    assert "worst case: $0.80" in text
    assert "DRY RUN" in text and "--yes-spend" in text
    assert "PEAK" in text
    assert not out.exists()  # nothing created, nothing launched (no fake pi is even on PATH)


def test_dry_run_worst_case_is_bounded_by_the_wave_cap(tmp_path, capsys):
    d = _prompts(tmp_path, ("a", "b", "c"))
    main(["--prompts-dir", str(d), "--wave-cap-usd", "1", "--job-cap-usd", "0.5", "--projected-usd", "0.1",
          "--out-dir", str(tmp_path / "out")])
    text = capsys.readouterr().out
    assert "worst case: $1.00" in text and "projected: $0.30\n" in text
    assert "allows only 2 job(s) at once" in text


def test_budget_file_clips_the_wave_cap_and_refuses_when_no_job_fits(tmp_path, capsys):
    d = _prompts(tmp_path)
    budget = tmp_path / "budget.json"
    budget.write_text(json.dumps({"total_usd": 1.0, "rounds": [{"spent_usd": 0.7}]}), encoding="utf-8")
    rc = main(["--prompts-dir", str(d), "--wave-cap-usd", "5", "--job-cap-usd", "0.3", "--budget-file", str(budget),
               "--out-dir", str(tmp_path / "out")])
    captured = capsys.readouterr()
    assert "wave cap: $0.25 (clipped by budget file: $0.30 left" in captured.out
    assert rc == 1 and "refused" in captured.err


def test_missing_budget_file_is_an_error_not_an_invented_total(tmp_path, capsys):
    d = _prompts(tmp_path)
    rc = main(["--prompts-dir", str(d), "--wave-cap-usd", "5", "--job-cap-usd", "0.3",
               "--budget-file", str(tmp_path / "nope.json")])
    assert rc == 2 and "no such budget file" in capsys.readouterr().err


def test_yes_spend_runs_the_wave_writes_summaries_and_records_the_budget_round(fake_pi, tmp_path, capsys):
    d = _prompts(tmp_path)
    out = tmp_path / "out"
    budget = tmp_path / "budget.json"
    budget.write_text(json.dumps({"total_usd": 10.0, "rounds": []}), encoding="utf-8")
    rc = main(["--prompts-dir", str(d), "--wave-cap-usd", "5", "--job-cap-usd", "0.4", "--out-dir", str(out),
               "--budget-file", str(budget), "--round-name", "r1", "--yes-spend", *FAST])
    assert rc == 0
    result = json.loads((out / "wave-result.json").read_text(encoding="utf-8"))
    assert result["committed_usd"] == pytest.approx(0.002)  # fake pi reports $0.001 per job
    assert set(result["jobs"]) == {"a", "b"} and all(j["status"] == "success" for j in result["jobs"].values())
    job = json.loads((out / "a" / "job.json").read_text(encoding="utf-8"))
    assert job["status"] == "success" and len(job["prompt_sha256"]) == 64 and job["attempts"][0]["returncode"] == 0
    rounds = json.loads(budget.read_text(encoding="utf-8"))["rounds"]
    assert rounds == [{"round": "r1", "spent_usd": 0.002, "jobs": 2, "finished_utc": rounds[0]["finished_utc"]}]

    # Re-running the same command is resumable: nothing left to run, nothing spent.
    capsys.readouterr()
    rc = main(["--prompts-dir", str(d), "--wave-cap-usd", "5", "--job-cap-usd", "0.4", "--out-dir", str(out), "--yes-spend"])
    assert rc == 0 and "every job already succeeded" in capsys.readouterr().out


def test_live_cap_kills_a_runaway_job_and_the_wave_reports_it(spending_pi, tmp_path):
    d = _prompts(tmp_path, ("a",))
    out = tmp_path / "out"
    rc = main(["--prompts-dir", str(d), "--wave-cap-usd", "5", "--job-cap-usd", "0.5", "--out-dir", str(out),
               "--yes-spend", *FAST])
    assert rc == 1
    result = json.loads((out / "wave-result.json").read_text(encoding="utf-8"))
    assert result["jobs"]["a"]["reason"].startswith("cost cap: spent $1.0000 > cap $0.5000")
    assert result["not_successful"] == ["a"]


def test_require_output_fails_a_job_that_wrote_nothing(fake_pi, tmp_path):
    d = _prompts(tmp_path, ("a",))
    out = tmp_path / "out"
    rc = main(["--prompts-dir", str(d), "--wave-cap-usd", "5", "--job-cap-usd", "0.5", "--out-dir", str(out),
               "--per-job-workdir", "--require-output", "result.txt", "--yes-spend", *FAST])
    assert rc == 1
    reason = json.loads((out / "wave-result.json").read_text(encoding="utf-8"))["jobs"]["a"]["reason"]
    assert "required output missing" in reason


def test_stop_file_stops_new_launches(fake_pi, tmp_path):
    d = _prompts(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    (out / "STOP").write_text("", encoding="utf-8")
    rc = main(["--prompts-dir", str(d), "--wave-cap-usd", "5", "--job-cap-usd", "0.5", "--out-dir", str(out),
               "--yes-spend", *FAST])
    assert rc == 1
    result = json.loads((out / "wave-result.json").read_text(encoding="utf-8"))
    assert sorted(result["not_launched"]) == ["a", "b"] and "stop file" in result["stop_reason"]


@pytest.fixture
def hang_then_resume_pi(tmp_path, monkeypatch):
    """First launch writes a session and hangs (hits the timeout); a `--session <file>` resume appends one
    usage record and exits 0."""
    script = tmp_path / "rbin" / "pi"
    script.parent.mkdir()
    script.write_text(textwrap.dedent("""\
        #!/usr/bin/env python3
        import json, os, sys, time
        args = sys.argv[1:]
        rec = {"type": "message", "id": f"m-{time.time_ns()}", "timestamp": "2026-11-04T00:00:00Z",
               "message": {"role": "assistant", "provider": "deepseek", "model": "deepseek-flash",
                           "responseId": f"r-{time.time_ns()}", "timestamp": "2026-11-04T00:00:00Z",
                           "usage": {"input": 1, "output": 1, "cost": {"total": 0.01}}, "content": []}}
        if "--session" in args:
            with open(args[args.index("--session") + 1], "a") as f:
                f.write(json.dumps(rec) + "\\n")
            sys.exit(0)
        d = args[args.index("--session-dir") + 1]
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, f"s-{os.getpid()}.jsonl"), "w") as f:
            f.write(json.dumps(rec) + "\\n")
        time.sleep(60)
    """), encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", str(script.parent) + os.pathsep + os.environ["PATH"])


def test_max_resumes_continues_a_timed_out_job_in_its_own_session(hang_then_resume_pi, tmp_path):
    d = _prompts(tmp_path, ("a",))
    out = tmp_path / "out"
    rc = main(["--prompts-dir", str(d), "--wave-cap-usd", "5", "--job-cap-usd", "0.5", "--out-dir", str(out),
               "--timeout", "0.5", "--max-resumes", "1", "--yes-spend", *FAST])
    assert rc == 0
    result = json.loads((out / "wave-result.json").read_text(encoding="utf-8"))
    assert result["committed_usd"] == pytest.approx(0.02)  # timed-out attempt + resumed attempt
    job = json.loads((out / "a" / "job.json").read_text(encoding="utf-8"))
    assert [a["timed_out"] for a in job["attempts"]] == [True, False]


def test_help_lists_caps_dry_run_budget_and_examples(capsys):
    with pytest.raises(SystemExit):
        main(["--help"])
    out = capsys.readouterr().out
    for needle in ("--yes-spend", "--wave-cap-usd", "--job-cap-usd", "--budget-file", "live job cap", "PEAK",
                   "STOP", "examples:", "job list format"):
        assert needle in out

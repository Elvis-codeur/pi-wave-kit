"""The console-script CLI (pi-wave-job): a single ad-hoc job built on the tested run_pi() path,
no file-staging step -- see pi_wave_kit/cli.py's module docstring for why that matters (the exact
bug class in agentic-reasoning-translator issue #1 / ERRATA #43 is structurally impossible here,
because the prompt is read once and passed straight through, never copied to a destination path)."""

import json

from pi_wave_kit.cli import main


def test_cli_runs_a_job_and_writes_result_json(fake_pi, tmp_path, capsys):
    prompt_file = tmp_path / "prompt.md"
    prompt_file.write_text("do the thing", encoding="utf-8")
    jobs_dir = tmp_path / "jobs"

    rc = main([
        "job-1", "deepseek-flash", str(tmp_path), str(prompt_file),
        "--jobs-dir", str(jobs_dir),
    ])

    assert rc == 0
    result_path = jobs_dir / "job-1" / "result.json"
    assert result_path.is_file()
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    assert payload["returncode"] == 0
    assert payload["cost_usd"] == 0.001
    assert payload["prompt_tokens"] == 100
    out = capsys.readouterr().out
    assert "job-1" in out and "cost_usd=0.0010" in out


def test_cli_passes_the_prompt_files_content_as_a_real_argv_string_not_a_staged_file(fake_pi, tmp_path):
    """The exact fix for the bug class this CLI avoids: the prompt file can sit at ANY path,
    including one that would collide with a staging destination in the old shell-script approach
    -- there is no copy step here at all, so no destination-path collision is even possible."""
    prompt_file = tmp_path / "jobs" / "job-1" / "prompt.md"
    prompt_file.parent.mkdir(parents=True)
    prompt_file.write_text("same path as where pi_job.sh would have staged it", encoding="utf-8")

    rc = main([
        "job-1", "x", str(tmp_path), str(prompt_file),
        "--jobs-dir", str(tmp_path / "jobs"),
    ])

    assert rc == 0  # pi_job.sh's cp step would have aborted here with "are the same file"


def test_cli_rejects_a_missing_prompt_file_without_launching_anything(tmp_path, monkeypatch, capsys):
    # No fake_pi on PATH at all -- if the CLI tried to launch pi, this would fail differently
    # (FileNotFoundError) rather than returning the early validation error below.
    rc = main([
        "job-1", "x", str(tmp_path), str(tmp_path / "does-not-exist.md"),
        "--jobs-dir", str(tmp_path / "jobs"),
    ])
    assert rc == 2
    assert not (tmp_path / "jobs" / "job-1" / "result.json").exists()
    assert "no such prompt file" in capsys.readouterr().err


def test_cli_rejects_an_empty_prompt_file(tmp_path, capsys):
    prompt_file = tmp_path / "empty.md"
    prompt_file.write_text("   \n", encoding="utf-8")
    rc = main([
        "job-1", "x", str(tmp_path), str(prompt_file),
        "--jobs-dir", str(tmp_path / "jobs"),
    ])
    assert rc == 2
    assert "empty prompt file" in capsys.readouterr().err


def test_cli_nonzero_exit_code_is_surfaced(fake_pi, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_PI_EXIT_CODE", "3")
    prompt_file = tmp_path / "prompt.md"
    prompt_file.write_text("do the thing", encoding="utf-8")
    rc = main([
        "job-1", "x", str(tmp_path), str(prompt_file),
        "--jobs-dir", str(tmp_path / "jobs"),
    ])
    assert rc == 1


def test_cli_with_mem_max_runs_under_systemd_run(fake_pi, fake_systemd_run, tmp_path):
    prompt_file = tmp_path / "prompt.md"
    prompt_file.write_text("do the thing", encoding="utf-8")
    rc = main([
        "job-1", "x", str(tmp_path), str(prompt_file),
        "--jobs-dir", str(tmp_path / "jobs"), "--mem-max", "300M",
    ])
    assert rc == 0
    payload = json.loads((tmp_path / "jobs" / "job-1" / "result.json").read_text(encoding="utf-8"))
    assert payload["returncode"] == 0


def test_cli_without_mem_max_does_not_require_systemd_run(fake_pi, tmp_path):
    """No --mem-max means no cgroup is built at all -- systemd-run need not even be on PATH."""
    prompt_file = tmp_path / "prompt.md"
    prompt_file.write_text("do the thing", encoding="utf-8")
    rc = main([
        "job-1", "x", str(tmp_path), str(prompt_file),
        "--jobs-dir", str(tmp_path / "jobs"),
    ])
    assert rc == 0

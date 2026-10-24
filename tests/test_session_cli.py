"""The console-script CLI (pi-wave-session) over pi_wave_kit.interactive: launch/status/hardcopy/stop
a long-lived, remotely-reachable session without writing Python. Uses the fake_pi/fake_screen
fixtures (same as test_interactive.py) so no real screen/pi binary is required."""

import json
import time

from pi_wave_kit.session_cli import main


def test_launch_writes_mesh_autoregister_config_when_missing(fake_pi, fake_screen, tmp_path):
    workdir = tmp_path / "work"
    workdir.mkdir()
    rc = main([
        "launch", "alpha", "x", str(workdir), "--prompt", "stand by",
        "--jobs-dir", str(tmp_path / "jobs"),
    ])
    assert rc == 0
    cfg = json.loads((workdir / ".pi" / "pi-messenger.json").read_text(encoding="utf-8"))
    assert cfg == {"autoRegister": True}


def test_launch_does_not_overwrite_an_existing_mesh_config(fake_pi, fake_screen, tmp_path):
    workdir = tmp_path / "work"
    (workdir / ".pi").mkdir(parents=True)
    existing = {"autoRegister": False, "somethingElse": 1}
    (workdir / ".pi" / "pi-messenger.json").write_text(json.dumps(existing), encoding="utf-8")

    rc = main([
        "launch", "alpha", "x", str(workdir), "--prompt", "stand by",
        "--jobs-dir", str(tmp_path / "jobs"),
    ])
    assert rc == 0
    cfg = json.loads((workdir / ".pi" / "pi-messenger.json").read_text(encoding="utf-8"))
    assert cfg == existing  # untouched


def test_no_mesh_flag_skips_writing_any_config(fake_pi, fake_screen, tmp_path):
    workdir = tmp_path / "work"
    workdir.mkdir()
    rc = main([
        "launch", "alpha", "x", str(workdir), "--prompt", "stand by",
        "--jobs-dir", str(tmp_path / "jobs"), "--no-mesh",
    ])
    assert rc == 0
    assert not (workdir / ".pi" / "pi-messenger.json").exists()


def test_launch_with_prompt_file(fake_pi, fake_screen, tmp_path):
    workdir = tmp_path / "work"
    workdir.mkdir()
    prompt_file = tmp_path / "prompt.md"
    prompt_file.write_text("stand by please", encoding="utf-8")
    rc = main([
        "launch", "alpha", "x", str(workdir), "--prompt-file", str(prompt_file),
        "--jobs-dir", str(tmp_path / "jobs"),
    ])
    assert rc == 0


def test_launch_rejects_a_missing_prompt_file(fake_pi, fake_screen, tmp_path):
    workdir = tmp_path / "work"
    workdir.mkdir()
    rc = main([
        "launch", "alpha", "x", str(workdir), "--prompt-file", str(tmp_path / "nope.md"),
        "--jobs-dir", str(tmp_path / "jobs"),
    ])
    assert rc == 2


def test_status_reports_alive_then_not_running(fake_pi, fake_screen, tmp_path, monkeypatch, capsys):
    workdir = tmp_path / "work"
    workdir.mkdir()
    monkeypatch.setenv("FAKE_PI_SLEEP", "2")
    rc = main([
        "launch", "alpha", "x", str(workdir), "--prompt", "stand by",
        "--jobs-dir", str(tmp_path / "jobs"),
    ])
    assert rc == 0

    rc = main(["status", "alpha"])
    assert rc == 0
    assert "alive" in capsys.readouterr().out

    monkeypatch.delenv("FAKE_PI_SLEEP", raising=False)
    rc = main(["stop", "alpha"])
    assert rc == 0
    time.sleep(0.2)
    rc = main(["status", "alpha"])
    assert rc == 1
    assert "not running" in capsys.readouterr().out


def test_hardcopy_writes_and_prints_the_dump(fake_pi, fake_screen, tmp_path, monkeypatch, capsys):
    workdir = tmp_path / "work"
    workdir.mkdir()
    monkeypatch.setenv("FAKE_PI_SLEEP", "2")
    main([
        "launch", "alpha", "x", str(workdir), "--prompt", "stand by",
        "--jobs-dir", str(tmp_path / "jobs"),
    ])

    rc = main(["hardcopy", "alpha", "--jobs-dir", str(tmp_path / "jobs")])
    assert rc == 0
    out_path = tmp_path / "jobs" / "alpha" / "hardcopy.txt"
    assert out_path.is_file()
    assert "alpha" in out_path.read_text(encoding="utf-8")

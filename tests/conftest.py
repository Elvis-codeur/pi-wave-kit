"""A fake `pi` executable on PATH, same technique the project this library was extracted from used
(tests/test_pi_wave.py, agentic-doc-treatement): writes a synthetic session JSONL with a real usage
record, so run_pi.py's cost-reading path is exercised against a real file, not mocked away."""

import os
import stat
import textwrap

import pytest


@pytest.fixture
def fake_pi(tmp_path, monkeypatch):
    """Returns the path to a fake `pi` script and puts it first on PATH. The script writes one session
    file to --session-dir with a single assistant usage record, then exits 0 (or with
    FAKE_PI_EXIT_CODE/FAKE_PI_SLEEP from the environment, settable per-test)."""
    script = tmp_path / "pi"
    script.write_text(textwrap.dedent("""\
        #!/usr/bin/env python3
        import json, os, sys, time
        args = sys.argv[1:]
        session_dir = args[args.index("--session-dir") + 1]
        sleep_s = float(os.environ.get("FAKE_PI_SLEEP", "0"))
        if sleep_s:
            time.sleep(sleep_s)
        os.makedirs(session_dir, exist_ok=True)
        path = os.path.join(session_dir, f"session-{os.getpid()}.jsonl")
        with open(path, "w") as f:
            f.write(json.dumps({"type": "session", "id": f"s-{os.getpid()}"}) + "\\n")
            f.write(json.dumps({
                "type": "message", "id": "m1", "timestamp": "2026-10-15T00:00:00Z",
                "message": {"role": "assistant", "provider": "deepseek", "model": "deepseek-flash",
                             "responseId": f"r-{os.getpid()}", "timestamp": "2026-10-15T00:00:00Z",
                             "usage": {"input": 100, "output": 50, "cost": {"total": 0.001}},
                             "content": []}
            }) + "\\n")
        sys.exit(int(os.environ.get("FAKE_PI_EXIT_CODE", "0")))
    """), encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    return script


@pytest.fixture
def fake_pi_resumable(tmp_path, monkeypatch):
    """A fake `pi` that supports BOTH `--session-dir` (writes a brand-new file, like `fake_pi`) and
    `--session <path>` (APPENDS one more assistant usage record to that EXISTING file) -- the real
    `pi`'s actual behavior when resuming (confirmed live, 2026-10-24): a resumed session's file grows,
    it is never replaced. `fake_pi` alone can't exercise resume_pi_headless's real cost-diff path
    (record count before/after in one file), because it only ever writes brand-new files."""
    script = tmp_path / "pi"
    script.write_text(textwrap.dedent("""\
        #!/usr/bin/env python3
        import json, os, sys, time
        args = sys.argv[1:]
        record = {
            "type": "message", "id": f"m-{os.getpid()}-{time.time_ns()}", "timestamp": "2026-10-24T00:00:00Z",
            "message": {"role": "assistant", "provider": "deepseek", "model": "deepseek-flash",
                         "responseId": f"r-{os.getpid()}-{time.time_ns()}", "timestamp": "2026-10-24T00:00:00Z",
                         "usage": {"input": 20, "output": 10, "cost": {"total": 0.0005}}, "content": []},
        }
        if "--session" in args:
            path = args[args.index("--session") + 1]
            with open(path, "a") as f:
                f.write(json.dumps(record) + "\\n")
        else:
            session_dir = args[args.index("--session-dir") + 1]
            os.makedirs(session_dir, exist_ok=True)
            path = os.path.join(session_dir, f"session-{os.getpid()}.jsonl")
            with open(path, "w") as f:
                f.write(json.dumps({"type": "session", "id": f"s-{os.getpid()}"}) + "\\n")
                f.write(json.dumps(record) + "\\n")
        sys.exit(int(os.environ.get("FAKE_PI_EXIT_CODE", "0")))
    """), encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    return script


@pytest.fixture
def fake_screen(tmp_path, monkeypatch):
    """A fake `screen` on PATH that supports exactly the four sub-commands
    `pi_wave_kit.interactive` uses: `-dmS <name> <cmd...>` (spawns `cmd` detached, tracked by a pidfile
    under a state dir), `-ls` (lists still-alive tracked sessions in screen's own
    `\tPID.NAME\t(date)\t(Detached)` format), `-S <name> -X hardcopy <path>` (writes a canned marker,
    alive or dead), and `-S <name> -X quit` (kills the tracked pid). Good enough to exercise
    interactive.py's real argv-building and parsing without needing the real `screen` binary (not
    guaranteed present in CI)."""
    state_dir = tmp_path / "fake-screen-state"
    state_dir.mkdir()
    script = tmp_path / "screen"
    script.write_text(textwrap.dedent(f"""\
        #!/usr/bin/env python3
        import os, subprocess, sys, time
        STATE = {str(state_dir)!r}
        args = sys.argv[1:]

        def pidfile(name):
            return os.path.join(STATE, name + ".pid")

        if "-dmS" in args:
            i = args.index("-dmS")
            name = args[i + 1]
            cmd = args[i + 2:]
            proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL)
            with open(pidfile(name), "w") as f:
                f.write(str(proc.pid))
        elif "-ls" in args:
            for fn in os.listdir(STATE):
                if not fn.endswith(".pid"):
                    continue
                name = fn[:-4]
                pid = int(open(pidfile(name)).read())
                try:
                    os.kill(pid, 0)
                    print(f"\\t{{pid}}.{{name}}\\t(10/25/2026 00:00:00 AM)\\t(Detached)")
                except ProcessLookupError:
                    os.remove(pidfile(name))
        elif "-X" in args:
            si = args.index("-S")
            name = args[si + 1]
            xi = args.index("-X")
            action = args[xi + 1]
            if action == "hardcopy":
                out_path = args[xi + 2]
                alive = os.path.exists(pidfile(name))
                with open(out_path, "w") as f:
                    f.write(f"fake hardcopy for {{name}}, alive={{alive}}\\n")
            elif action == "quit":
                if os.path.exists(pidfile(name)):
                    pid = int(open(pidfile(name)).read())
                    try:
                        os.kill(pid, 9)
                    except ProcessLookupError:
                        pass
                    os.remove(pidfile(name))
    """), encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    return script


@pytest.fixture
def fake_systemd_run(tmp_path, monkeypatch):
    """A fake `systemd-run` on PATH that just execs everything after its own flags/`--`, the same
    way the real `systemd-run --user --scope` execs its target command in place. Lets
    CgroupLimits-wrapped commands be tested without a real systemd user session (not guaranteed
    available in CI/sandboxes) while still exercising the real argv-prefixing path end to end."""
    script = tmp_path / "systemd-run"
    script.write_text(textwrap.dedent("""\
        #!/usr/bin/env python3
        import os, sys
        args = sys.argv[1:]
        i = args.index("--")
        os.execvp(args[i + 1], args[i + 1:])
    """), encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    return script

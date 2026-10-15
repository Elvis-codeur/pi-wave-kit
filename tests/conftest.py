"""A fake `pi` executable on PATH, same technique the project this library was extracted from used
(tests/test_pi_wave.py, agentic-doc-treatement): writes a synthetic session JSONL with a real usage
record, so run_pi.py's cost-reading path is exercised against a real file, not mocked away."""

import json
import os
import stat
import sys
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

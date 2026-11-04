"""pi-wave-session send (issue #15) and type (issue #16): the two ways to reach a running session. A fake
courier `pi` writes pi-messenger's feed line; the fake `screen` records pasted keystrokes. No model call."""

import json
import os
import stat
import textwrap
import time

import pytest

import pi_wave_kit.interactive as interactive
from pi_wave_kit.interactive import SEND_BEGIN, SEND_END, find_delivery, send_prompt
from pi_wave_kit.session_cli import main


@pytest.fixture
def courier_pi(tmp_path, monkeypatch):
    """A fake `pi` courier: records its argv/env/stdin, writes a session file, and -- unless FAKE_COURIER_FAIL
    is set -- appends the feed line pi-messenger would write for a DM from $PI_AGENT_NAME to the named peer."""
    script = tmp_path / "cbin" / "pi"
    script.parent.mkdir()
    script.write_text(textwrap.dedent("""\
        #!/usr/bin/env python3
        import json, os, re, sys, time
        args = sys.argv[1:]
        prompt = args[-1]
        json.dump({"args": args, "agent": os.environ.get("PI_AGENT_NAME"), "stdin_closed": sys.stdin.read() == ""},
                  open(os.path.join(os.environ["COURIER_RECORD_DIR"], "call.json"), "w"))
        d = args[args.index("--session-dir") + 1]
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "s.jsonl"), "w") as f:
            f.write(json.dumps({"type": "message", "id": "m", "timestamp": "2026-11-04T00:00:00Z",
                "message": {"role": "assistant", "provider": "deepseek", "model": "deepseek-flash", "responseId": "r",
                            "timestamp": "2026-11-04T00:00:00Z", "usage": {"input": 1, "output": 1, "cost": {"total": 0.0004}},
                            "content": []}}) + "\\n")
        if not os.environ.get("FAKE_COURIER_FAIL"):
            to = re.search(r"peer named exactly (\\S+)\\.", prompt).group(1)
            feed = os.path.join(os.getcwd(), ".pi", "messenger", "feed.jsonl")
            os.makedirs(os.path.dirname(feed), exist_ok=True)
            with open(feed, "a") as f:
                f.write(json.dumps({"ts": "2026-11-04T10:00:00Z", "type": "message", "agent": os.environ["PI_AGENT_NAME"],
                                    "target": to, "preview": "..."}) + "\\n")
        print("SENT")
    """), encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    record_dir = tmp_path / "courier-record"
    record_dir.mkdir()
    monkeypatch.setenv("COURIER_RECORD_DIR", str(record_dir))
    monkeypatch.setenv("PATH", str(script.parent) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("HOME", str(tmp_path / "home"))  # keep the global-feed candidate out of the real ~
    monkeypatch.delenv("PI_MESSENGER_DIR", raising=False)
    return record_dir


def test_send_prompt_quotes_the_payload_verbatim_between_markers():
    text = "Line one: keep *this*.\n  Line two -- with \"quotes\" and $VARS."
    prompt = send_prompt("Review7", text)
    assert f"{SEND_BEGIN}\n{text}\n{SEND_END}" in prompt
    assert "peer named exactly Review7." in prompt and "EXACTLY" in prompt


def test_send_is_confirmed_from_the_feed_not_the_couriers_reply(courier_pi, tmp_path, capsys):
    proj = tmp_path / "proj"
    feed = proj / ".pi" / "messenger" / "feed.jsonl"
    feed.parent.mkdir(parents=True)
    # An OLD delivery to the same peer must not count as this one.
    feed.write_text(json.dumps({"type": "message", "agent": "Dispatcher", "target": "Home"}) + "\n", encoding="utf-8")
    rc = main(["send", "Home", "Correction: use the 2nd edition.", "--workdir", str(proj),
               "--jobs-dir", str(tmp_path / "jobs")])
    assert rc == 0
    assert "delivered to Home" in capsys.readouterr().out
    call = json.loads((courier_pi / "call.json").read_text(encoding="utf-8"))
    assert call["agent"] == "Dispatcher" and call["stdin_closed"]
    assert "Correction: use the 2nd edition." in call["args"][-1]
    assert call["args"][call["args"].index("--model") + 1] == "deepseek-flash"
    assert str(tmp_path / "jobs" / "Dispatcher" / "sessions") in call["args"]


def test_send_exits_nonzero_when_no_feed_line_appears(courier_pi, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("FAKE_COURIER_FAIL", "1")
    proj = tmp_path / "proj"
    proj.mkdir()
    rc = main(["send", "Home", "hello", "--from", "Ops", "--workdir", str(proj), "--jobs-dir", str(tmp_path / "jobs")])
    assert rc == 1
    assert "NOT confirmed" in capsys.readouterr().err


def test_send_reads_text_from_a_file_and_rejects_empty_text(courier_pi, tmp_path, capsys):
    proj = tmp_path / "proj"
    proj.mkdir()
    f = tmp_path / "msg.txt"
    f.write_text("   \n", encoding="utf-8")
    assert main(["send", "Home", "--text-file", str(f), "--workdir", str(proj)]) == 2
    f.write_text("from a file", encoding="utf-8")
    assert main(["send", "Home", "--text-file", str(f), "--workdir", str(proj), "--jobs-dir", str(tmp_path / "j")]) == 0
    assert "from a file" in json.loads((courier_pi / "call.json").read_text(encoding="utf-8"))["args"][-1]


def test_find_delivery_matches_sender_and_target_only_after_the_offset(tmp_path):
    feed = tmp_path / "feed.jsonl"
    old = json.dumps({"type": "message", "agent": "A", "target": "B"}) + "\n"
    feed.write_text(old, encoding="utf-8")
    offsets = {feed: feed.stat().st_size}
    assert find_delivery(offsets, to="B", sender="A") is None
    with open(feed, "a", encoding="utf-8") as f:
        f.write(json.dumps({"type": "join", "agent": "A"}) + "\n")
        f.write(json.dumps({"type": "message", "agent": "Z", "target": "B"}) + "\n")
        f.write("not json\n")
        f.write(json.dumps({"type": "message", "agent": "A", "target": "B", "ts": "t1"}) + "\n")
    assert find_delivery(offsets, to="B", sender="A")["ts"] == "t1"


def _launch(fake_screen_state_parent, tmp_path, name="alpha"):
    workdir = tmp_path / "work"
    workdir.mkdir(exist_ok=True)
    assert main(["launch", name, "x", str(workdir), "--prompt", "stand by", "--jobs-dir", str(tmp_path / "jobs"),
                 "--no-watch"]) == 0
    time.sleep(0.2)


def test_type_pastes_the_text_verbatim_plus_enter_and_logs_it(fake_pi, fake_screen, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("FAKE_PI_SLEEP", "30")
    _launch(fake_screen, tmp_path)
    text = 'a^Mb \\n "$HOME" ^C'  # characters `screen -X stuff` would interpret
    rc = main(["type", "alpha", text, "--jobs-dir", str(tmp_path / "jobs")])
    assert rc == 0
    typed = (tmp_path / "fake-screen-state" / "alpha.typed").read_bytes()
    assert typed == text.encode() + b"\r"
    log = [json.loads(line) for line in (tmp_path / "jobs" / "alpha" / "inject.jsonl").read_text(encoding="utf-8").splitlines()]
    assert log[0]["type"] == "inject" and log[0]["text"] == text and log[0]["via"] == "screen"
    assert not list((tmp_path / "jobs" / "alpha").glob("*payload*"))  # scratch file removed
    main(["stop", "alpha"])


def test_type_no_enter_and_if_idle(fake_pi, fake_screen, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_PI_SLEEP", "30")
    _launch(fake_screen, tmp_path)
    assert main(["type", "alpha", "draft", "--no-enter", "--if-idle", "--idle-seconds", "0.05",
                 "--jobs-dir", str(tmp_path / "jobs")]) == 0
    assert (tmp_path / "fake-screen-state" / "alpha.typed").read_bytes() == b"draft"

    frames = iter(["generating...", "generating... more"])
    monkeypatch.setattr(interactive, "_snapshot", lambda name, mux, scratch: next(frames))
    assert main(["type", "alpha", "x", "--if-idle", "--idle-seconds", "0", "--jobs-dir", str(tmp_path / "jobs")]) == 3
    assert (tmp_path / "fake-screen-state" / "alpha.typed").read_bytes() == b"draft"  # nothing more typed
    main(["stop", "alpha"])


def test_type_into_a_session_that_does_not_exist(fake_screen, tmp_path, monkeypatch, capsys):
    rc = main(["type", "ghost", "hi", "--jobs-dir", str(tmp_path / "jobs")])
    assert rc == 1 and "no running screen or tmux session" in capsys.readouterr().err


def test_help_shows_the_three_ways_to_reach_a_session(capsys):
    with pytest.raises(SystemExit):
        main(["--help"])
    out = capsys.readouterr().out
    for needle in ("send", "type", "hardcopy", "next tool boundary", "keystrokes", "examples:"):
        assert needle in out
    with pytest.raises(SystemExit):
        main(["launch", "--help"])
    assert "pi-wave-session send" in capsys.readouterr().out

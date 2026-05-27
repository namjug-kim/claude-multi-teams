import json
import threading
import time
from pathlib import Path

import pytest

from cmt.strategies import await_jsonl_done


def _append(path: Path, event: dict) -> None:
    with open(path, "a") as f:
        f.write(json.dumps(event) + "\n")


def test_returns_done_when_terminal_stop_reason_already_present(tmp_path: Path) -> None:
    p = tmp_path / "session.jsonl"
    _append(p, {"type": "user", "message": {"role": "user", "content": "x"}})
    _append(p, {"type": "assistant", "message": {
        "role": "assistant",
        "content": [{"type": "text", "text": "ok"}],
        "stop_reason": "end_turn",
    }})
    result = await_jsonl_done(p, baseline_offset=0, is_alive=lambda: True, poll_interval=0.05)
    assert result == "done"


def test_polls_growing_file(tmp_path: Path) -> None:
    p = tmp_path / "session.jsonl"
    # Start with empty file (allowed — strategy must tolerate FileNotFoundError too)
    p.touch()

    def writer():
        time.sleep(0.15)
        _append(p, {"type": "user", "message": {"role": "user", "content": "x"}})
        time.sleep(0.15)
        _append(p, {"type": "assistant", "message": {
            "role": "assistant",
            "content": [{"type": "text", "text": "ok"}],
            "stop_reason": "end_turn",
        }})

    t = threading.Thread(target=writer)
    t.start()
    result = await_jsonl_done(p, baseline_offset=0, is_alive=lambda: True, poll_interval=0.05)
    t.join()
    assert result == "done"


def test_returns_dead_when_is_alive_false(tmp_path: Path) -> None:
    p = tmp_path / "session.jsonl"
    p.touch()
    calls = {"n": 0}

    def alive():
        calls["n"] += 1
        return calls["n"] < 3  # dies after a couple of polls

    result = await_jsonl_done(p, baseline_offset=0, is_alive=alive, poll_interval=0.05)
    assert result == "dead"


def test_waits_through_tool_use_until_final_end_turn(tmp_path: Path) -> None:
    p = tmp_path / "session.jsonl"
    _append(p, {"type": "user", "message": {"role": "user", "content": "ls"}})
    # tool_use is NOT a terminal stop_reason — strategy must keep waiting
    _append(p, {"type": "assistant", "message": {
        "role": "assistant",
        "content": [{"type": "tool_use", "id": "x", "name": "Bash", "input": {}}],
        "stop_reason": "tool_use",
    }})

    def writer():
        time.sleep(0.15)
        _append(p, {"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "x", "content": "f1\nf2"},
        ]}})
        _append(p, {"type": "assistant", "message": {
            "role": "assistant",
            "content": [{"type": "text", "text": "done"}],
            "stop_reason": "end_turn",
        }})

    t = threading.Thread(target=writer)
    t.start()
    result = await_jsonl_done(p, baseline_offset=0, is_alive=lambda: True, poll_interval=0.05)
    t.join()
    assert result == "done"


def test_baseline_offset_ignores_earlier_terminal(tmp_path: Path) -> None:
    p = tmp_path / "session.jsonl"
    _append(p, {"type": "user", "message": {"role": "user", "content": "earlier"}})
    _append(p, {"type": "assistant", "message": {
        "role": "assistant",
        "content": [{"type": "text", "text": "earlier-reply"}],
        "stop_reason": "end_turn",
    }})
    offset = p.stat().st_size

    def writer():
        time.sleep(0.15)
        _append(p, {"type": "user", "message": {"role": "user", "content": "now"}})
        _append(p, {"type": "assistant", "message": {
            "role": "assistant",
            "content": [{"type": "text", "text": "now-reply"}],
            "stop_reason": "end_turn",
        }})

    t = threading.Thread(target=writer)
    t.start()
    result = await_jsonl_done(p, baseline_offset=offset, is_alive=lambda: True, poll_interval=0.05)
    t.join()
    assert result == "done"


def test_tolerates_missing_file_initially(tmp_path: Path) -> None:
    p = tmp_path / "session.jsonl"
    # do NOT touch — file not created at all yet

    def writer():
        time.sleep(0.15)
        _append(p, {"type": "user", "message": {"role": "user", "content": "x"}})
        _append(p, {"type": "assistant", "message": {
            "role": "assistant",
            "content": [{"type": "text", "text": "ok"}],
            "stop_reason": "end_turn",
        }})

    t = threading.Thread(target=writer)
    t.start()
    result = await_jsonl_done(p, baseline_offset=0, is_alive=lambda: True, poll_interval=0.05)
    t.join()
    assert result == "done"


def test_tolerates_malformed_lines(tmp_path: Path) -> None:
    p = tmp_path / "session.jsonl"
    with open(p, "w") as f:
        f.write("garbage\n")
        f.write(json.dumps({"type": "user", "message": {"role": "user", "content": "x"}}) + "\n")
        f.write("{partial\n")
        f.write(json.dumps({"type": "assistant", "message": {
            "role": "assistant",
            "content": [{"type": "text", "text": "ok"}],
            "stop_reason": "end_turn",
        }}) + "\n")
    result = await_jsonl_done(p, baseline_offset=0, is_alive=lambda: True, poll_interval=0.05)
    assert result == "done"

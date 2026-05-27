"""codex-specific strategies: done-detection + status from rollout jsonl.

Codex event shape (verified from real rollout 2026-05-27):
- {"type":"event_msg","payload":{"type":"task_started", ...}}
- {"type":"event_msg","payload":{"type":"user_message", "message":"..."}}
- {"type":"event_msg","payload":{"type":"agent_message","message":"..."}}
- {"type":"event_msg","payload":{"type":"task_complete","last_agent_message":"..."}}

task_complete is the terminal marker — analogous to claude's stop_reason==end_turn.
"""

import json
import threading
import time
from pathlib import Path

from cmt.strategies import await_codex_done, status_codex


def _append(path: Path, event: dict) -> None:
    with open(path, "a") as f:
        f.write(json.dumps(event) + "\n")


def _evt(payload_type: str, **extra) -> dict:
    return {"type": "event_msg", "payload": {"type": payload_type, **extra}}


def test_await_returns_done_when_task_complete_already_present(tmp_path: Path) -> None:
    p = tmp_path / "rollout.jsonl"
    _append(p, _evt("task_started"))
    _append(p, _evt("user_message", message="x"))
    _append(p, _evt("agent_message", message="ok"))
    _append(p, _evt("task_complete", last_agent_message="ok"))
    assert await_codex_done(p, baseline_offset=0, is_alive=lambda: True, poll_interval=0.05) == "done"


def test_await_polls_growing_file(tmp_path: Path) -> None:
    p = tmp_path / "rollout.jsonl"
    p.touch()

    def writer():
        time.sleep(0.15)
        _append(p, _evt("task_started"))
        _append(p, _evt("agent_message", message="hi"))
        time.sleep(0.1)
        _append(p, _evt("task_complete", last_agent_message="hi"))

    t = threading.Thread(target=writer)
    t.start()
    result = await_codex_done(p, baseline_offset=0, is_alive=lambda: True, poll_interval=0.05)
    t.join()
    assert result == "done"


def test_await_tolerates_missing_file(tmp_path: Path) -> None:
    p = tmp_path / "rollout.jsonl"

    def writer():
        time.sleep(0.15)
        _append(p, _evt("task_started"))
        _append(p, _evt("task_complete", last_agent_message="ok"))

    t = threading.Thread(target=writer)
    t.start()
    result = await_codex_done(p, baseline_offset=0, is_alive=lambda: True, poll_interval=0.05)
    t.join()
    assert result == "done"


def test_await_dead_when_pane_dies(tmp_path: Path) -> None:
    p = tmp_path / "rollout.jsonl"
    p.touch()
    n = {"i": 0}

    def alive():
        n["i"] += 1
        return n["i"] < 3

    result = await_codex_done(p, baseline_offset=0, is_alive=alive, poll_interval=0.05)
    assert result == "dead"


def test_await_baseline_offset_ignores_earlier_complete(tmp_path: Path) -> None:
    p = tmp_path / "rollout.jsonl"
    _append(p, _evt("task_started"))
    _append(p, _evt("task_complete", last_agent_message="earlier"))
    offset = p.stat().st_size

    def writer():
        time.sleep(0.15)
        _append(p, _evt("task_started"))
        _append(p, _evt("task_complete", last_agent_message="now"))

    t = threading.Thread(target=writer)
    t.start()
    result = await_codex_done(p, baseline_offset=offset, is_alive=lambda: True, poll_interval=0.05)
    t.join()
    assert result == "done"


def test_status_dead_when_pane_gone(tmp_path: Path) -> None:
    p = tmp_path / "rollout.jsonl"
    assert status_codex(p, baseline_offset=0, pane_alive=False) == "dead"


def test_status_done_when_file_missing(tmp_path: Path) -> None:
    p = tmp_path / "rollout.jsonl"
    assert status_codex(p, baseline_offset=0, pane_alive=True) == "done"


def test_status_done_when_no_new_bytes(tmp_path: Path) -> None:
    p = tmp_path / "rollout.jsonl"
    _append(p, _evt("task_started"))
    _append(p, _evt("task_complete", last_agent_message="ok"))
    offset = p.stat().st_size
    assert status_codex(p, baseline_offset=offset, pane_alive=True) == "done"


def test_status_working_when_started_but_not_complete(tmp_path: Path) -> None:
    p = tmp_path / "rollout.jsonl"
    _append(p, _evt("task_started"))
    _append(p, _evt("agent_message", message="thinking"))
    assert status_codex(p, baseline_offset=0, pane_alive=True) == "working"


def test_status_done_after_task_complete(tmp_path: Path) -> None:
    p = tmp_path / "rollout.jsonl"
    _append(p, _evt("task_started"))
    _append(p, _evt("agent_message", message="ok"))
    _append(p, _evt("task_complete", last_agent_message="ok"))
    assert status_codex(p, baseline_offset=0, pane_alive=True) == "done"

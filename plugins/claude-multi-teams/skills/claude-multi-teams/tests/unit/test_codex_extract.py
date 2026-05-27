"""codex response extraction from rollout jsonl.

Codex emits agent_message events for each assistant turn; the final text is
also duplicated into task_complete.last_agent_message. We concatenate the
agent_message texts after baseline_offset — same shape as the claude extractor
walking text blocks.
"""

import json
from pathlib import Path

from cmt.extract import extract_codex_response


def _write(path: Path, events: list[dict]) -> int:
    with open(path, "w") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")
    return path.stat().st_size


def _evt(payload_type: str, **extra) -> dict:
    return {"type": "event_msg", "payload": {"type": payload_type, **extra}}


def test_extracts_single_agent_message(tmp_path: Path) -> None:
    p = tmp_path / "rollout.jsonl"
    _write(p, [
        _evt("task_started"),
        _evt("user_message", message="ping"),
        _evt("agent_message", message="pong"),
        _evt("task_complete", last_agent_message="pong"),
    ])
    assert extract_codex_response(p, baseline_offset=0) == "pong"


def test_concatenates_multiple_agent_messages(tmp_path: Path) -> None:
    p = tmp_path / "rollout.jsonl"
    _write(p, [
        _evt("task_started"),
        _evt("agent_message", message="First. "),
        _evt("agent_message", message="Second."),
        _evt("task_complete", last_agent_message="Second."),
    ])
    assert extract_codex_response(p, baseline_offset=0) == "First. Second."


def test_ignores_non_event_msg_types(tmp_path: Path) -> None:
    p = tmp_path / "rollout.jsonl"
    _write(p, [
        {"type": "session_meta", "payload": {"id": "x"}},
        {"type": "turn_context", "payload": {}},
        {"type": "response_item", "payload": {"role": "assistant", "content": "noise"}},
        _evt("agent_message", message="real"),
        _evt("task_complete", last_agent_message="real"),
    ])
    assert extract_codex_response(p, baseline_offset=0) == "real"


def test_baseline_offset_skips_earlier(tmp_path: Path) -> None:
    p = tmp_path / "rollout.jsonl"
    offset = _write(p, [
        _evt("task_started"),
        _evt("agent_message", message="earlier"),
        _evt("task_complete", last_agent_message="earlier"),
    ])
    with open(p, "a") as f:
        f.write(json.dumps(_evt("task_started")) + "\n")
        f.write(json.dumps(_evt("agent_message", message="now")) + "\n")
        f.write(json.dumps(_evt("task_complete", last_agent_message="now")) + "\n")
    assert extract_codex_response(p, baseline_offset=offset) == "now"


def test_returns_empty_when_no_agent_message(tmp_path: Path) -> None:
    p = tmp_path / "rollout.jsonl"
    _write(p, [
        _evt("task_started"),
        _evt("user_message", message="ping"),
    ])
    assert extract_codex_response(p, baseline_offset=0) == ""


def test_skips_malformed_lines(tmp_path: Path) -> None:
    p = tmp_path / "rollout.jsonl"
    with open(p, "w") as f:
        f.write("garbage\n")
        f.write(json.dumps(_evt("user_message", message="x")) + "\n")
        f.write("{partial\n")
        f.write(json.dumps(_evt("agent_message", message="ok")) + "\n")
        f.write(json.dumps(_evt("task_complete", last_agent_message="ok")) + "\n")
    assert extract_codex_response(p, baseline_offset=0) == "ok"


def test_strips_trailing_whitespace(tmp_path: Path) -> None:
    p = tmp_path / "rollout.jsonl"
    _write(p, [
        _evt("agent_message", message="  hi  \n\n"),
        _evt("task_complete", last_agent_message="hi"),
    ])
    assert extract_codex_response(p, baseline_offset=0) == "hi"

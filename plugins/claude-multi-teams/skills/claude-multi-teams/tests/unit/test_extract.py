import json
from pathlib import Path

from cmt.extract import extract_jsonl_assistant


def _write_jsonl(path: Path, events: list[dict]) -> int:
    """Write events to path; return offset at end of file."""
    with open(path, "w") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")
    return path.stat().st_size


def test_extracts_single_text_block(tmp_path: Path) -> None:
    p = tmp_path / "session.jsonl"
    _write_jsonl(p, [
        {"type": "user", "message": {"role": "user", "content": "ping"}},
        {"type": "assistant", "message": {
            "role": "assistant",
            "content": [{"type": "text", "text": "pong"}],
            "stop_reason": "end_turn",
        }},
    ])
    assert extract_jsonl_assistant(p, baseline_offset=0) == "pong"


def test_concatenates_multiple_text_blocks(tmp_path: Path) -> None:
    p = tmp_path / "session.jsonl"
    _write_jsonl(p, [
        {"type": "user", "message": {"role": "user", "content": "x"}},
        {"type": "assistant", "message": {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "First part. "},
                {"type": "text", "text": "Second part."},
            ],
            "stop_reason": "end_turn",
        }},
    ])
    assert extract_jsonl_assistant(p, baseline_offset=0) == "First part. Second part."


def test_skips_tool_use_blocks_concatenates_text_across_messages(tmp_path: Path) -> None:
    p = tmp_path / "session.jsonl"
    _write_jsonl(p, [
        {"type": "user", "message": {"role": "user", "content": "ls"}},
        {"type": "assistant", "message": {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "Let me check. "},
                {"type": "tool_use", "id": "x", "name": "Bash", "input": {"cmd": "ls"}},
            ],
        }},
        {"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "x", "content": "file1\nfile2"},
        ]}},
        {"type": "assistant", "message": {
            "role": "assistant",
            "content": [{"type": "text", "text": "Found 2 files."}],
            "stop_reason": "end_turn",
        }},
    ])
    assert extract_jsonl_assistant(p, baseline_offset=0) == "Let me check. Found 2 files."


def test_baseline_offset_skips_earlier_turns(tmp_path: Path) -> None:
    p = tmp_path / "session.jsonl"
    offset_after_turn1 = _write_jsonl(p, [
        {"type": "user", "message": {"role": "user", "content": "first"}},
        {"type": "assistant", "message": {
            "role": "assistant",
            "content": [{"type": "text", "text": "first reply"}],
            "stop_reason": "end_turn",
        }},
    ])
    # Append a second turn
    with open(p, "a") as f:
        f.write(json.dumps({"type": "user", "message": {"role": "user", "content": "second"}}) + "\n")
        f.write(json.dumps({"type": "assistant", "message": {
            "role": "assistant",
            "content": [{"type": "text", "text": "second reply"}],
            "stop_reason": "end_turn",
        }}) + "\n")
    assert extract_jsonl_assistant(p, baseline_offset=offset_after_turn1) == "second reply"


def test_skips_malformed_lines(tmp_path: Path) -> None:
    p = tmp_path / "session.jsonl"
    with open(p, "w") as f:
        f.write("not valid json\n")
        f.write(json.dumps({"type": "user", "message": {"role": "user", "content": "x"}}) + "\n")
        f.write("\n")  # blank line
        f.write(json.dumps({"type": "assistant", "message": {
            "role": "assistant",
            "content": [{"type": "text", "text": "ok"}],
            "stop_reason": "end_turn",
        }}) + "\n")
        f.write("{partial json\n")
    assert extract_jsonl_assistant(p, baseline_offset=0) == "ok"


def test_returns_empty_when_no_assistant_yet(tmp_path: Path) -> None:
    p = tmp_path / "session.jsonl"
    _write_jsonl(p, [
        {"type": "user", "message": {"role": "user", "content": "ping"}},
    ])
    assert extract_jsonl_assistant(p, baseline_offset=0) == ""


def test_strips_trailing_whitespace(tmp_path: Path) -> None:
    p = tmp_path / "session.jsonl"
    _write_jsonl(p, [
        {"type": "user", "message": {"role": "user", "content": "x"}},
        {"type": "assistant", "message": {
            "role": "assistant",
            "content": [{"type": "text", "text": "  reply  \n\n"}],
            "stop_reason": "end_turn",
        }},
    ])
    assert extract_jsonl_assistant(p, baseline_offset=0) == "reply"

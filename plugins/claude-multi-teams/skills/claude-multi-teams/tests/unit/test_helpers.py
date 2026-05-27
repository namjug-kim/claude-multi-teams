import json
from pathlib import Path

from cmt import state, strategies
from cmt.state import AgentState


def _sample(name="alice", agent_id="abc-id") -> AgentState:
    return AgentState(
        name=name, agent="claude", agent_id=agent_id,
        pane_id="%23", cwd="/tmp", started_at="t",
        session_file="/tmp/none.jsonl", baseline_offset=0,
    )


def test_find_by_agent_id(tmp_path: Path) -> None:
    state.save(_sample("alice", "id-1"), state_dir=tmp_path)
    state.save(_sample("bob",   "id-2"), state_dir=tmp_path)
    assert state.find_by_agent_id("id-2", state_dir=tmp_path).name == "bob"
    assert state.find_by_agent_id("nope", state_dir=tmp_path) is None


def _append(path: Path, events: list[dict]) -> None:
    with open(path, "a") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")


def test_status_jsonl_done_when_no_new_activity(tmp_path: Path) -> None:
    p = tmp_path / "session.jsonl"
    _append(p, [
        {"type": "user", "message": {"role": "user", "content": "x"}},
        {"type": "assistant", "message": {
            "role": "assistant",
            "content": [{"type": "text", "text": "ok"}],
            "stop_reason": "end_turn",
        }},
    ])
    # baseline at start of (only) turn — strategy sees terminal stop_reason → done
    assert strategies.status_jsonl(p, baseline_offset=0, pane_alive=True) == "done"


def test_status_jsonl_working_when_user_no_assistant(tmp_path: Path) -> None:
    p = tmp_path / "session.jsonl"
    _append(p, [
        {"type": "user", "message": {"role": "user", "content": "thinking"}},
    ])
    assert strategies.status_jsonl(p, baseline_offset=0, pane_alive=True) == "working"


def test_status_jsonl_working_when_mid_tool_use(tmp_path: Path) -> None:
    p = tmp_path / "session.jsonl"
    _append(p, [
        {"type": "user", "message": {"role": "user", "content": "x"}},
        {"type": "assistant", "message": {
            "role": "assistant",
            "content": [{"type": "tool_use", "id": "1", "name": "B", "input": {}}],
            "stop_reason": "tool_use",
        }},
    ])
    assert strategies.status_jsonl(p, baseline_offset=0, pane_alive=True) == "working"


def test_status_jsonl_dead_when_pane_dead(tmp_path: Path) -> None:
    p = tmp_path / "session.jsonl"
    p.touch()
    assert strategies.status_jsonl(p, baseline_offset=0, pane_alive=False) == "dead"


def test_status_jsonl_done_when_idle_baseline_at_eof(tmp_path: Path) -> None:
    # File exists but nothing new since baseline — agent is idle, waiting for next prompt
    p = tmp_path / "session.jsonl"
    _append(p, [
        {"type": "user", "message": {"role": "user", "content": "x"}},
        {"type": "assistant", "message": {
            "role": "assistant",
            "content": [{"type": "text", "text": "ok"}],
            "stop_reason": "end_turn",
        }},
    ])
    eof = p.stat().st_size
    assert strategies.status_jsonl(p, baseline_offset=eof, pane_alive=True) == "done"


def test_status_jsonl_done_when_file_missing(tmp_path: Path) -> None:
    # claude hasn't written jsonl yet (no first prompt sent) — treat as idle done
    p = tmp_path / "never.jsonl"
    assert strategies.status_jsonl(p, baseline_offset=0, pane_alive=True) == "done"

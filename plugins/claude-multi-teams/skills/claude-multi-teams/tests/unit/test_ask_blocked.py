"""ask() surfaces an input-blocked turn as BlockedOnInput instead of hanging."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from cmt import agents, state
from cmt.ops import ask as ask_op


def _agent(session_file: str) -> state.AgentState:
    return state.AgentState(
        name="alice", agent="claude", agent_id="id", pane_id="%1",
        cwd="/tmp", started_at="2026-05-28T00:00:00Z",
        session_file=session_file, baseline_offset=0,
    )


def test_ask_raises_blocked_on_input_with_question(tmp_path: Path, monkeypatch) -> None:
    sd = tmp_path / "state"
    sess = tmp_path / "s.jsonl"
    sess.write_text("")
    state.save(_agent(str(sess)), state_dir=sd)

    question = {"questions": [{"header": "h", "question": "Which?"}]}
    patched = dataclasses.replace(
        agents.AGENTS["claude"],
        pre_send=None,
        await_done=lambda st, alive: "blocked",
        extract_response=lambda st: "partial review text",
    )
    monkeypatch.setitem(agents.AGENTS, "claude", patched)
    monkeypatch.setattr(ask_op, "_ensure_started", lambda *a, **k: None)
    monkeypatch.setattr(ask_op.mux, "pane_alive", lambda p: True)
    monkeypatch.setattr(ask_op.mux, "send_text", lambda *a, **k: None)
    monkeypatch.setattr(ask_op.strategies, "pending_question", lambda p, b: question)

    with pytest.raises(ask_op.BlockedOnInput) as ei:
        ask_op.ask("alice", "review this", state_dir=sd)

    assert ei.value.question == question
    assert ei.value.text == "partial review text"
    assert ei.value.name == "alice"
    # in-flight call marker is released even though ask raised
    assert not (sd / ".calls" / "alice.json").exists()

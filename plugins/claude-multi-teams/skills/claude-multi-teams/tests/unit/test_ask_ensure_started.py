"""Tests for the dropped-Enter guard in cmt.ops.ask.

A bracketed paste + immediate Enter can race under load; the Enter is
swallowed and the prompt sits unsent. _ensure_started detects the stall
and re-presses Enter rather than blocking forever in await_done.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from cmt import state
from cmt.ops import ask as ask_op


def _agent(session_file: str | None, baseline: int) -> state.AgentState:
    return state.AgentState(
        name="alice", agent="claude", agent_id="id", pane_id="%1",
        cwd="/tmp", started_at="2026-05-28T00:00:00Z",
        session_file=session_file, baseline_offset=baseline,
    )


def test_turn_started_true_when_jsonl_grew(tmp_path: Path) -> None:
    f = tmp_path / "s.jsonl"
    f.write_text("x" * 100)
    assert ask_op._turn_started(_agent(str(f), 50), "alice", tmp_path) is True


def test_turn_started_false_when_jsonl_not_grown(tmp_path: Path) -> None:
    f = tmp_path / "s.jsonl"
    f.write_text("x" * 100)
    # size == baseline → not strictly greater → not started
    assert ask_op._turn_started(_agent(str(f), 100), "alice", tmp_path) is False


def test_turn_started_false_when_jsonl_missing(tmp_path: Path) -> None:
    assert ask_op._turn_started(_agent(str(tmp_path / "nope.jsonl"), 0), "alice", tmp_path) is False


def test_ensure_started_resends_enter_until_turn_begins(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(ask_op.mux, "pane_alive", lambda p: True)
    # The turn only "starts" once a resend Enter has been delivered — exactly
    # the dropped-Enter scenario. Coupling the two makes the test timing-free.
    state_flag = {"started": False}
    sends: list[tuple] = []

    def fake_send(p, *k):
        sends.append((p, k))
        state_flag["started"] = True

    monkeypatch.setattr(ask_op.mux, "send_keys", fake_send)
    monkeypatch.setattr(ask_op, "_turn_started", lambda *a: state_flag["started"])
    ask_op._ensure_started(_agent("f", 0), "alice", tmp_path,
                           max_resends=3, window=0.2, poll=0.1)
    assert len(sends) == 1  # one resend was enough to start the turn


def test_ensure_started_raises_after_max_resends(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(ask_op.mux, "pane_alive", lambda p: True)
    monkeypatch.setattr(ask_op.mux, "send_keys", lambda p, *k: None)
    monkeypatch.setattr(ask_op, "_turn_started", lambda *a: False)
    with pytest.raises(RuntimeError, match="never started"):
        ask_op._ensure_started(_agent("f", 0), "alice", tmp_path,
                               max_resends=2, window=0.2, poll=0.1)


def test_ensure_started_returns_on_dead_pane(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(ask_op.mux, "pane_alive", lambda p: False)
    monkeypatch.setattr(ask_op, "_turn_started", lambda *a: False)
    # dead pane → return quietly, let await_done surface 'dead'
    ask_op._ensure_started(_agent("f", 0), "alice", tmp_path,
                           max_resends=3, window=0.3, poll=0.1)

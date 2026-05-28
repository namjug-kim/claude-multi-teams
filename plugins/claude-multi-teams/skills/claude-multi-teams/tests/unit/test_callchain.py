"""Tests for cycle prevention + per-target mutex in cmt.callchain."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from cmt import callchain, state


def _make_agent(state_dir: Path, name: str, agent_id: str) -> None:
    """Write a minimal state file so find_by_agent_id can resolve."""
    s = state.AgentState(
        name=name,
        agent="claude",
        agent_id=agent_id,
        pane_id=f"%{name}",
        cwd="/tmp",
        started_at="2026-05-27T00:00:00Z",
    )
    state.save(s, state_dir=state_dir)


def test_acquire_from_orchestrator_writes_single_step_chain(tmp_path: Path) -> None:
    callchain.acquire("alice", state_dir=tmp_path)
    chain_file = tmp_path / ".calls" / "alice.json"
    assert chain_file.exists()
    assert json.loads(chain_file.read_text())["chain"] == ["alice"]


def test_release_clears_in_flight_marker(tmp_path: Path) -> None:
    callchain.acquire("alice", state_dir=tmp_path)
    callchain.release("alice", state_dir=tmp_path)
    assert not (tmp_path / ".calls" / "alice.json").exists()


def test_release_is_idempotent(tmp_path: Path) -> None:
    callchain.release("ghost", state_dir=tmp_path)  # must not raise


def test_acquire_busy_target_raises(tmp_path: Path) -> None:
    callchain.acquire("alice", state_dir=tmp_path)
    with pytest.raises(callchain.TargetBusy):
        callchain.acquire("alice", state_dir=tmp_path)


def test_nested_call_extends_chain(tmp_path: Path, monkeypatch) -> None:
    _make_agent(tmp_path, "alice", "id-alice")
    callchain.acquire("alice", state_dir=tmp_path)
    monkeypatch.setenv("CMT_AGENT_ID", "id-alice")
    callchain.acquire("bob", state_dir=tmp_path)
    bob_chain = json.loads((tmp_path / ".calls" / "bob.json").read_text())["chain"]
    assert bob_chain == ["alice", "bob"]


def test_cycle_detected_direct(tmp_path: Path, monkeypatch) -> None:
    _make_agent(tmp_path, "alice", "id-alice")
    callchain.acquire("alice", state_dir=tmp_path)
    monkeypatch.setenv("CMT_AGENT_ID", "id-alice")
    # alice's pane tries to call alice → self-cycle
    with pytest.raises(callchain.CycleDetected):
        callchain.acquire("alice", state_dir=tmp_path)


def test_cycle_detected_back_edge(tmp_path: Path, monkeypatch) -> None:
    _make_agent(tmp_path, "alice", "id-alice")
    _make_agent(tmp_path, "bob", "id-bob")
    # orchestrator → alice
    callchain.acquire("alice", state_dir=tmp_path)
    # alice → bob (CMT_AGENT_ID=alice)
    monkeypatch.setenv("CMT_AGENT_ID", "id-alice")
    callchain.acquire("bob", state_dir=tmp_path)
    # bob → alice (CMT_AGENT_ID=bob) — would re-enter alice
    monkeypatch.setenv("CMT_AGENT_ID", "id-bob")
    with pytest.raises(callchain.CycleDetected):
        callchain.acquire("alice", state_dir=tmp_path)


def test_depth_exceeded(tmp_path: Path, monkeypatch) -> None:
    # Build a chain that hits max_depth
    names = ["a", "b", "c", "d"]
    for n in names:
        _make_agent(tmp_path, n, f"id-{n}")
    callchain.acquire("a", state_dir=tmp_path, max_depth=3)
    monkeypatch.setenv("CMT_AGENT_ID", "id-a")
    callchain.acquire("b", state_dir=tmp_path, max_depth=3)
    monkeypatch.setenv("CMT_AGENT_ID", "id-b")
    callchain.acquire("c", state_dir=tmp_path, max_depth=3)
    monkeypatch.setenv("CMT_AGENT_ID", "id-c")
    with pytest.raises(callchain.DepthExceeded):
        callchain.acquire("d", state_dir=tmp_path, max_depth=3)


def test_release_then_reacquire_works(tmp_path: Path) -> None:
    callchain.acquire("alice", state_dir=tmp_path)
    callchain.release("alice", state_dir=tmp_path)
    # Should be acquirable again — atomic O_EXCL recreates
    callchain.acquire("alice", state_dir=tmp_path)


def test_stale_marker_from_dead_pid_is_reclaimed(tmp_path: Path) -> None:
    """A .calls marker left by a crashed cmt (dead owner_pid) must not lock
    the target forever — the next acquire reclaims it."""
    calls = tmp_path / ".calls"
    calls.mkdir(parents=True)
    # PID 999999 is overwhelmingly unlikely to be alive
    (calls / "alice.json").write_text(json.dumps({"chain": ["alice"], "owner_pid": 999999}))
    callchain.acquire("alice", state_dir=tmp_path)  # must not raise
    rec = json.loads((calls / "alice.json").read_text())
    assert rec["chain"] == ["alice"]
    assert rec["owner_pid"] == os.getpid()


def test_live_marker_still_blocks(tmp_path: Path) -> None:
    """A marker owned by a live process (our own pid) blocks as TargetBusy."""
    calls = tmp_path / ".calls"
    calls.mkdir(parents=True)
    (calls / "alice.json").write_text(json.dumps({"chain": ["alice"], "owner_pid": os.getpid()}))
    with pytest.raises(callchain.TargetBusy):
        callchain.acquire("alice", state_dir=tmp_path)


def test_acquire_unknown_caller_id_falls_back_to_empty_chain(tmp_path: Path, monkeypatch) -> None:
    """If CMT_AGENT_ID points at a deleted/missing state, treat as
    orchestrator (no chain) rather than crash."""
    monkeypatch.setenv("CMT_AGENT_ID", "id-ghost")
    callchain.acquire("alice", state_dir=tmp_path)
    chain = json.loads((tmp_path / ".calls" / "alice.json").read_text())["chain"]
    assert chain == ["alice"]

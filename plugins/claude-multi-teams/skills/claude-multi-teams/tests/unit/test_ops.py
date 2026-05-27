"""End-to-end ops tests using real tmux + a fake claude binary (PATH-shim).

Covers the compose-paths: spawn → state.save; ask → send_text → strategy →
extract; kill → kill_pane → state.remove. The fake claude reads pasted lines
from stdin and writes claude-shaped jsonl events, so the test exercises the
real bracketed-paste-through-tmux flow without depending on the cloud LLM.
"""

import os
import time
from pathlib import Path

import pytest

from cmt import state
from cmt.ops import spawn as spawn_op
from cmt.ops import ask as ask_op
from cmt.ops import kill as kill_op


def test_spawn_creates_pane_and_state(tmp_path: Path, tmux_server, fake_claude) -> None:
    s = spawn_op.spawn("claude", "alice", cwd=str(tmp_path), state_dir=tmp_path / "state")
    assert s.name == "alice"
    assert s.agent == "claude"
    assert s.pane_id.startswith("%")
    assert s.agent_id  # non-empty
    assert s.session_file is not None
    # state file written
    loaded = state.load("alice", state_dir=tmp_path / "state")
    assert loaded == s


def test_spawn_conflict_without_replace_raises(tmp_path: Path, tmux_server, fake_claude) -> None:
    spawn_op.spawn("claude", "alice", cwd=str(tmp_path), state_dir=tmp_path / "state")
    with pytest.raises(FileExistsError):
        spawn_op.spawn("claude", "alice", cwd=str(tmp_path), state_dir=tmp_path / "state")


def test_spawn_replace_kills_old(tmp_path: Path, tmux_server, fake_claude) -> None:
    s1 = spawn_op.spawn("claude", "alice", cwd=str(tmp_path), state_dir=tmp_path / "state")
    s2 = spawn_op.spawn("claude", "alice", cwd=str(tmp_path), state_dir=tmp_path / "state",
                        replace=True)
    assert s2.pane_id != s1.pane_id


def test_spawn_requires_parent_pane(tmp_path: Path, monkeypatch, fake_claude) -> None:
    monkeypatch.delenv("TMUX_PANE", raising=False)
    monkeypatch.delenv("TMUX", raising=False)
    with pytest.raises(RuntimeError):
        spawn_op.spawn("claude", "alice", cwd=str(tmp_path), state_dir=tmp_path / "state")


def test_ask_returns_assistant_text(tmp_path: Path, tmux_server, fake_claude) -> None:
    spawn_op.spawn("claude", "alice", cwd=str(tmp_path), state_dir=tmp_path / "state")
    # let fake claude start up (it just sits waiting on stdin)
    time.sleep(0.3)
    reply = ask_op.ask("alice", "ping", state_dir=tmp_path / "state")
    assert reply == "echo: ping"


def test_ask_two_turns(tmp_path: Path, tmux_server, fake_claude) -> None:
    spawn_op.spawn("claude", "alice", cwd=str(tmp_path), state_dir=tmp_path / "state")
    time.sleep(0.3)
    r1 = ask_op.ask("alice", "first", state_dir=tmp_path / "state")
    r2 = ask_op.ask("alice", "second", state_dir=tmp_path / "state")
    assert r1 == "echo: first"
    assert r2 == "echo: second"


def test_ask_unknown_name_raises(tmp_path: Path, tmux_server) -> None:
    with pytest.raises(FileNotFoundError):
        ask_op.ask("ghost", "ping", state_dir=tmp_path / "state")


def test_ask_dead_pane_raises(tmp_path: Path, tmux_server, fake_claude) -> None:
    s = spawn_op.spawn("claude", "alice", cwd=str(tmp_path), state_dir=tmp_path / "state")
    # kill the pane out from under ask
    from cmt import mux as mux_mod
    mux_mod.kill_pane(s.pane_id)
    time.sleep(0.2)
    with pytest.raises(RuntimeError):
        ask_op.ask("alice", "ping", state_dir=tmp_path / "state")


def test_kill_removes_state_and_pane(tmp_path: Path, tmux_server, fake_claude) -> None:
    s = spawn_op.spawn("claude", "alice", cwd=str(tmp_path), state_dir=tmp_path / "state")
    from cmt import mux as mux_mod
    assert mux_mod.pane_alive(s.pane_id)
    kill_op.kill("alice", state_dir=tmp_path / "state")
    time.sleep(0.1)
    assert state.load("alice", state_dir=tmp_path / "state") is None
    assert not mux_mod.pane_alive(s.pane_id)


def test_kill_missing_is_idempotent(tmp_path: Path, tmux_server) -> None:
    kill_op.kill("ghost", state_dir=tmp_path / "state")  # must not raise


def test_kill_all_removes_every_agent(tmp_path: Path, tmux_server, fake_claude) -> None:
    spawn_op.spawn("claude", "alice", cwd=str(tmp_path), state_dir=tmp_path / "state")
    spawn_op.spawn("claude", "bob",   cwd=str(tmp_path), state_dir=tmp_path / "state")
    kill_op.kill_all(state_dir=tmp_path / "state")
    assert state.list_all(state_dir=tmp_path / "state") == []

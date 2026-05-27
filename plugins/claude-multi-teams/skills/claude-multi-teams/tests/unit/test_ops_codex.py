"""Ops tests for the codex agent (spawn / ask / status / last-reply / kill).

Exercises the codex-specific dispatch in ops/* — pre_spawn_marker snapshot,
post_spawn_warmup banner wait, delayed session_file resolution on first ask,
status_codex / extract_codex_response.

Uses the ``fake_codex`` conftest fixture which installs a sandboxed
CODEX_HOME and a fake codex binary that prints the banner immediately and
writes codex-shaped rollout jsonl for each prompt.
"""

import time
from pathlib import Path

import pytest

from cmt import state
from cmt.ops import ask as ask_op
from cmt.ops import kill as kill_op
from cmt.ops import last_reply as last_reply_op
from cmt.ops import spawn as spawn_op
from cmt.ops import status as status_op


def test_spawn_codex_session_file_none_initially(tmp_path: Path, tmux_server, fake_codex) -> None:
    s = spawn_op.spawn("codex", "alice", cwd=str(tmp_path), state_dir=tmp_path / "state")
    assert s.agent == "codex"
    assert s.session_file is None  # resolved on first ask
    assert s.spawn_marker is not None  # snapshot was captured
    # spawn_marker is a float string
    assert float(s.spawn_marker) >= 0.0


def test_spawn_codex_warmup_completes(tmp_path: Path, tmux_server, fake_codex) -> None:
    # Fake prints banner immediately, so warmup returns. If it didn't,
    # spawn would block (or timeout-raise).
    s = spawn_op.spawn("codex", "alice", cwd=str(tmp_path), state_dir=tmp_path / "state")
    assert s.pane_id.startswith("%")


def test_ask_first_turn_resolves_session_file_and_returns_text(
    tmp_path: Path, tmux_server, fake_codex
) -> None:
    spawn_op.spawn("codex", "alice", cwd=str(tmp_path), state_dir=tmp_path / "state")
    time.sleep(0.4)
    reply = ask_op.ask("alice", "ping", state_dir=tmp_path / "state")
    assert reply == "echo: ping"
    # session_file now persisted
    loaded = state.load("alice", state_dir=tmp_path / "state")
    assert loaded is not None
    assert loaded.session_file is not None
    assert "rollout-" in loaded.session_file


def test_ask_two_turns_codex(tmp_path: Path, tmux_server, fake_codex) -> None:
    """codex first ask must resolve the session file; second ask must read
    a *new* baseline within that same file (fake writes a NEW rollout per
    prompt — but real codex appends. We assert each reply text is correct
    regardless of which file the resolver picks for turn 2)."""
    spawn_op.spawn("codex", "alice", cwd=str(tmp_path), state_dir=tmp_path / "state")
    time.sleep(0.4)
    r1 = ask_op.ask("alice", "first", state_dir=tmp_path / "state")
    r2 = ask_op.ask("alice", "second", state_dir=tmp_path / "state")
    assert r1 == "echo: first"
    assert r2 == "echo: second"


def test_status_returns_done_for_codex_with_no_session_yet(
    tmp_path: Path, tmux_server, fake_codex
) -> None:
    spawn_op.spawn("codex", "alice", cwd=str(tmp_path), state_dir=tmp_path / "state")
    assert status_op.status("alice", state_dir=tmp_path / "state") == "done"


def test_status_done_after_codex_ask(tmp_path: Path, tmux_server, fake_codex) -> None:
    spawn_op.spawn("codex", "alice", cwd=str(tmp_path), state_dir=tmp_path / "state")
    time.sleep(0.4)
    ask_op.ask("alice", "ping", state_dir=tmp_path / "state")
    assert status_op.status("alice", state_dir=tmp_path / "state") == "done"


def test_last_reply_codex(tmp_path: Path, tmux_server, fake_codex) -> None:
    spawn_op.spawn("codex", "alice", cwd=str(tmp_path), state_dir=tmp_path / "state")
    time.sleep(0.4)
    ask_op.ask("alice", "ping", state_dir=tmp_path / "state")
    assert last_reply_op.last_reply("alice", state_dir=tmp_path / "state") == "echo: ping"


def test_kill_codex(tmp_path: Path, tmux_server, fake_codex) -> None:
    s = spawn_op.spawn("codex", "alice", cwd=str(tmp_path), state_dir=tmp_path / "state")
    from cmt import mux as mux_mod
    assert mux_mod.pane_alive(s.pane_id)
    kill_op.kill("alice", state_dir=tmp_path / "state")
    time.sleep(0.1)
    assert state.load("alice", state_dir=tmp_path / "state") is None
    assert not mux_mod.pane_alive(s.pane_id)

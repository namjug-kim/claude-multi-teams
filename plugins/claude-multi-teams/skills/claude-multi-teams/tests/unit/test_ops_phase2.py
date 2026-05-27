"""Phase-2 ops: send / keys / capture / last-reply / status / wait-status /
wait-output / whoami / list. Tested against real tmux + fake claude.
"""

import time
from pathlib import Path

import pytest

from cmt import mux, state
from cmt.ops import (
    ask as ask_op,
    capture as capture_op,
    keys as keys_op,
    kill as kill_op,
    last_reply as last_reply_op,
    list_ as list_op,
    send as send_op,
    spawn as spawn_op,
    status as status_op,
    wait_output as wait_output_op,
    wait_status as wait_status_op,
    whoami as whoami_op,
)


# --- send / keys ---


def test_send_pastes_text_and_presses_enter(tmp_path, tmux_server, fake_claude) -> None:
    s = spawn_op.spawn("claude", "alice", cwd=str(tmp_path), state_dir=tmp_path / "state")
    time.sleep(0.3)
    send_op.send("alice", "hello", state_dir=tmp_path / "state")
    time.sleep(0.5)
    jsonl = next(Path(fake_claude["config_dir"]).rglob("*.jsonl"))
    assert "hello" in jsonl.read_text()


def test_send_no_enter_does_not_submit(tmp_path, tmux_server, fake_claude) -> None:
    s = spawn_op.spawn("claude", "alice", cwd=str(tmp_path), state_dir=tmp_path / "state")
    time.sleep(0.3)
    send_op.send("alice", "no-enter", enter=False, state_dir=tmp_path / "state")
    time.sleep(0.4)
    # No jsonl written because no Enter — fake-claude never read the line
    cfg = Path(fake_claude["config_dir"])
    jsonl_files = list(cfg.rglob("*.jsonl"))
    if jsonl_files:
        assert "no-enter" not in jsonl_files[0].read_text()


def test_keys_send_arbitrary_keys(tmp_path, tmux_server, fake_claude) -> None:
    s = spawn_op.spawn("claude", "alice", cwd=str(tmp_path), state_dir=tmp_path / "state")
    time.sleep(0.3)
    # Type "abc" then Enter via individual keys
    keys_op.keys("alice", ["a", "b", "c", "Enter"], state_dir=tmp_path / "state")
    time.sleep(0.5)
    jsonl = next(Path(fake_claude["config_dir"]).rglob("*.jsonl"))
    assert "abc" in jsonl.read_text()


# --- capture ---


def test_capture_returns_pane_text(tmp_path, tmux_server, fake_claude) -> None:
    spawn_op.spawn("claude", "alice", cwd=str(tmp_path), state_dir=tmp_path / "state")
    time.sleep(0.3)
    # Push a known marker into the pane (terminal echoes paste), then capture.
    send_op.send("alice", "CAPTURE-MARKER-X7", enter=False, state_dir=tmp_path / "state")
    time.sleep(0.2)
    text = capture_op.capture("alice", state_dir=tmp_path / "state")
    assert "CAPTURE-MARKER-X7" in text


def test_capture_mode_param(tmp_path, tmux_server, fake_claude) -> None:
    s = spawn_op.spawn("claude", "alice", cwd=str(tmp_path), state_dir=tmp_path / "state")
    time.sleep(0.3)
    visible = capture_op.capture("alice", mode="visible", state_dir=tmp_path / "state")
    full = capture_op.capture("alice", mode="full", state_dir=tmp_path / "state")
    wrapped = capture_op.capture("alice", mode="wrapped", state_dir=tmp_path / "state")
    assert all(isinstance(x, str) for x in (visible, full, wrapped))


# --- last-reply ---


def test_last_reply_returns_most_recent(tmp_path, tmux_server, fake_claude) -> None:
    s = spawn_op.spawn("claude", "alice", cwd=str(tmp_path), state_dir=tmp_path / "state")
    time.sleep(0.3)
    ask_op.ask("alice", "first", state_dir=tmp_path / "state")
    ask_op.ask("alice", "second", state_dir=tmp_path / "state")
    reply = last_reply_op.last_reply("alice", state_dir=tmp_path / "state")
    assert reply == "echo: second"


def test_last_reply_empty_when_no_ask_yet(tmp_path, tmux_server, fake_claude) -> None:
    spawn_op.spawn("claude", "alice", cwd=str(tmp_path), state_dir=tmp_path / "state")
    time.sleep(0.3)
    reply = last_reply_op.last_reply("alice", state_dir=tmp_path / "state")
    assert reply == ""


# --- status ---


def test_status_idle_after_spawn(tmp_path, tmux_server, fake_claude) -> None:
    spawn_op.spawn("claude", "alice", cwd=str(tmp_path), state_dir=tmp_path / "state")
    time.sleep(0.3)
    assert status_op.status("alice", state_dir=tmp_path / "state") == "done"


def test_status_done_after_completed_ask(tmp_path, tmux_server, fake_claude) -> None:
    spawn_op.spawn("claude", "alice", cwd=str(tmp_path), state_dir=tmp_path / "state")
    time.sleep(0.3)
    ask_op.ask("alice", "x", state_dir=tmp_path / "state")
    assert status_op.status("alice", state_dir=tmp_path / "state") == "done"


def test_status_dead_after_kill(tmp_path, tmux_server, fake_claude) -> None:
    spawn_op.spawn("claude", "alice", cwd=str(tmp_path), state_dir=tmp_path / "state")
    time.sleep(0.3)
    s = state.load("alice", state_dir=tmp_path / "state")
    mux.kill_pane(s.pane_id)
    time.sleep(0.2)
    assert status_op.status("alice", state_dir=tmp_path / "state") == "dead"


# --- wait-status ---


def test_wait_status_returns_when_target_reached(tmp_path, tmux_server, fake_claude) -> None:
    spawn_op.spawn("claude", "alice", cwd=str(tmp_path), state_dir=tmp_path / "state")
    time.sleep(0.3)
    ok = wait_status_op.wait_status("alice", target="done", state_dir=tmp_path / "state",
                                    poll_interval=0.05)
    assert ok is True


def test_wait_status_returns_false_on_dead(tmp_path, tmux_server, fake_claude) -> None:
    s = spawn_op.spawn("claude", "alice", cwd=str(tmp_path), state_dir=tmp_path / "state")
    mux.kill_pane(s.pane_id)
    time.sleep(0.2)
    # Asking to wait for "done" but pane is dead — function returns False (dead != done)
    ok = wait_status_op.wait_status("alice", target="done", state_dir=tmp_path / "state",
                                    poll_interval=0.05)
    assert ok is False


# --- wait-output ---


def test_wait_output_substring_match(tmp_path, tmux_server, fake_claude) -> None:
    spawn_op.spawn("claude", "alice", cwd=str(tmp_path), state_dir=tmp_path / "state")
    time.sleep(0.3)
    # fake-claude is silent — paste a visible marker via the pane's local echo
    send_op.send("alice", "VISIBLE-MARKER", enter=False, state_dir=tmp_path / "state")
    found = wait_output_op.wait_output(
        "alice", pattern="VISIBLE-MARKER", as_text=True, state_dir=tmp_path / "state",
        poll_interval=0.05,
    )
    assert found is True


def test_wait_output_regex_match(tmp_path, tmux_server, fake_claude) -> None:
    spawn_op.spawn("claude", "alice", cwd=str(tmp_path), state_dir=tmp_path / "state")
    time.sleep(0.3)
    send_op.send("alice", "MARK-42", enter=False, state_dir=tmp_path / "state")
    found = wait_output_op.wait_output(
        "alice", pattern=r"MARK-\d+", as_text=False, state_dir=tmp_path / "state",
        poll_interval=0.05,
    )
    assert found is True


def test_wait_output_returns_false_on_dead(tmp_path, tmux_server, fake_claude) -> None:
    s = spawn_op.spawn("claude", "alice", cwd=str(tmp_path), state_dir=tmp_path / "state")
    mux.kill_pane(s.pane_id)
    time.sleep(0.2)
    found = wait_output_op.wait_output(
        "alice", pattern="never-will-match", as_text=True, state_dir=tmp_path / "state",
        poll_interval=0.05,
    )
    assert found is False


# --- whoami ---


def test_whoami_resolves_via_env(tmp_path, tmux_server, fake_claude, monkeypatch) -> None:
    s = spawn_op.spawn("claude", "alice", cwd=str(tmp_path), state_dir=tmp_path / "state")
    monkeypatch.setenv("CMT_AGENT_ID", s.agent_id)
    me = whoami_op.whoami(state_dir=tmp_path / "state")
    assert me.name == "alice"
    assert me.agent_id == s.agent_id


def test_whoami_returns_none_when_no_env(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("CMT_AGENT_ID", raising=False)
    assert whoami_op.whoami(state_dir=tmp_path / "state") is None


def test_whoami_returns_none_when_env_unknown(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CMT_AGENT_ID", "ghost-id")
    assert whoami_op.whoami(state_dir=tmp_path / "state") is None


# --- list ---


def test_list_empty(tmp_path) -> None:
    assert list_op.list_agents(state_dir=tmp_path / "state") == []


def test_list_returns_all(tmp_path, tmux_server, fake_claude) -> None:
    spawn_op.spawn("claude", "alice", cwd=str(tmp_path), state_dir=tmp_path / "state")
    spawn_op.spawn("claude", "bob",   cwd=str(tmp_path), state_dir=tmp_path / "state")
    names = sorted(s.name for s in list_op.list_agents(state_dir=tmp_path / "state"))
    assert names == ["alice", "bob"]

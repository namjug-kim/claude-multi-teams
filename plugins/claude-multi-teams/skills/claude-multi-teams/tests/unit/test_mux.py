"""mux.py tests, exercised against a real detached tmux server per-test
(see ``tmux_server`` fixture in conftest.py).
"""

import os
import shutil
import time
from pathlib import Path

import pytest

from cmt import mux

pytestmark = pytest.mark.skipif(
    shutil.which("tmux") is None, reason="tmux binary required"
)


def test_split_pane_returns_new_pane_id(tmux_server) -> None:
    parent = tmux_server
    new_pane = mux.split_pane(parent, cwd="/tmp", cmd="bash", env_vars={})
    assert new_pane.startswith("%")
    assert new_pane != parent


def test_split_pane_injects_env_vars(tmux_server) -> None:
    parent = tmux_server
    new_pane = mux.split_pane(
        parent, cwd="/tmp",
        cmd="bash -c 'echo MARKER=$CMT_AGENT_ID; sleep 30'",
        env_vars={"CMT_AGENT_ID": "test-id-abc"},
    )
    # let bash run + print
    time.sleep(0.4)
    screen = mux.capture(new_pane)
    assert "MARKER=test-id-abc" in screen


def test_pane_alive_true_then_false(tmux_server) -> None:
    parent = tmux_server
    pane = mux.split_pane(parent, cwd="/tmp", cmd="bash -c 'sleep 30'", env_vars={})
    assert mux.pane_alive(pane) is True
    mux.kill_pane(pane)
    # give tmux a moment to clean up
    time.sleep(0.1)
    assert mux.pane_alive(pane) is False


def test_paste_bracketed_delivers_text(tmux_server) -> None:
    parent = tmux_server
    pane = mux.split_pane(parent, cwd="/tmp", cmd="cat", env_vars={})
    time.sleep(0.2)
    mux.paste_bracketed(pane, "HELLO-PASTED")
    time.sleep(0.2)
    screen = mux.capture(pane)
    assert "HELLO-PASTED" in screen


def test_send_keys_sends_literal_key(tmux_server) -> None:
    parent = tmux_server
    pane = mux.split_pane(parent, cwd="/tmp", cmd="bash", env_vars={})
    time.sleep(0.2)
    mux.send_keys(pane, "echo", "Space", "KEYS-TEST", "Enter")
    time.sleep(0.3)
    screen = mux.capture(pane)
    assert "KEYS-TEST" in screen


def test_send_text_pastes_then_presses_enter(tmux_server) -> None:
    parent = tmux_server
    pane = mux.split_pane(parent, cwd="/tmp", cmd="bash", env_vars={})
    time.sleep(0.2)
    mux.send_text(pane, "echo SEND-TEXT-OK")
    time.sleep(0.3)
    screen = mux.capture(pane)
    assert "SEND-TEXT-OK" in screen


def test_capture_modes(tmux_server) -> None:
    parent = tmux_server
    pane = mux.split_pane(parent, cwd="/tmp", cmd="bash", env_vars={})
    time.sleep(0.2)
    mux.send_text(pane, "for i in 1 2 3; do echo line$i; done")
    time.sleep(0.4)
    full = mux.capture(pane, mode="full")
    visible = mux.capture(pane, mode="visible")
    wrapped = mux.capture(pane, mode="wrapped")
    assert "line1" in full and "line2" in full and "line3" in full
    assert isinstance(visible, str)
    assert isinstance(wrapped, str)


def test_list_panes_returns_known_panes(tmux_server) -> None:
    parent = tmux_server
    new_pane = mux.split_pane(parent, cwd="/tmp", cmd="bash", env_vars={})
    panes = mux.list_panes()
    assert parent in panes
    assert new_pane in panes


def test_kill_pane_idempotent_on_missing(tmux_server) -> None:
    # killing a nonexistent pane should not raise
    mux.kill_pane("%99999")


def test_pane_alive_false_for_unknown(tmux_server) -> None:
    assert mux.pane_alive("%99999") is False


def test_paste_bracketed_branches_to_cmux_when_in_claude_teams(tmux_server, monkeypatch) -> None:
    """When ``$TMUX`` points at the cmux ``claude-teams`` fake tmux path, mux
    routes paste through the ``cmux`` CLI (not ``tmux``). We don't have a
    real cmux server in this test, so we shim ``cmux`` with a bash function
    that records its argv to a file and exits 0. The dispatch is what's
    under test, not the cmux side-effects.
    """
    # The tmux_server fixture set $TMUX to our real-tmux test socket.
    # Override it so _use_cmux_native() returns True.
    monkeypatch.setenv("TMUX", "/tmp/cmux-claude-teams/fake,0,0")

    fake_bin = Path(os.environ["HOME"]) / ".cmt-test-bin"
    fake_bin.mkdir(exist_ok=True)
    log = fake_bin / "cmux-calls.log"
    log.write_text("")
    fake_cmux = fake_bin / "cmux"
    fake_cmux.write_text(
        f'#!/bin/sh\necho "$@" >> {log}\nexit 0\n'
    )
    fake_cmux.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake_bin}:{os.environ['PATH']}")
    try:
        mux.paste_bracketed("surface:99", "CMUX-PATH-TEXT")
        calls = log.read_text()
        assert "set-buffer" in calls
        assert "paste-buffer" in calls
        assert "surface:99" in calls
    finally:
        shutil.rmtree(fake_bin, ignore_errors=True)

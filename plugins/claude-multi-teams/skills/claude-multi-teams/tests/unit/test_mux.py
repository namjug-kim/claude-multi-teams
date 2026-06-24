"""mux.py tests, exercised against a real detached tmux server per-test
(see ``tmux_server`` fixture in conftest.py).
"""

import os
import shutil
import subprocess
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


def test_current_pane_prefers_process_ancestry_over_stale_env(monkeypatch) -> None:
    """A stale inherited TMUX_PANE must not make kill() think a sibling pane is
    the orchestrator. The pane whose root pid is in cmt's ancestry wins."""
    monkeypatch.setenv("TMUX", "/tmp/tmux-test,0,0")
    monkeypatch.delenv("CMUX_SOCKET_PATH", raising=False)
    monkeypatch.setenv("TMUX_PANE", "%stale")

    def fake_tmux(*args, **kwargs):
        if args[:3] == ("list-panes", "-a", "-F"):
            return subprocess.CompletedProcess(
                ["tmux", *args],
                0,
                stdout="%actual 111\n%stale 222\n",
                stderr="",
            )
        if args and args[0] == "display-message":
            return subprocess.CompletedProcess(
                ["tmux", *args],
                0,
                stdout="%selected\n",
                stderr="",
            )
        raise AssertionError(args)

    monkeypatch.setattr(mux, "_tmux", fake_tmux)
    monkeypatch.setattr(mux, "_tmux_pane_alive", lambda pane: True)
    monkeypatch.setattr(mux, "_process_ancestors", lambda: {111, 999})

    assert mux.current_pane() == "%actual"


def test_current_pane_falls_back_to_env_when_ancestry_unmatched(tmux_server, monkeypatch) -> None:
    """When cmt cannot match process ancestry to a tmux pane, a live
    TMUX_PANE remains the best available current-pane hint."""
    parent = tmux_server
    child = mux.split_pane(parent, cwd="/tmp", cmd="bash", env_vars={})
    mux._tmux("select-pane", "-t", child)
    monkeypatch.setenv("TMUX_PANE", parent)
    assert mux.current_pane() == parent


def test_current_pane_does_not_fall_back_to_selected_pane(monkeypatch) -> None:
    """A non-tty caller may see a sibling as tmux's selected pane. Without
    process ancestry or a live TMUX_PANE, current pane is unknown."""
    monkeypatch.setenv("TMUX", "/tmp/tmux-test,0,0")
    monkeypatch.delenv("CMUX_SOCKET_PATH", raising=False)
    monkeypatch.setenv("TMUX_PANE", "%dead")

    def fake_tmux(*args, **kwargs):
        if args[:3] == ("list-panes", "-a", "-F"):
            return subprocess.CompletedProcess(
                ["tmux", *args],
                0,
                stdout="%selected 222\n",
                stderr="",
            )
        if args and args[0] == "display-message":
            raise AssertionError("selected pane fallback must not be used")
        raise AssertionError(args)

    monkeypatch.setattr(mux, "_tmux", fake_tmux)
    monkeypatch.setattr(mux, "_tmux_pane_alive", lambda pane: False)
    monkeypatch.setattr(mux, "_process_ancestors", lambda: {999})

    assert mux.current_pane() is None


def test_real_tmux_wins_over_stale_cmux_socket_path(tmux_server, monkeypatch) -> None:
    """A real tmux session is authoritative even if cmux env leaks in.

    In this state cmt must stay on the tmux backend. Routing through cmux makes
    otherwise valid tmux sessions unusable when the inherited cmux socket is
    stale or broken.
    """
    parent = tmux_server
    monkeypatch.setenv("CMUX_SOCKET_PATH", "/tmp/stale-cmux.sock")
    fake_bin = Path(os.environ["HOME"]) / ".cmt-test-bin-stale-cmux"
    fake_bin.mkdir(exist_ok=True)
    fake_cmux = fake_bin / "cmux"
    fake_cmux.write_text("#!/bin/sh\nexit 77\n")
    fake_cmux.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake_bin}:{os.environ['PATH']}")
    try:
        assert parent in mux.list_panes()
    finally:
        shutil.rmtree(fake_bin, ignore_errors=True)


def test_tmux_server_fixture_clears_cmux_binary_env(monkeypatch, request) -> None:
    """cmux-launched shells can export a real cmux binary path.

    The tmux_server fixture must clear it before tests install PATH shims;
    otherwise cmux backend tests can call the user's real app instead of the
    fake test binary.
    """
    monkeypatch.setenv("CMUX_CLAUDE_HOOK_CMUX_BIN", "/bin/false")

    request.getfixturevalue("tmux_server")

    assert "CMUX_CLAUDE_HOOK_CMUX_BIN" not in os.environ


def test_cmux_detection_requires_fake_path_directory(monkeypatch) -> None:
    monkeypatch.setenv("TMUX", "/tmp/cmux-real-tmux.sock,0,0")
    monkeypatch.setenv("CMUX_SOCKET_PATH", "/tmp/stale-cmux.sock")

    assert mux._use_cmux_native() is False


def test_cmux_resolves_app_bundle_binary_when_not_on_path(tmp_path: Path, tmux_server, monkeypatch) -> None:
    """cmux codex-teams exposes ``CMUX_SOCKET_PATH`` to tool processes but may
    not put a ``cmux`` executable on PATH. cmt must still find the app bundle
    CLI instead of failing with FileNotFoundError."""
    monkeypatch.setenv("TMUX", "/tmp/cmux-claude-teams/fake,0,0")
    monkeypatch.setenv("PATH", str(tmp_path / "empty-bin"))
    for env_var in mux._CMUX_ENV_VARS:
        monkeypatch.delenv(env_var, raising=False)
    fake_app_bin = tmp_path / "cmux.app" / "Contents" / "Resources" / "bin"
    fake_app_bin.mkdir(parents=True)
    log = tmp_path / "cmux-calls.log"
    fake_cmux = fake_app_bin / "cmux"
    fake_cmux.write_text(f'#!/bin/sh\necho "$@" >> {log}\nexit 0\n')
    fake_cmux.chmod(0o755)
    monkeypatch.setattr(mux, "_CMUX_BUNDLE_CANDIDATES", (str(fake_cmux),))

    mux._cmux("list-pane-surfaces", check=False)

    assert log.read_text().strip() == "list-pane-surfaces"


def test_cmux_env_binary_takes_precedence_over_bundle(tmp_path: Path, tmux_server, monkeypatch) -> None:
    monkeypatch.setenv("TMUX", "/tmp/cmux-claude-teams/fake,0,0")
    monkeypatch.setenv("PATH", str(tmp_path / "empty-bin"))
    for env_var in mux._CMUX_ENV_VARS:
        monkeypatch.delenv(env_var, raising=False)
    bundle_bin = tmp_path / "bundle" / "cmux"
    bundle_bin.parent.mkdir()
    bundle_log = tmp_path / "bundle.log"
    bundle_bin.write_text(f'#!/bin/sh\necho "$@" >> {bundle_log}\nexit 0\n')
    bundle_bin.chmod(0o755)
    env_bin = tmp_path / "env" / "cmux"
    env_bin.parent.mkdir()
    env_log = tmp_path / "env.log"
    env_bin.write_text(f'#!/bin/sh\necho "$@" >> {env_log}\nexit 0\n')
    env_bin.chmod(0o755)
    monkeypatch.setattr(mux, "_CMUX_BUNDLE_CANDIDATES", (str(bundle_bin),))
    monkeypatch.setenv("CMT_CMUX_BIN", str(env_bin))

    mux._cmux("list-pane-surfaces", check=False)

    assert env_log.read_text().strip() == "list-pane-surfaces"
    assert not bundle_log.exists()


def test_kill_pane_idempotent_on_missing(tmux_server) -> None:
    # killing a nonexistent pane should not raise
    mux.kill_pane("%99999")


def test_pane_alive_false_for_unknown(tmux_server) -> None:
    assert mux.pane_alive("%99999") is False


def test_paste_bracketed_branches_to_cmux_when_in_claude_teams(tmux_server, monkeypatch) -> None:
    """When ``$TMUX`` points at a cmux teams fake tmux path, mux
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


def test_cmux_codex_teams_tmux_prefix_uses_cmux_backend(tmux_server, monkeypatch) -> None:
    """``cmux codex-teams`` uses the same fake-tmux family as
    ``claude-teams``. It must not fall through to real tmux and treat
    ``surface:N`` ids as dead tmux panes."""
    monkeypatch.setenv("TMUX", "/tmp/cmux-codex-teams/fake,0,0")

    fake_bin = Path(os.environ["HOME"]) / ".cmt-test-bin-codex-teams"
    fake_bin.mkdir(exist_ok=True)
    log = fake_bin / "cmux-calls.log"
    log.write_text("")
    fake_cmux = fake_bin / "cmux"
    fake_cmux.write_text(f'#!/bin/sh\necho "$@" >> {log}\nexit 0\n')
    fake_cmux.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake_bin}:{os.environ['PATH']}")
    try:
        assert mux.pane_alive("surface:99") is True
        assert "capture-pane --surface surface:99" in log.read_text()
    finally:
        shutil.rmtree(fake_bin, ignore_errors=True)


def test_cmux_kill_pane_skips_non_surface_ids(tmux_server, monkeypatch) -> None:
    """``cmux close-surface`` defaults to the focused surface ($CMUX_SURFACE_ID
    — the user's main tab) when it can't resolve --surface. A stale or
    cross-backend id (empty, or a tmux "%id") must therefore never reach it.
    A real ``surface:N`` ref still goes through."""
    monkeypatch.setenv("TMUX", "/tmp/cmux-claude-teams/fake,0,0")
    fake_bin = Path(os.environ["HOME"]) / ".cmt-test-bin-kill"
    fake_bin.mkdir(exist_ok=True)
    log = fake_bin / "cmux-calls.log"
    log.write_text("")
    fake_cmux = fake_bin / "cmux"
    fake_cmux.write_text(f'#!/bin/sh\necho "$@" >> {log}\nexit 0\n')
    fake_cmux.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake_bin}:{os.environ['PATH']}")
    try:
        mux.kill_pane("%5")
        mux.kill_pane("")
        mux.kill_pane("surface:")     # malformed: no number
        mux.kill_pane("surface:abc")  # malformed: non-numeric
        assert log.read_text().strip() == ""  # cmux never invoked
        mux.kill_pane("surface:99")
        assert "close-surface --surface surface:99" in log.read_text()
    finally:
        shutil.rmtree(fake_bin, ignore_errors=True)


def test_cmux_pane_alive_false_for_non_surface_ids(tmux_server, monkeypatch) -> None:
    """``pane_alive`` on a non-surface id returns False without calling
    capture-pane, which could otherwise fall back to the focused surface and
    falsely report it alive — defeating the kill-time liveness guard."""
    monkeypatch.setenv("TMUX", "/tmp/cmux-claude-teams/fake,0,0")
    fake_bin = Path(os.environ["HOME"]) / ".cmt-test-bin-alive"
    fake_bin.mkdir(exist_ok=True)
    log = fake_bin / "cmux-calls.log"
    log.write_text("")
    fake_cmux = fake_bin / "cmux"
    fake_cmux.write_text(f'#!/bin/sh\necho "$@" >> {log}\nexit 0\n')
    fake_cmux.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake_bin}:{os.environ['PATH']}")
    try:
        assert mux.pane_alive("%5") is False
        assert mux.pane_alive("") is False
        assert mux.pane_alive("surface:") is False     # malformed: no number
        assert mux.pane_alive("surface:abc") is False  # malformed: non-numeric
        assert log.read_text().strip() == ""  # capture-pane never invoked
    finally:
        shutil.rmtree(fake_bin, ignore_errors=True)


def test_cmux_send_keys_and_paste_skip_non_surface_ids(tmux_server, monkeypatch) -> None:
    """Input paths share close-surface's focused-surface fallback: a stale or
    cross-backend id ("%5", "") delivered via send-key / send / paste-buffer
    would land keystrokes/text on the user's main tab. Guard them like
    close-surface; a real ``surface:N`` still goes through."""
    monkeypatch.setenv("TMUX", "/tmp/cmux-claude-teams/fake,0,0")
    fake_bin = Path(os.environ["HOME"]) / ".cmt-test-bin-input"
    fake_bin.mkdir(exist_ok=True)
    log = fake_bin / "cmux-calls.log"
    log.write_text("")
    fake_cmux = fake_bin / "cmux"
    fake_cmux.write_text(f'#!/bin/sh\necho "$@" >> {log}\nexit 0\n')
    fake_cmux.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake_bin}:{os.environ['PATH']}")
    try:
        mux.send_keys("%5", "Enter")
        mux.send_keys("", "Escape")
        mux.paste_bracketed("%5", "stale text")
        mux.send_text("", "more text")
        assert log.read_text().strip() == ""  # cmux never invoked
        mux.send_keys("surface:99", "Enter")
        assert "send-key --surface surface:99 enter" in log.read_text()
    finally:
        shutil.rmtree(fake_bin, ignore_errors=True)


def test_cmux_pane_alive_false_for_dead_surface(tmux_server, monkeypatch) -> None:
    """A well-formed but recycled/dead ``surface:N`` (the bug's root case) must
    read as not-alive: cmux ``capture-pane`` on a missing surface exits
    non-zero. Unlike the malformed-id case, capture-pane IS invoked here."""
    monkeypatch.setenv("TMUX", "/tmp/cmux-claude-teams/fake,0,0")
    fake_bin = Path(os.environ["HOME"]) / ".cmt-test-bin-dead"
    fake_bin.mkdir(exist_ok=True)
    log = fake_bin / "cmux-calls.log"
    log.write_text("")
    fake_cmux = fake_bin / "cmux"
    # exit 1 mimics capture-pane on a missing/recycled surface
    fake_cmux.write_text(f'#!/bin/sh\necho "$@" >> {log}\nexit 1\n')
    fake_cmux.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake_bin}:{os.environ['PATH']}")
    try:
        assert mux.pane_alive("surface:239") is False
        assert "capture-pane --surface surface:239" in log.read_text()
    finally:
        shutil.rmtree(fake_bin, ignore_errors=True)


def test_cmux_capture_returns_empty_for_non_surface_ids(tmux_server, monkeypatch) -> None:
    """capture-pane with an empty --surface falls back to the focused surface,
    so `cmt capture`/`modal` on a stale or malformed id would read the user's
    main tab. _cmux_capture must fail closed (return "") without calling cmux."""
    monkeypatch.setenv("TMUX", "/tmp/cmux-claude-teams/fake,0,0")
    fake_bin = Path(os.environ["HOME"]) / ".cmt-test-bin-cap"
    fake_bin.mkdir(exist_ok=True)
    log = fake_bin / "cmux-calls.log"
    log.write_text("")
    fake_cmux = fake_bin / "cmux"
    fake_cmux.write_text(f'#!/bin/sh\necho "$@" >> {log}\nexit 0\n')
    fake_cmux.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake_bin}:{os.environ['PATH']}")
    try:
        for bad in ("%5", "", "surface:", "surface:abc"):
            assert mux.capture(bad, mode="full") == ""
        assert log.read_text().strip() == ""  # cmux never invoked
    finally:
        shutil.rmtree(fake_bin, ignore_errors=True)


def test_cmux_send_keys_routes_literal_chars_through_send(tmux_server, monkeypatch) -> None:
    """cmux ``send-key`` rejects literal characters ("Unknown key"), so a menu
    digit like "2" must go through ``cmux send`` (text), while named keys
    ("Enter") stay on ``send-key``. Regression for codex modal dismissal."""
    monkeypatch.setenv("TMUX", "/tmp/cmux-claude-teams/fake,0,0")
    fake_bin = Path(os.environ["HOME"]) / ".cmt-test-bin-keys"
    fake_bin.mkdir(exist_ok=True)
    log = fake_bin / "cmux-calls.log"
    log.write_text("")
    fake_cmux = fake_bin / "cmux"
    fake_cmux.write_text(f'#!/bin/sh\necho "$@" >> {log}\nexit 0\n')
    fake_cmux.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake_bin}:{os.environ['PATH']}")
    try:
        mux.send_keys("surface:99", "2", "Enter")
        lines = [ln for ln in log.read_text().splitlines() if ln.strip()]
        assert lines[0] == "send --surface surface:99 2"
        assert lines[1] == "send-key --surface surface:99 enter"
    finally:
        shutil.rmtree(fake_bin, ignore_errors=True)


def test_cmux_split_pane_closes_pane_when_send_fails(tmux_server, monkeypatch) -> None:
    """`new-pane` succeeds but the follow-up `send` fails: the created surface
    must be closed before the error propagates. Otherwise split_pane raises
    before returning the id, so spawn never records state and the live pane is
    an orphan no cmt command can ever reap."""
    monkeypatch.setenv("TMUX", "/tmp/cmux-claude-teams/fake,0,0")
    fake_bin = Path(os.environ["HOME"]) / ".cmt-test-bin-splitfail"
    fake_bin.mkdir(exist_ok=True)
    log = fake_bin / "cmux-calls.log"
    log.write_text("")
    fake_cmux = fake_bin / "cmux"
    fake_cmux.write_text(
        "#!/bin/sh\n"
        f'echo "$@" >> {log}\n'
        'case "$1" in\n'
        '  new-pane) echo "OK surface:77 pane:5 workspace:1"; exit 0 ;;\n'
        "  send) exit 1 ;;\n"  # delivering the command fails
        "  *) exit 0 ;;\n"
        "esac\n"
    )
    fake_cmux.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake_bin}:{os.environ['PATH']}")
    try:
        with pytest.raises(subprocess.CalledProcessError):
            mux.split_pane("%parent", cwd="/tmp", cmd="bash", env_vars={})
        calls = log.read_text()
        assert "new-pane" in calls
        # the just-created surface must be reaped, not leaked
        assert "close-surface --surface surface:77" in calls
    finally:
        shutil.rmtree(fake_bin, ignore_errors=True)

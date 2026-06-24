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
    from cmt import mux as mux_mod
    monkeypatch.delenv("TMUX_PANE", raising=False)
    monkeypatch.delenv("TMUX", raising=False)
    monkeypatch.delenv("CMUX_SOCKET_PATH", raising=False)
    monkeypatch.setattr(mux_mod, "current_pane", lambda: None)
    with pytest.raises(RuntimeError):
        spawn_op.spawn("claude", "alice", cwd=str(tmp_path), state_dir=tmp_path / "state")


def test_spawn_uses_current_pane_when_tmux_pane_missing(tmp_path: Path, monkeypatch) -> None:
    from cmt import mux as mux_mod

    monkeypatch.delenv("TMUX_PANE", raising=False)
    monkeypatch.setattr(mux_mod, "current_pane", lambda: "surface:2581")

    parents: list[str] = []

    def fake_split_pane(parent, cwd, cmd, env_vars):
        parents.append(parent)
        return "surface:300"

    monkeypatch.setattr(mux_mod, "split_pane", fake_split_pane)

    s = spawn_op.spawn("claude", "alice", cwd=str(tmp_path), state_dir=tmp_path / "state")

    assert parents == ["surface:2581"]
    assert s.pane_id == "surface:300"


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


def test_kill_skips_close_when_pane_not_alive(tmp_path: Path, monkeypatch) -> None:
    """A stale state file (cmux restarted → surface ids recycled, or a foreign
    / cross-backend id) must NOT drive a blind close — cmux's close-surface
    falls back to the focused surface (the user's main tab) when it can't
    resolve the id. kill drops the state without touching the mux."""
    from cmt import mux as mux_mod
    s = state.AgentState(
        name="stale", agent="claude", agent_id="x", pane_id="surface:239",
        cwd="/tmp", started_at="2026-05-29T00:00:00Z",
    )
    state.save(s, state_dir=tmp_path / "state")
    calls: list[str] = []
    monkeypatch.setattr(mux_mod, "current_pane", lambda: None)
    monkeypatch.setattr(mux_mod, "pane_alive", lambda p: False)
    monkeypatch.setattr(mux_mod, "kill_pane", lambda p: calls.append(p))
    kill_op.kill("stale", state_dir=tmp_path / "state")
    assert calls == []  # never closed anything
    assert state.load("stale", state_dir=tmp_path / "state") is None  # state dropped


def test_kill_closes_pane_when_alive(tmp_path: Path, monkeypatch) -> None:
    from cmt import mux as mux_mod
    s = state.AgentState(
        name="live", agent="claude", agent_id="x", pane_id="surface:7",
        cwd="/tmp", started_at="2026-05-29T00:00:00Z",
    )
    state.save(s, state_dir=tmp_path / "state")
    calls: list[str] = []
    monkeypatch.setattr(mux_mod, "current_pane", lambda: None)
    monkeypatch.setattr(mux_mod, "pane_alive", lambda p: True)
    monkeypatch.setattr(mux_mod, "kill_pane", lambda p: calls.append(p))
    kill_op.kill("live", state_dir=tmp_path / "state")
    assert calls == ["surface:7"]
    assert state.load("live", state_dir=tmp_path / "state") is None


def test_kill_missing_is_idempotent(tmp_path: Path, tmux_server) -> None:
    kill_op.kill("ghost", state_dir=tmp_path / "state")  # must not raise


def test_kill_all_removes_every_agent(tmp_path: Path, tmux_server, fake_claude) -> None:
    spawn_op.spawn("claude", "alice", cwd=str(tmp_path), state_dir=tmp_path / "state")
    spawn_op.spawn("claude", "bob",   cwd=str(tmp_path), state_dir=tmp_path / "state")
    kill_op.kill_all(state_dir=tmp_path / "state")
    assert state.list_all(state_dir=tmp_path / "state") == []


def test_kill_all_skips_dead_panes(tmp_path: Path, monkeypatch) -> None:
    """kill_all over a mix of live + stale agents (the post-restart scenario)
    must close only the live ones — a stale surface:N must never be blind-closed."""
    from cmt import mux as mux_mod
    for nm, pane in (("live", "surface:7"), ("stale", "surface:239")):
        state.save(
            state.AgentState(
                name=nm, agent="claude", agent_id="x", pane_id=pane,
                cwd="/tmp", started_at="2026-05-29T00:00:00Z",
            ),
            state_dir=tmp_path / "state",
        )
    calls: list[str] = []
    monkeypatch.setattr(mux_mod, "current_pane", lambda: None)
    monkeypatch.setattr(mux_mod, "pane_alive", lambda p: p == "surface:7")
    monkeypatch.setattr(mux_mod, "kill_pane", lambda p: calls.append(p))
    kill_op.kill_all(state_dir=tmp_path / "state")
    assert calls == ["surface:7"]  # stale surface:239 never closed
    assert state.list_all(state_dir=tmp_path / "state") == []


def test_spawn_replace_skips_close_when_pane_not_alive(tmp_path: Path, monkeypatch) -> None:
    """spawn --replace over a stale/dead pane must drop the old state without a
    blind close — the same focused-surface hazard kill() guards against."""
    from cmt import mux as mux_mod
    state.save(
        state.AgentState(
            name="alice", agent="claude", agent_id="old", pane_id="surface:239",
            cwd="/tmp", started_at="2026-05-29T00:00:00Z",
        ),
        state_dir=tmp_path / "state",
    )
    monkeypatch.setenv("TMUX_PANE", "%0")
    calls: list[str] = []
    monkeypatch.setattr(mux_mod, "pane_alive", lambda p: False)
    monkeypatch.setattr(mux_mod, "kill_pane", lambda p: calls.append(p))
    monkeypatch.setattr(mux_mod, "split_pane", lambda *a, **k: "surface:300")
    s = spawn_op.spawn("claude", "alice", cwd=str(tmp_path), replace=True,
                       state_dir=tmp_path / "state")
    assert calls == []  # stale old pane never closed
    assert s.pane_id == "surface:300"


def test_spawn_replace_aborts_when_old_pane_wont_close(tmp_path: Path, monkeypatch) -> None:
    """spawn --replace over a LIVE pane whose close silently fails (still alive
    afterwards) must abort, not drop the old state + reuse the name — doing so
    would orphan the still-live old pane (its record overwritten by the new
    spawn). The old record must be preserved so `cmt kill` can still reap it."""
    from cmt import mux as mux_mod
    state.save(
        state.AgentState(
            name="alice", agent="claude", agent_id="old", pane_id="surface:7",
            cwd="/tmp", started_at="2026-05-29T00:00:00Z",
        ),
        state_dir=tmp_path / "state",
    )
    monkeypatch.setenv("TMUX_PANE", "%0")
    # pane stays alive even after kill_pane (close failed / busy)
    monkeypatch.setattr(mux_mod, "pane_alive", lambda p: True)
    monkeypatch.setattr(mux_mod, "kill_pane", lambda p: None)  # no-op close
    monkeypatch.setattr(mux_mod, "split_pane", lambda *a, **k: "surface:300")

    with pytest.raises(RuntimeError):
        spawn_op.spawn("claude", "alice", cwd=str(tmp_path), replace=True,
                       state_dir=tmp_path / "state")

    loaded = state.load("alice", state_dir=tmp_path / "state")
    assert loaded is not None and loaded.pane_id == "surface:7"  # old handle kept


def _ghost_on_current_pane(name: str, cwd: Path) -> state.AgentState:
    """A tracked agent whose pane_id is the pane cmt runs in — simulates a
    stale/recycled ``surface:N`` (or ``%pane``) ref now pointing at the
    orchestrator pane."""
    return state.AgentState(
        name=name, agent="claude", agent_id="ghost",
        pane_id=os.environ["TMUX_PANE"], cwd=str(cwd), started_at="t",
    )


def test_kill_refuses_current_pane(tmp_path: Path, tmux_server) -> None:
    state.save(_ghost_on_current_pane("ghost", tmp_path), state_dir=tmp_path / "state")
    with pytest.raises(RuntimeError, match="running in"):
        kill_op.kill("ghost", state_dir=tmp_path / "state")
    # state preserved AND the orchestrator pane is untouched
    assert state.load("ghost", state_dir=tmp_path / "state") is not None
    from cmt import mux as mux_mod
    assert mux_mod.pane_alive(os.environ["TMUX_PANE"])


def test_kill_all_skips_current_pane(tmp_path: Path, tmux_server, fake_claude) -> None:
    real = spawn_op.spawn("claude", "real", cwd=str(tmp_path), state_dir=tmp_path / "state")
    state.save(_ghost_on_current_pane("ghost", tmp_path), state_dir=tmp_path / "state")
    kill_op.kill_all(state_dir=tmp_path / "state")
    # real agent torn down; ghost (current pane) left alone; main pane survives
    assert state.load("real", state_dir=tmp_path / "state") is None
    assert state.load("ghost", state_dir=tmp_path / "state") is not None
    from cmt import mux as mux_mod
    assert mux_mod.pane_alive(os.environ["TMUX_PANE"])
    assert not mux_mod.pane_alive(real.pane_id)


def test_spawn_records_state_before_warmup(
    tmp_path: Path, tmux_server, fake_claude, monkeypatch
) -> None:
    """A provisional state file must exist WHILE warmup runs. The warmup window
    can be minutes (CMT_CODEX_WARMUP_DEADLINE); a hard-kill during it would
    otherwise leave a live pane with no record — an unreapable orphan."""
    import dataclasses
    from cmt import agents

    seen: dict = {}

    def recording_warmup(ctx, pane_id) -> None:
        seen["state"] = state.load(ctx.name, state_dir=ctx.state_dir)

    spec = dataclasses.replace(agents.AGENTS["claude"], post_spawn_warmup=recording_warmup)
    monkeypatch.setitem(agents.AGENTS, "claude", spec)

    spawn_op.spawn("claude", "alice", cwd=str(tmp_path), state_dir=tmp_path / "state")

    assert seen["state"] is not None  # provisional record present during warmup
    assert seen["state"].pane_id  # and it carries the pane id (reapable)


def test_spawn_warmup_failure_removes_state_and_kills_pane(
    tmp_path: Path, tmux_server, fake_claude, monkeypatch
) -> None:
    """If warmup fails, the provisional state AND the pane are torn down — a
    failed spawn leaves neither a stale record nor an orphan pane."""
    import dataclasses
    from cmt import agents
    from cmt import mux as mux_mod

    killed: list[str] = []
    monkeypatch.setattr(mux_mod, "kill_pane", lambda p: killed.append(p))

    def failing_warmup(ctx, pane_id) -> None:
        raise TimeoutError("banner never appeared")

    spec = dataclasses.replace(agents.AGENTS["claude"], post_spawn_warmup=failing_warmup)
    monkeypatch.setitem(agents.AGENTS, "claude", spec)

    with pytest.raises(TimeoutError):
        spawn_op.spawn("claude", "alice", cwd=str(tmp_path), state_dir=tmp_path / "state")

    assert killed  # pane closed
    assert state.load("alice", state_dir=tmp_path / "state") is None  # no stale record

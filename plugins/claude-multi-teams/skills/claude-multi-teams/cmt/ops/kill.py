"""cmt kill — tear down a pane and drop its state. Also kill --all."""

from __future__ import annotations

from pathlib import Path

from cmt import mux, state


def kill(name: str, state_dir: Path | None = None) -> None:
    """Kill agent ``name``. Idempotent on unknown name."""
    s = state.load(name, state_dir=state_dir)
    if s is None:
        return
    # Only close a pane that's actually live in THIS mux session. A stale state
    # file (cmux restarted → surface ids recycled, or a foreign/cross-backend
    # id) must not drive a blind close: cmux's close-surface falls back to the
    # focused surface — the user's main tab — when it can't resolve the id.
    # Drop the tracked state either way.
    if mux.pane_alive(s.pane_id):
        mux.kill_pane(s.pane_id)
    _cleanup_codex_home(s, state_dir)
    state.remove(name, state_dir=state_dir)


def _cleanup_codex_home(s: state.AgentState, state_dir: Path | None) -> None:
    """Remove a codex agent's per-agent CODEX_HOME scratch dir. Its entries are
    symlinks into the real home (rmtree drops the links, not the targets); only
    the private ``sessions/`` rollouts are real and they're no longer needed
    once the pane is gone. Best-effort."""
    if s.agent != "codex":
        return
    import shutil

    from cmt import codex_session

    sd = state_dir if state_dir is not None else state.default_dir()
    shutil.rmtree(codex_session.agent_home(sd, s.agent_id), ignore_errors=True)


def kill_all(state_dir: Path | None = None) -> None:
    """Kill every tracked agent."""
    for s in state.list_all(state_dir=state_dir):
        kill(s.name, state_dir=state_dir)

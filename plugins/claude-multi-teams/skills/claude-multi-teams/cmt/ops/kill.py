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
    state.remove(name, state_dir=state_dir)


def kill_all(state_dir: Path | None = None) -> None:
    """Kill every tracked agent."""
    for s in state.list_all(state_dir=state_dir):
        kill(s.name, state_dir=state_dir)

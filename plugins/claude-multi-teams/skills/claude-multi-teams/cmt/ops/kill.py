"""cmt kill — tear down a pane and drop its state. Also kill --all."""

from __future__ import annotations

from pathlib import Path

from cmt import mux, state


def kill(name: str, state_dir: Path | None = None) -> None:
    """Kill agent ``name``. Idempotent on unknown name."""
    s = state.load(name, state_dir=state_dir)
    if s is None:
        return
    mux.kill_pane(s.pane_id)
    state.remove(name, state_dir=state_dir)


def kill_all(state_dir: Path | None = None) -> None:
    """Kill every tracked agent."""
    for s in state.list_all(state_dir=state_dir):
        kill(s.name, state_dir=state_dir)

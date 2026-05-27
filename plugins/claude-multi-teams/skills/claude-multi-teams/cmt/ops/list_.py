"""cmt list — enumerate currently-tracked agents."""

from __future__ import annotations

from pathlib import Path

from cmt import state


def list_agents(state_dir: Path | None = None) -> list[state.AgentState]:
    return state.list_all(state_dir=state_dir)

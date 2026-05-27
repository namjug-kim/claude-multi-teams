"""cmt status — one-shot read of an agent's current status.

Returns ``"working" | "done" | "blocked" | "dead"``. Always callable —
returns ``"dead"`` for an unknown name (treat as "not currently alive").
"""

from __future__ import annotations

from pathlib import Path

from cmt import agents, mux, state, strategies


def status(name: str, state_dir: Path | None = None) -> strategies.AgentStatus:
    s = state.load(name, state_dir=state_dir)
    if s is None:
        return "dead"
    pane_alive = mux.pane_alive(s.pane_id)
    if s.session_file is None:
        # No session yet (codex pre-first-ask, or agy-style w/o jsonl) —
        # report based on pane liveness alone.
        return "done" if pane_alive else "dead"
    spec = agents.AGENTS.get(s.agent)
    if spec is None or spec.status_fn is None:
        # Unknown agent: degrade gracefully.
        return "done" if pane_alive else "dead"
    return spec.status_fn(
        Path(s.session_file),
        baseline_offset=s.baseline_offset,
        pane_alive=pane_alive,
    )

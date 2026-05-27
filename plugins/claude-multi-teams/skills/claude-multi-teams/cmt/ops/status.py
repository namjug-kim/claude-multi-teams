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
    spec = agents.AGENTS.get(s.agent)
    if spec is None or spec.status_fn is None:
        return "done" if pane_alive else "dead"
    # jsonl agents pre-first-ask have session_file=None; that's "done"
    # (no turn in progress). agy's status_fn handles the screen-only case.
    if s.session_file is None and spec.resolve_session_file is not None:
        # codex before first ask — no rollout yet
        return "done" if pane_alive else "dead"
    return spec.status_fn(s, pane_alive)

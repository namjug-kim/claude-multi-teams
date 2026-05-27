"""cmt status — one-shot read of an agent's current status.

Returns ``"working" | "done" | "blocked" | "dead"``. Always callable —
returns ``"dead"`` for an unknown name (treat as "not currently alive").
"""

from __future__ import annotations

from pathlib import Path

from cmt import mux, state, strategies


def status(name: str, state_dir: Path | None = None) -> strategies.AgentStatus:
    s = state.load(name, state_dir=state_dir)
    if s is None:
        return "dead"
    pane_alive = mux.pane_alive(s.pane_id)
    if s.session_file is None:
        # agy-style (no jsonl) — capture-pane strategy ships in a later slice.
        return "done" if pane_alive else "dead"
    return strategies.status_jsonl(
        Path(s.session_file),
        baseline_offset=s.baseline_offset,
        pane_alive=pane_alive,
    )

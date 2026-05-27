"""cmt ask — send a prompt, block until the agent's turn is done, return reply."""

from __future__ import annotations

import dataclasses
from pathlib import Path

from cmt import extract, mux, state, strategies


def ask(name: str, prompt: str, state_dir: Path | None = None) -> str:
    """Send ``prompt`` to agent ``name`` and return the assistant text.

    Raises ``FileNotFoundError`` if the agent isn't known, ``RuntimeError``
    if its pane is already dead or dies during the turn. No timeout — see
    CONTEXT.md "Liveness and timeouts".
    """
    s = state.load(name, state_dir=state_dir)
    if s is None:
        raise FileNotFoundError(f"agent {name!r} not found. spawn first.")

    if not mux.pane_alive(s.pane_id):
        raise RuntimeError(f"agent {name!r} pane {s.pane_id} is dead.")

    if s.session_file is None:
        # agy slice will replace this with capture-pane strategy; foundation
        # phase 1 covers claude only.
        raise NotImplementedError(
            f"agent {s.agent!r} has no jsonl session_file; "
            "capture-pane strategy not in this slice."
        )

    session_file = Path(s.session_file)
    baseline = session_file.stat().st_size if session_file.exists() else 0

    # Persist baseline BEFORE sending so `last-reply` and `status` can find
    # the start of this turn even if we crash mid-ask.
    state.save(dataclasses.replace(s, baseline_offset=baseline), state_dir=state_dir)

    mux.send_text(s.pane_id, prompt)

    result = strategies.await_jsonl_done(
        session_file,
        baseline_offset=baseline,
        is_alive=lambda: mux.pane_alive(s.pane_id),
    )
    if result == "dead":
        raise RuntimeError(f"agent {name!r} died during ask")

    return extract.extract_jsonl_assistant(session_file, baseline_offset=baseline)

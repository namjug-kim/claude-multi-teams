"""cmt ask — send a prompt, block until the agent's turn is done, return reply."""

from __future__ import annotations

import dataclasses
from pathlib import Path

from cmt import agents, mux, state


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

    spec = agents.AGENTS.get(s.agent)
    if spec is None or spec.await_done is None or spec.extract_response is None:
        raise NotImplementedError(
            f"agent {s.agent!r}: no jsonl/extract strategy registered "
            "(capture-pane strategy not in this slice)."
        )

    # Branch on whether the session file is already known. claude knows it
    # at spawn; codex resolves it on the first ask (after sending the prompt
    # so codex actually writes a rollout file).
    if s.session_file is None:
        if spec.resolve_session_file is None:
            raise NotImplementedError(
                f"agent {s.agent!r}: session_file is None and no resolver registered"
            )
        # codex path: send first, then wait for rollout file
        mux.send_text(s.pane_id, prompt)
        ctx = agents.SpawnContext(
            name=s.name, agent_id=s.agent_id, cwd=s.cwd, session_uuid="",
        )
        new_session = spec.resolve_session_file(ctx, s.spawn_marker)
        if new_session is None:
            raise RuntimeError(
                f"agent {s.agent!r} {name!r}: session file did not appear after first prompt"
            )
        s = dataclasses.replace(s, session_file=new_session, baseline_offset=0)
        state.save(s, state_dir=state_dir)
    else:
        session_file = Path(s.session_file)
        baseline = session_file.stat().st_size if session_file.exists() else 0
        s = dataclasses.replace(s, baseline_offset=baseline)
        # Persist baseline BEFORE sending so `last-reply` and `status` can find
        # the start of this turn even if we crash mid-ask.
        state.save(s, state_dir=state_dir)
        mux.send_text(s.pane_id, prompt)

    session_file = Path(s.session_file)
    result = spec.await_done(
        session_file,
        baseline_offset=s.baseline_offset,
        is_alive=lambda: mux.pane_alive(s.pane_id),
    )
    if result == "dead":
        raise RuntimeError(f"agent {name!r} died during ask")

    return spec.extract_response(session_file, baseline_offset=s.baseline_offset)

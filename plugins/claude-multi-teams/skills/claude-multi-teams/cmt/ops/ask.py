"""cmt ask — send a prompt, block until the agent's turn is done, return reply."""

from __future__ import annotations

import dataclasses
from pathlib import Path

from cmt import agents, mux, state


def ask(name: str, prompt: str, state_dir: Path | None = None) -> str:
    """Send ``prompt`` to agent ``name`` and return the assistant text.

    Three code paths, distinguished by whether the agent has a jsonl session
    file and whether that file is already known:

      - **jsonl, known** (claude after spawn, codex after first ask):
        update baseline_offset from current file size, send prompt, await
        done via jsonl tail.
      - **jsonl, unknown** (codex first ask): send prompt first (codex only
        writes a rollout file on user input), then call the spec's
        resolve_session_file to locate the new file.
      - **screen-based** (agy): session_file stays None forever; send prompt,
        await done via screen capture, extract from screen.

    Raises ``FileNotFoundError`` for an unknown name, ``RuntimeError`` if
    the pane is dead. No wall-clock timeout — see CONTEXT.md.
    """
    s = state.load(name, state_dir=state_dir)
    if s is None:
        raise FileNotFoundError(f"agent {name!r} not found. spawn first.")

    if not mux.pane_alive(s.pane_id):
        raise RuntimeError(f"agent {name!r} pane {s.pane_id} is dead.")

    spec = agents.AGENTS.get(s.agent)
    if spec is None or spec.await_done is None or spec.extract_response is None:
        raise NotImplementedError(
            f"agent {s.agent!r}: no done/extract strategy registered."
        )

    if s.session_file is None and spec.resolve_session_file is not None:
        # codex first-ask: prompt must hit the agent before the rollout file
        # appears. Then resolve, then persist.
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
    elif s.session_file is None:
        # Screen-based agent (agy): no session file, no baseline to maintain.
        mux.send_text(s.pane_id, prompt)
    else:
        # jsonl agent, known session file: bump baseline, then send.
        session_file = Path(s.session_file)
        baseline = session_file.stat().st_size if session_file.exists() else 0
        s = dataclasses.replace(s, baseline_offset=baseline)
        # Persist baseline BEFORE sending so `last-reply` and `status` can find
        # the start of this turn even if we crash mid-ask.
        state.save(s, state_dir=state_dir)
        mux.send_text(s.pane_id, prompt)

    result = spec.await_done(s, lambda: mux.pane_alive(s.pane_id))
    if result == "dead":
        raise RuntimeError(f"agent {name!r} died during ask")

    return spec.extract_response(s)

"""cmt ask — send a prompt, block until the agent's turn is done, return reply."""

from __future__ import annotations

import dataclasses
import time
from pathlib import Path

from cmt import agents, callchain, mux, state
from cmt.ops import status as status_op


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

    sd = state_dir if state_dir is not None else state.default_dir()
    callchain.acquire(name, sd)
    try:
        return _ask_inner(name, prompt, s, spec, state_dir)
    finally:
        callchain.release(name, sd)


def _ask_inner(name, prompt, s, spec, state_dir):
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

    _ensure_started(s, name, state_dir)

    result = spec.await_done(s, lambda: mux.pane_alive(s.pane_id))
    if result == "dead":
        raise RuntimeError(f"agent {name!r} died during ask")

    return spec.extract_response(s)


def _turn_started(s: "state.AgentState", name: str, state_dir) -> bool:
    """Whether the turn we just sent has actually begun in the agent.

    For jsonl agents the session file growing past the baseline captured at
    send time means the prompt was accepted (the user message was written).
    Screen agents (agy) have no baseline, so fall back to a ``working`` status.
    """
    if s.session_file is not None:
        try:
            return Path(s.session_file).stat().st_size > s.baseline_offset
        except FileNotFoundError:
            return False
    return status_op.status(name, state_dir=state_dir) == "working"


def _ensure_started(s, name, state_dir, max_resends: int = 3,
                    window: float = 5.0, poll: float = 0.4) -> None:
    """Confirm the prompt actually started a turn; re-press Enter if not.

    A bracketed paste followed immediately by Enter can race under parallel
    load: the Enter lands while the TUI is still ingesting the paste and gets
    swallowed, leaving the prompt composed-but-unsent. ``await_done`` would
    then block forever. Detect the stall and re-send Enter instead.
    """
    for attempt in range(max_resends + 1):
        waited = 0.0
        while waited < window:
            if not mux.pane_alive(s.pane_id):
                return  # let await_done surface 'dead'
            if _turn_started(s, name, state_dir):
                return
            time.sleep(poll)
            waited += poll
        if attempt < max_resends:
            mux.send_keys(s.pane_id, "Enter")
    raise RuntimeError(
        f"agent {name!r}: prompt never started a turn after {max_resends} "
        f"Enter resends — submit appears stuck"
    )

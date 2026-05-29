"""cmt kill — tear down a pane and drop its state. Also kill --all."""

from __future__ import annotations

import sys
from pathlib import Path

from cmt import mux, state


def kill(name: str, state_dir: Path | None = None) -> None:
    """Kill agent ``name``. Idempotent on unknown name.

    Refuses to close the pane cmt is running in: a persisted ``surface:N`` ref
    is a volatile index cmux can recycle onto an unrelated (or the orchestrator)
    pane, so a stale entry whose ref now matches the current pane must never be
    closed."""
    s = state.load(name, state_dir=state_dir)
    if s is None:
        return
    if s.pane_id == mux.current_pane():
        raise RuntimeError(
            f"refusing to kill {name!r}: its tracked pane {s.pane_id} is the "
            f"pane cmt is running in. A stale/recycled pane id can point here — "
            f"close the pane manually if this is really intended."
        )
    _teardown(s, state_dir)


def _teardown(s: state.AgentState, state_dir: Path | None) -> None:
    # Only close a pane that's actually live in THIS mux session. A stale state
    # file (cmux restarted → surface ids recycled, or a foreign/cross-backend
    # id) must not drive a blind close: cmux's close-surface falls back to the
    # focused surface — the user's main tab — when it can't resolve the id.
    if mux.pane_alive(s.pane_id):
        mux.kill_pane(s.pane_id)
    _cleanup_codex_home(s, state_dir)
    state.remove(s.name, state_dir=state_dir)


def _cleanup_codex_home(s: state.AgentState, state_dir: Path | None) -> None:
    """Remove a codex agent's per-agent CODEX_HOME scratch dir. Its entries are
    symlinks into the real home (rmtree drops the links, not the targets); only
    the private ``sessions/`` rollouts are real and they're no longer needed
    once the pane is gone. Best-effort."""
    if s.agent != "codex":
        return
    import shutil

    from cmt import codex_session

    sd = state_dir if state_dir is not None else state.default_dir()
    shutil.rmtree(codex_session.agent_home(sd, s.agent_id), ignore_errors=True)


def kill_all(state_dir: Path | None = None) -> None:
    """Kill every tracked agent, but never the pane cmt is running in.

    The current pane is skipped (left tracked) rather than aborting the whole
    sweep — a single stale/recycled entry matching the orchestrator pane must
    not take down the orchestrator, and must not block tearing down the rest."""
    current = mux.current_pane()
    skipped: list[str] = []
    for s in state.list_all(state_dir=state_dir):
        if s.pane_id == current:
            skipped.append(s.name)
            continue
        _teardown(s, state_dir)
    if skipped:
        print(
            f"cmt kill --all: skipped {', '.join(skipped)} — tracked pane is the "
            f"current pane (possible stale/recycled id); not closing it.",
            file=sys.stderr,
        )

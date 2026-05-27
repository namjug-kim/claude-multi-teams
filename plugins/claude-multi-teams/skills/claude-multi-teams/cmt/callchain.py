"""Cycle prevention and per-target mutex for ``cmt ask``.

The wait-for graph of nested ``cmt ask`` calls forms a tree as long as no
target appears twice in the chain leading to it. We track that chain in
``$STATE_DIR/.calls/<target>.json`` while the call is in flight and:

  - **Atomic create** (O_CREAT | O_EXCL) gives a per-target mutex — only
    one outstanding ``cmt ask`` against a given agent at a time.
  - **The contents** of that file are the chain leading up to the call,
    so any nested ``cmt ask`` from inside the target's pane can read
    its own chain and detect a cycle before issuing a new call.

If ``CMT_AGENT_ID`` is set, the calling code is running inside a spawned
pane and we treat that agent as the immediate caller. Otherwise the
caller is the orchestrator (no name needed; chain starts empty).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from cmt import state

DEFAULT_MAX_DEPTH = 6  # generous; cycle-prevention is the primary guard


def _calls_dir(state_dir: Path) -> Path:
    return state_dir / ".calls"


def _chain_for(state_dir: Path, name: str) -> list[str]:
    """The chain that led to ``name`` being called — empty if not in-flight."""
    p = _calls_dir(state_dir) / f"{name}.json"
    if not p.exists():
        return []
    try:
        return list(json.loads(p.read_text()))
    except (json.JSONDecodeError, OSError):
        return []


def _caller_name(state_dir: Path) -> str | None:
    """The name of the agent whose pane this ``cmt`` invocation is running in,
    or ``None`` if invoked from outside any pane (orchestrator)."""
    agent_id = os.environ.get("CMT_AGENT_ID")
    if not agent_id:
        return None
    s = state.find_by_agent_id(agent_id, state_dir=state_dir)
    return s.name if s is not None else None


class CycleDetected(RuntimeError):
    """Raised when ``cmt ask <target>`` would re-enter an agent already in
    the calling chain. Stops the call before it touches the target's pane."""


class TargetBusy(RuntimeError):
    """Raised when a ``cmt ask`` against ``<target>`` is already in flight
    from somewhere else. Prevents parallel asks to the same agent that
    would otherwise interleave on the same pane."""


class DepthExceeded(RuntimeError):
    """Raised when the chain length would exceed ``max_depth``."""


def acquire(
    target: str,
    state_dir: Path,
    max_depth: int = DEFAULT_MAX_DEPTH,
) -> list[str]:
    """Validate the call to ``target`` is safe, mark it in flight, and return
    the new chain that should be visible to any nested calls.

    Raises ``CycleDetected``, ``TargetBusy``, or ``DepthExceeded`` if the
    call is unsafe. Pair every successful call with :func:`release`.
    """
    caller = _caller_name(state_dir)
    chain = _chain_for(state_dir, caller) if caller else []

    if target in chain or target == caller:
        full = chain + [target]
        raise CycleDetected(
            f"cycle: call chain {full} would re-enter {target!r}"
        )

    new_chain = chain + [target]
    if len(new_chain) > max_depth:
        raise DepthExceeded(
            f"call depth {len(new_chain)} exceeds max {max_depth}: {new_chain}"
        )

    calls = _calls_dir(state_dir)
    calls.mkdir(parents=True, exist_ok=True)
    path = calls / f"{target}.json"
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        existing = _chain_for(state_dir, target)
        raise TargetBusy(
            f"target {target!r} is already being called (in-flight chain: {existing})"
        )
    try:
        os.write(fd, json.dumps(new_chain).encode())
    finally:
        os.close(fd)
    return new_chain


def release(target: str, state_dir: Path) -> None:
    """Clear the in-flight marker for ``target``. Idempotent."""
    p = _calls_dir(state_dir) / f"{target}.json"
    try:
        p.unlink()
    except FileNotFoundError:
        pass

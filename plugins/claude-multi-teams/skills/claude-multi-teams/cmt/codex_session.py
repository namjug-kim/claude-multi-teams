"""Codex rollout file discovery.

Codex creates ``$CODEX_HOME/sessions/YYYY/MM/DD/rollout-<iso>-<uuid>.jsonl``
only after the first user prompt. The cmt foundation needs to:

  1. Snapshot the sessions root's max-mtime at spawn time (``spawn_marker``).
  2. After the first prompt, scan for files newer than that snapshot and
     pick the newest — that's the spawned codex's rollout file.

Both functions are pure (operate on paths). ``sessions_root`` reads env once
to find the default base; tests pass tmp paths directly to the others.
"""

from __future__ import annotations

import os
import time
from pathlib import Path


def sessions_root() -> Path:
    """Resolve the codex sessions root, honoring ``$CODEX_HOME`` if set.
    Default: ``~/.codex/sessions``."""
    base = os.environ.get("CODEX_HOME")
    if base:
        return Path(base) / "sessions"
    return Path(os.environ.get("HOME", "/")) / ".codex" / "sessions"


def snapshot_max_mtime(root: Path) -> float:
    """Return the max mtime (as float seconds since epoch) of all rollout
    files currently under ``root``. Returns ``0.0`` if the dir doesn't exist
    or holds no rollouts."""
    if not root.exists():
        return 0.0
    best = 0.0
    for p in root.rglob("rollout-*.jsonl"):
        try:
            mt = p.stat().st_mtime
        except FileNotFoundError:
            continue
        if mt > best:
            best = mt
    return best


def find_new_rollout(root: Path, after: float) -> Path | None:
    """Return the newest rollout under ``root`` with mtime strictly greater
    than ``after``. Returns ``None`` if no such file exists.

    One-shot. Use ``wait_for_new_rollout`` if you need to block for a file
    to appear."""
    if not root.exists():
        return None
    candidates: list[tuple[float, Path]] = []
    for p in root.rglob("rollout-*.jsonl"):
        try:
            mt = p.stat().st_mtime
        except FileNotFoundError:
            continue
        if mt > after:
            candidates.append((mt, p))
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][1]


def wait_for_new_rollout(
    root: Path,
    after: float,
    timeout: float,
    poll_interval: float = 0.1,
) -> Path | None:
    """Block until a rollout newer than ``after`` appears, or ``timeout``
    seconds elapse. Returns the path or ``None`` on timeout."""
    deadline = time.monotonic() + timeout
    while True:
        found = find_new_rollout(root, after=after)
        if found is not None:
            return found
        if time.monotonic() >= deadline:
            return None
        time.sleep(poll_interval)

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
    return source_home() / "sessions"


def source_home() -> Path:
    """The real codex home to mirror into each agent's private home —
    honoring ``$CODEX_HOME`` if set, else ``~/.codex``."""
    base = os.environ.get("CODEX_HOME")
    if base:
        return Path(base)
    return Path(os.environ.get("HOME", "/")) / ".codex"


def agent_home(state_dir: Path, agent_id: str) -> Path:
    """Per-agent private ``CODEX_HOME`` under the cmt state dir.

    Isolating each codex's sessions tree here is what stops concurrent
    first-asks from resolving to each other's rollout file: with a shared
    ``$CODEX_HOME/sessions`` root, discovery ("newest rollout after the spawn
    marker") cannot tell sibling rollouts apart and several agents bind to the
    same file — byte-identical / cross-wired replies. A private root makes the
    one rollout that appears unambiguous. Derived purely from
    ``(state_dir, agent_id)`` so spawn and the first ask agree without storing
    extra state."""
    return state_dir / "codex-home" / agent_id


def seed_agent_home(home: Path, source: Path) -> None:
    """Make ``home`` behave like ``source`` but with a private ``sessions/``.

    Symlinks every top-level entry of ``source`` into ``home`` so codex finds
    the same auth, config, skills, hooks, rules, etc. — EXCEPT ``sessions``,
    which becomes a real empty dir owned by this agent. That single carve-out
    is the whole isolation; everything else stays shared exactly as it was
    under one ``$CODEX_HOME``, so behavior is unchanged. Idempotent: existing
    links/dirs are left as-is."""
    home.mkdir(parents=True, exist_ok=True)
    if source.exists():
        for entry in source.iterdir():
            if entry.name == "sessions":
                continue
            link = home / entry.name
            if link.exists() or link.is_symlink():
                continue
            link.symlink_to(entry)
    (home / "sessions").mkdir(parents=True, exist_ok=True)


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

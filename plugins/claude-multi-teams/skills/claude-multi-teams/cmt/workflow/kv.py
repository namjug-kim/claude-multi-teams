"""Shared key-value store under ``$CMT_STATE_DIR/kv/<key>``.

The world-state snapshot a workflow reads and writes: "what is true now?".
One value per key, last write wins. Keys may contain ``/`` to namespace
(``feature/17/status``); the store maps them onto nested directories.

No compare-and-set in the MVP — a single blocking orchestrator has no
concurrent writers. CAS is a deferred concern (see SPEC 1b).
"""

from __future__ import annotations

import re
from pathlib import Path

from cmt import state

_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_/-]*$")


def _validate_key(key: str) -> None:
    if not _KEY_RE.match(key) or ".." in key or key.endswith("/"):
        raise ValueError(
            f"invalid kv key {key!r}: must match [a-z0-9][a-z0-9_/-]* "
            f"(slashes namespace; no '..', no trailing '/')"
        )


def _kv_dir(state_dir: Path | None) -> Path:
    return (state_dir or state.default_dir()) / "kv"


def _path(key: str, state_dir: Path | None) -> Path:
    return _kv_dir(state_dir) / key


def put(key: str, value: str, state_dir: Path | None = None) -> None:
    _validate_key(key)
    p = _path(key, state_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(value)
    tmp.replace(p)


def get(key: str, state_dir: Path | None = None) -> str | None:
    _validate_key(key)
    p = _path(key, state_dir)
    if not p.exists():
        return None
    return p.read_text()

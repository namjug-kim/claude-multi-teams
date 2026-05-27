"""cmt keys — send an arbitrary key sequence to a pane."""

from __future__ import annotations

from pathlib import Path

from cmt import mux, state


def keys(name: str, keys: list[str], state_dir: Path | None = None) -> None:
    s = state.load(name, state_dir=state_dir)
    if s is None:
        raise FileNotFoundError(f"agent {name!r} not found.")
    mux.send_keys(s.pane_id, *keys)

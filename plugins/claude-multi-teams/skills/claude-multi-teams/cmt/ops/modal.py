"""cmt modal — inspect a startup selection modal blocking a pane.

Read-only: parses the live screen and reports the modal (title / options /
highlighted row / footer) if one is present. Answer it by composing with the
existing ``keys`` primitive, e.g. ``cmt keys <name> 2 Enter`` to pick option 2.
"""

from __future__ import annotations

from pathlib import Path

from cmt import modal as _modal, mux, state


def inspect(name: str, state_dir: Path | None = None) -> _modal.Modal | None:
    s = state.load(name, state_dir=state_dir)
    if s is None:
        raise FileNotFoundError(f"agent {name!r} not found.")
    return _modal.detect(mux.capture(s.pane_id, mode="full"))

"""cmt capture — read pane screen text."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from cmt import mux, state


def capture(name: str, mode: Literal["visible", "full", "wrapped"] = "full",
            state_dir: Path | None = None) -> str:
    s = state.load(name, state_dir=state_dir)
    if s is None:
        raise FileNotFoundError(f"agent {name!r} not found.")
    return mux.capture(s.pane_id, mode=mode)

"""cmt send — paste text into a pane (default with Enter)."""

from __future__ import annotations

from pathlib import Path

from cmt import mux, state


def send(name: str, text: str, enter: bool = True, state_dir: Path | None = None) -> None:
    s = state.load(name, state_dir=state_dir)
    if s is None:
        raise FileNotFoundError(f"agent {name!r} not found.")
    if enter:
        mux.send_text(s.pane_id, text)
    else:
        mux.paste_bracketed(s.pane_id, text)

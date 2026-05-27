"""cmt wait-output — block until pane text matches a regex/substring."""

from __future__ import annotations

import re
import time
from pathlib import Path

from cmt import mux, state


def wait_output(
    name: str,
    pattern: str,
    as_text: bool = False,
    state_dir: Path | None = None,
    poll_interval: float = 0.5,
) -> bool:
    """Block until the pane's full-scrollback capture matches ``pattern``.

    ``as_text=True``  → literal substring match.
    ``as_text=False`` → ``re.search`` over the captured text.

    Returns ``True`` on match, ``False`` if the pane dies first. No wall-clock
    timeout — wrap with shell ``timeout`` if needed.
    """
    s = state.load(name, state_dir=state_dir)
    if s is None:
        raise FileNotFoundError(f"agent {name!r} not found.")
    matcher = (lambda text: pattern in text) if as_text else (
        lambda text, _re=re.compile(pattern): bool(_re.search(text))
    )
    while True:
        if not mux.pane_alive(s.pane_id):
            return False
        screen = mux.capture(s.pane_id)
        if matcher(screen):
            return True
        time.sleep(poll_interval)

"""Post-spawn warmup state machine for codex.

After ``codex`` launches with the bypass flags, it may still present a
"Do you trust the contents of this directory?" modal (Trust folder). The
machine polls the pane's screen capture, dismisses any known modal it sees,
and returns once the codex banner appears.

Modals are matched by a short marker substring (resilient to ANSI/box-drawing
chars around the prompt text). Each modal pattern records one "key sequence
to send" once per occurrence so a slow re-render doesn't double-fire keys.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

# Marker that proves codex's TUI banner has rendered.
BANNER_MARKER = "OpenAI Codex"

# Trust-folder modal (1. Yes, continue is default → just Enter).
TRUST_MODAL_MARKER = "Do you trust the contents of this directory?"


@dataclass(frozen=True)
class _Modal:
    key: str          # internal identifier (to avoid re-sending for same modal)
    marker: str       # substring matched in screen capture
    keys: tuple[str, ...]  # tmux/mux key sequence to dismiss


_MODALS: tuple[_Modal, ...] = (
    _Modal(key="trust", marker=TRUST_MODAL_MARKER, keys=("Enter",)),
    # If Update / Hooks ever surface despite flags, add them here. Each modal
    # gets one key-send per occurrence; re-occurrence (same marker again later)
    # would re-send. Within one polling burst, the ``handled`` set suppresses
    # repeats while the screen is still showing the same modal.
)


def run_codex_warmup(
    capture: Callable[[], str],
    send_key: Callable[[str], None],
    deadline_s: float = 10.0,
    poll_interval: float = 0.3,
) -> None:
    """Poll ``capture()`` until ``BANNER_MARKER`` is on screen. Dismiss
    any known modal seen along the way by sending its keys via ``send_key``.

    Raises ``TimeoutError`` if the banner never appears within ``deadline_s``.
    """
    deadline = time.monotonic() + deadline_s
    handled: set[str] = set()
    while True:
        screen = capture()
        if BANNER_MARKER in screen:
            return
        for modal in _MODALS:
            if modal.marker in screen:
                if modal.key not in handled:
                    for key in modal.keys:
                        send_key(key)
                    handled.add(modal.key)
                break
        else:
            # No known modal on screen and no banner yet — clear the handled
            # set so a *new* occurrence of the same modal later would fire again.
            # (Without this, a second Trust modal in a row couldn't be dismissed.)
            handled.clear()

        if time.monotonic() >= deadline:
            raise TimeoutError(
                f"codex warmup: did not see {BANNER_MARKER!r} within {deadline_s}s"
            )
        time.sleep(poll_interval)

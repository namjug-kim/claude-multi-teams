"""Post-spawn warmup state machine for agy (Antigravity CLI).

Like codex, agy may show a Trust-folder modal before reaching its idle TUI.
The machine polls the pane's screen, dismisses any known modal it sees, and
returns once the bottom status line shows ``? for shortcuts`` — which is the
authoritative "agy is ready to accept paste" signal. The banner text appears
~4 seconds *before* the input area is ready, so we deliberately do NOT use
banner presence as the ready signal.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

from cmt.agy_screen import STATUS_DONE_MARKER, SURVEY_DISMISS_KEYS, SURVEY_MARKER

# Trust-folder modal: "Do you trust the contents of this project?"
# Default selection is "Yes, I trust this folder" — just press Enter.
TRUST_MODAL_MARKER = "Do you trust the contents of this project?"


@dataclass(frozen=True)
class _Modal:
    key: str
    marker: str
    keys: tuple[str, ...]


_MODALS: tuple[_Modal, ...] = (
    _Modal(key="trust", marker=TRUST_MODAL_MARKER, keys=("Enter",)),
    _Modal(key="survey", marker=SURVEY_MARKER, keys=SURVEY_DISMISS_KEYS),
)


def run_agy_warmup(
    capture: Callable[[], str],
    send_key: Callable[[str], None],
    deadline_s: float = 15.0,
    poll_interval: float = 0.5,
) -> None:
    """Poll capture() until ``? for shortcuts`` is on screen, dismissing any
    modal we see along the way. Raises TimeoutError if the marker never
    appears within deadline_s.
    """
    deadline = time.monotonic() + deadline_s
    handled: set[str] = set()
    while True:
        screen = capture()
        if STATUS_DONE_MARKER in screen:
            return
        matched = False
        for modal in _MODALS:
            if modal.marker in screen:
                matched = True
                if modal.key not in handled:
                    for key in modal.keys:
                        send_key(key)
                    handled.add(modal.key)
                break
        if not matched:
            handled.clear()
        if time.monotonic() >= deadline:
            raise TimeoutError(
                f"agy warmup: did not see {STATUS_DONE_MARKER!r} within {deadline_s}s"
            )
        time.sleep(poll_interval)

"""Post-spawn warmup state machine for codex.

After ``codex`` launches, it may stack several startup modals before the TUI
banner renders — Trust folder, "Update available!", "Hooks need review", … —
even with the bypass flags. The machine polls the pane, recognizes any numbered
selection modal (via :mod:`cmt.modal`, by *structure* not exact wording), picks
a safe option by content, and returns once the codex banner appears.

Why content-based picks (not a fixed key): codex highlights the *dangerous* row
by default — pressing Enter blindly would run "Update now" (blocks on npm) or
"Review hooks" (opens a sub-UI). We instead choose the option whose label says
"Skip" / "Trust all" / "Yes, continue".

Why an adaptive digit→Enter (not one fixed sequence): we don't assume whether a
digit press merely highlights a row or also confirms it. We send the digit, then
on the next poll either (a) the modal is gone — the digit confirmed, so we send
nothing more — or (b) it's still up — so we send Enter to confirm. This way a
stray Enter never lands on the *next* modal's dangerous default.
"""

from __future__ import annotations

import os
import time
from typing import Callable

from cmt import modal as _modal

# Marker that proves codex's TUI banner has rendered.
BANNER_MARKER = "OpenAI Codex"
# Matched against the whitespace-collapsed screen so a banner wrapped by a
# narrow pane still counts.
_BANNER_SQUASHED = "".join(BANNER_MARKER.split())

# Ordered option-label substrings to pick, by preference. For a detected modal
# we choose the first option whose label contains one of these. Extend as new
# modals appear — no need to encode each modal's full text.
_PICK_SUBSTRINGS: tuple[str, ...] = (
    "Yes, continue",   # Trust folder       → accept the directory
    "Skip",            # Update available!  → don't run npm install
    "Trust all",       # Hooks need review  → trust + continue (matches --dangerously-bypass-hook-trust)
)


def run_codex_warmup(
    capture: Callable[[], str],
    send_key: Callable[[str], None],
    # Default (when None): $CMT_CODEX_WARMUP_DEADLINE or 60s. 60s, not 20: with
    # several codex spawning at once (plus image-gen load on the same box) the
    # banner routinely takes >20s to render — 2026-06-11 saw 3 of 4 parallel
    # spawns die at 20s. A heavy-load caller (e.g. a warm-pool driver) can raise
    # it via the env var. The deadline is only an upper bound; a healthy pane
    # still returns as soon as the banner appears.
    deadline_s: float | None = None,
    poll_interval: float = 0.3,
) -> None:
    """Poll ``capture()`` until ``BANNER_MARKER`` is on screen, answering any
    known selection modal seen along the way.

    Raises ``TimeoutError`` if the banner never appears within ``deadline_s``;
    the message includes the last modal seen, for diagnosis.
    """
    if deadline_s is None:
        deadline_s = float(os.environ.get("CMT_CODEX_WARMUP_DEADLINE", "60") or "60")
    deadline = time.monotonic() + deadline_s
    # Per modal-occurrence progress: options-tuple -> "digit" | "done".
    progress: dict[tuple[str, ...], str] = {}
    last_modal: _modal.Modal | None = None

    while True:
        screen = capture()

        # Answer a live selection modal *before* trusting the banner. codex
        # prints its "OpenAI Codex" banner and only then runs the async update
        # check, so a blocking "Update available!" modal routinely sits on
        # screen with the banner already in the (full-history) capture.
        # Returning on the banner here would strand that modal — the agent hangs
        # on "Press enter to continue". So while a modal we can pick is still
        # being dismissed (busy), we keep working it and ignore the banner.
        m = _modal.detect(screen)
        busy = False
        if m is not None:
            last_modal = m
            choice = _pick(m)
            if choice is not None:
                _advance(m, choice, progress, send_key)
                # Still mid-dismissal until the option is confirmed ("done").
                # A "done" modal lingering in scrollback no longer blocks the
                # banner, so warmup can finish.
                busy = progress.get(m.options) != "done"
        else:
            # No modal on screen — reset so a fresh occurrence fires again.
            progress.clear()

        # Whitespace-collapsed match: in a narrow pane the banner wraps
        # ("OpenAI Cod\nex"), so a literal substring test never fires even
        # though codex is up.
        if not busy and _BANNER_SQUASHED in "".join(screen.split()):
            return

        if time.monotonic() >= deadline:
            detail = f" last modal options={last_modal.options}" if last_modal else ""
            raise TimeoutError(
                f"codex warmup: did not see {BANNER_MARKER!r} within {deadline_s}s.{detail}"
            )
        time.sleep(poll_interval)


def _pick(m: _modal.Modal) -> int | None:
    for needle in _PICK_SUBSTRINGS:
        i = m.index_of(needle)
        if i is not None:
            return i
    return None


def _advance(
    m: _modal.Modal,
    choice: int,
    progress: dict[tuple[str, ...], str],
    send_key: Callable[[str], None],
) -> None:
    """Move one step toward selecting ``choice`` for modal ``m``, without
    re-pressing keys on render lag. Sends the digit first; only confirms with
    Enter once the digit has taken effect (highlight on ``choice``) or the
    highlight can't be read at all."""
    sig = m.options
    phase = progress.get(sig)
    if phase is None:
        send_key(str(choice))
        progress[sig] = "digit"
    elif phase == "digit":
        if m.highlighted in (choice, None):
            send_key("Enter")
            progress[sig] = "done"
        else:
            # Digit didn't register (highlight elsewhere) — retry the digit.
            send_key(str(choice))
    # phase == "done": fully answered; wait for the screen to advance.

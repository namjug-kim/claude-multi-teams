"""Tests for agy screen-based detection + extraction.

agy has no jsonl session file (.pb files are opaque binaries and don't persist
for short sessions), so done detection and response extraction both work off
``capture-pane`` text:

  - **Status line** at the bottom of the screen carries the marker:
      ``esc to cancel``    → working (a turn is in progress)
      ``? for shortcuts``  → done (idle, ready for next prompt)
  - **Response** appears in the scrollback as a block bracketed by
    ``─{40,}`` divider lines, with the user prompt on a ``> <text>`` line and
    the model's reply rendered as subsequent lines (2-space indented).
"""

from __future__ import annotations

import threading
import time

from cmt.agy_screen import (
    STATUS_DONE_MARKER,
    STATUS_WORKING_MARKER,
    status_from_screen,
    extract_response,
    await_done,
)


def _idle_screen(reply_block: str = "") -> str:
    """Build a screen capture that ends in the idle-status state."""
    divider = "─" * 60
    blocks = []
    if reply_block:
        blocks.append(divider)
        blocks.append(reply_block)
    blocks += [
        divider,
        ">",
        divider,
        f"{STATUS_DONE_MARKER}                                    Gemini",
    ]
    return "\n".join(blocks)


def _working_screen() -> str:
    return "\n".join([
        "> Reply with one word: APPLE",
        "⣟ Generating...",
        "─" * 60,
        ">",
        "─" * 60,
        f"{STATUS_WORKING_MARKER}                                  Gemini",
    ])


def test_status_done_when_marker_present() -> None:
    assert status_from_screen(_idle_screen(), pane_alive=True) == "done"


def test_status_working_when_marker_present() -> None:
    assert status_from_screen(_working_screen(), pane_alive=True) == "working"


def test_status_dead_when_pane_gone() -> None:
    assert status_from_screen(_idle_screen(), pane_alive=False) == "dead"


def test_status_done_when_no_marker_but_pane_alive() -> None:
    # Conservative: unknown TUI state with live pane → assume done (not
    # working). working requires a positive signal.
    assert status_from_screen("just some text", pane_alive=True) == "done"


def test_extract_returns_text_of_last_prompt_block() -> None:
    screen = _idle_screen(reply_block="> Reply with one word: APPLE\n\n  APPLE")
    assert extract_response(screen) == "APPLE"


def test_extract_multi_line_response() -> None:
    block = "> List three\n\n  one\n  two\n  three"
    assert extract_response(_idle_screen(reply_block=block)) == "one\ntwo\nthree"


def test_extract_picks_LAST_block_when_multiple() -> None:
    divider = "─" * 60
    screen = "\n".join([
        divider,
        "> first prompt",
        "",
        "  first reply",
        divider,
        "> second prompt",
        "",
        "  second reply",
        divider,
        ">",
        divider,
        STATUS_DONE_MARKER,
    ])
    assert extract_response(screen) == "second reply"


def test_extract_returns_empty_when_no_response_block() -> None:
    # Fresh idle agy with empty prompt area
    assert extract_response(_idle_screen()) == ""


def test_extract_strips_box_drawing_artifacts() -> None:
    # The visible '>' line may be preceded by ANSI / box drawing; the parser
    # should still find a line that begins with literal '>' followed by space.
    block = "> ping\n\n  pong"
    assert extract_response(_idle_screen(reply_block=block)) == "pong"


def test_await_done_returns_done_when_status_already_done() -> None:
    screens = iter([_idle_screen()])
    result = await_done(
        capture=lambda: next(screens, _idle_screen()),
        is_alive=lambda: True,
        poll_interval=0.01,
    )
    assert result == "done"


def test_await_done_blocks_until_status_flips() -> None:
    state = {"phase": "working"}

    def cap():
        if state["phase"] == "working":
            return _working_screen()
        return _idle_screen()

    def flip():
        time.sleep(0.2)
        state["phase"] = "done"

    t = threading.Thread(target=flip)
    t.start()
    result = await_done(capture=cap, is_alive=lambda: True, poll_interval=0.05)
    t.join()
    assert result == "done"


def test_await_done_returns_dead_when_is_alive_false() -> None:
    n = {"i": 0}

    def alive():
        n["i"] += 1
        return n["i"] < 3

    result = await_done(
        capture=lambda: _working_screen(),
        is_alive=alive,
        poll_interval=0.05,
    )
    assert result == "dead"

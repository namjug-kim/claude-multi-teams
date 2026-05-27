"""Screen-based detection + extraction for the agy agent.

Why screen, not jsonl: agy persists its conversation in opaque ``.pb`` files
that don't appear for short sessions, so the only reliable channel is the
pane's rendered output. We detect turn state from the bottom status line
and parse responses out of the scrollback.

Markers verified against agy 1.0.2 (Antigravity CLI):
- ``? for shortcuts``  — idle / done
- ``esc to cancel``    — a turn is in progress (also paired with a spinner)
"""

from __future__ import annotations

import re
import time
from typing import Callable

from cmt.strategies import AgentStatus, AskResult

STATUS_DONE_MARKER = "? for shortcuts"
STATUS_WORKING_MARKER = "esc to cancel"

# A line consisting only of ─ (or - fallback) characters marks a turn
# boundary. agy renders this divider at the pane's visible width, so the
# length varies — narrow side-pane surfaces show only ~18 chars, full-width
# panes show 150+. The threshold (5) is high enough to skip ordinary content
# like ``---`` separators in markdown while still catching the narrowest
# real-world divider observed.
_DIVIDER = re.compile(r"^[─\-]{5,}\s*$")
# A "> <something non-blank>" line in scrollback is a rendered user prompt.
# Pure ">" with no content after is the current input area and should be ignored.
_PROMPT_LINE = re.compile(r"^>\s+\S")


def status_from_screen(screen: str, pane_alive: bool) -> AgentStatus:
    """Map a screen capture + pane liveness to one of the 4-state values.

    ``working`` requires a positive ``esc to cancel`` signal. Otherwise an
    alive pane is reported as ``done`` (no false-positive "working" when the
    TUI is in a weird state). ``dead`` wins over any screen content."""
    if not pane_alive:
        return "dead"
    if STATUS_WORKING_MARKER in screen:
        return "working"
    return "done"


def extract_response(screen: str) -> str:
    """Return the response text of the most recent rendered ``> <prompt>``
    block in ``screen``. Blocks are bracketed by ``─{5,}`` divider lines.

    Layout inside a block (narrow and wide panes are the same shape, just
    different widths):

        > <first prompt line>
          <prompt continuation lines, indented 2sp on wrap>
                                    ← single blank line separates prompt and
                                      response
          <response lines, indented 2sp>
                                    ← trailing blank before the divider

    We find the latest ``> <text>`` line in scrollback, collect everything
    until the next divider, then take the segment *after* the first blank
    line. The leading 2-space indent is stripped; surrounding blank lines
    are trimmed. Returns "" if no usable block is found.
    """
    lines = screen.splitlines()
    last_prompt_idx = -1
    for i, line in enumerate(lines):
        if _PROMPT_LINE.match(line):
            last_prompt_idx = i
    if last_prompt_idx < 0:
        return ""

    block: list[str] = []
    for line in lines[last_prompt_idx + 1:]:
        if _DIVIDER.match(line):
            break
        block.append(line)

    # Find the first blank line — that's the prompt/response boundary.
    first_blank = -1
    for i, line in enumerate(block):
        if not line.strip():
            first_blank = i
            break
    body = block[first_blank + 1:] if first_blank >= 0 else block

    stripped = [(line[2:] if line.startswith("  ") else line) for line in body]
    while stripped and not stripped[0].strip():
        stripped.pop(0)
    while stripped and not stripped[-1].strip():
        stripped.pop()
    return "\n".join(stripped)


def await_done(
    capture: Callable[[], str],
    is_alive: Callable[[], bool],
    poll_interval: float = 0.5,
) -> AskResult:
    """Poll ``capture()`` until the bottom status line shows
    ``? for shortcuts`` (idle). Returns ``"done"`` or ``"dead"``.

    No wall-clock timeout (mirrors the jsonl strategy contract)."""
    while True:
        if not is_alive():
            return "dead"
        screen = capture()
        if STATUS_DONE_MARKER in screen and STATUS_WORKING_MARKER not in screen:
            return "done"
        time.sleep(poll_interval)

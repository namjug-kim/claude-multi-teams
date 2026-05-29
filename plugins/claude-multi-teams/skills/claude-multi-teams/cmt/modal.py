"""Detect and answer startup selection modals (codex / agy / claude).

These CLIs interrupt boot with numbered single-choice modals — Trust folder,
"Update available!", "Hooks need review", … — that all share one structure:

    <title / question line>
    <optional description / release-notes lines>

    › 1. <option label>     # '›' / '>' / '❯' marks the highlighted row
      2. <option label>
      3. <option label>

    Press enter to <continue | confirm>

``detect`` parses that structure from a screen capture so callers can *see*
what is blocking (title + options + which row is highlighted) and pick a row
by content — without hard-coding every modal's exact wording. New modals that
follow the same shape are recognized for free.

Selection is digit-then-Enter (``select_keys``) — the convention this codebase
already uses for agy's survey dismissal. Pressing the option's digit moves the
highlight; Enter confirms it. Picking the digit explicitly (rather than relying
on the default) matters because codex highlights the *dangerous* row by default
("Update now", "Review hooks").
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# A numbered option row: optional highlight glyph, an index, a dot, a label.
_OPTION_RE = re.compile(r"^\s*([›>❯▌●]?)\s*(\d+)\.\s+(\S.*?)\s*$")
# Lines we never want to mistake for a title.
_FOOTER_RE = re.compile(r"[Pp]ress enter")
_URL_RE = re.compile(r"https?://")
# How many lines above the first option to scan for a title.
_TITLE_WINDOW = 12


@dataclass(frozen=True)
class Modal:
    title: str                 # best-effort question / title text ("" if unknown)
    options: tuple[str, ...]   # option labels in order; option N == options[N-1]
    highlighted: int | None    # 1-based index of the marked row, if detectable
    footer: str                # the "Press enter to …" line, if present

    def index_of(self, needle: str) -> int | None:
        """1-based number of the first option whose label contains ``needle``
        (case-insensitive), or None."""
        low = needle.lower()
        for i, opt in enumerate(self.options, start=1):
            if low in opt.lower():
                return i
        return None

    def render(self) -> str:
        lines = [self.title or "(modal)"]
        for i, opt in enumerate(self.options, start=1):
            mark = "›" if i == self.highlighted else " "
            lines.append(f"{mark} {i}. {opt}")
        if self.footer:
            lines.append(self.footer)
        return "\n".join(lines)


def detect(screen: str) -> Modal | None:
    """Parse a numbered selection modal from ``screen``.

    Returns None unless the screen contains a contiguous ``1. … 2. …`` option
    list of at least two rows (so a stray "1." in prose is never a modal).
    """
    lines = screen.splitlines()
    options: list[str] = []
    highlighted: int | None = None
    first_opt_line: int | None = None
    expected = 1
    for idx, line in enumerate(lines):
        m = _OPTION_RE.match(line)
        if m is None:
            continue
        glyph, num, label = m.group(1), int(m.group(2)), m.group(3)
        if num != expected:
            # Not the next row of a contiguous list — ignore (e.g. a "1." that
            # restarts mid-prose, or the version "0.135.0" lookalikes).
            continue
        if first_opt_line is None:
            first_opt_line = idx
        options.append(label)
        if glyph:
            highlighted = num
        expected += 1

    if len(options) < 2 or first_opt_line is None:
        return None

    title = _find_title(lines, first_opt_line)
    footer = _find_footer(lines, first_opt_line + len(options))
    return Modal(title=title, options=tuple(options), highlighted=highlighted, footer=footer)


def select_keys(option_number: int) -> tuple[str, ...]:
    """Key sequence to choose option ``option_number``: press its digit to move
    the highlight, then Enter to confirm."""
    return (str(option_number), "Enter")


def _find_title(lines: list[str], first_opt_line: int) -> str:
    # Walk upward from the options; the question/title is the nearest line that
    # isn't a URL, footer, or box-drawing filler.
    start = max(0, first_opt_line - _TITLE_WINDOW)
    for line in reversed(lines[start:first_opt_line]):
        text = line.strip()
        if not text or _URL_RE.search(text) or _FOOTER_RE.search(text):
            continue
        return text
    return ""


def _find_footer(lines: list[str], after_opts: int) -> str:
    for line in lines[after_opts:after_opts + _TITLE_WINDOW]:
        text = line.strip()
        if _FOOTER_RE.search(text):
            return text
    return ""

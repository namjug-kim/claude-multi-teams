"""Tests for the codex post-spawn warmup state machine.

The machine polls a screen ``capture``, recognizes numbered selection modals
(via :mod:`cmt.modal`), picks a safe option by content, and presses keys until
the codex banner shows up.

Modals seen in real codex (>= 0.134) even with the bypass flags:
  - Trust folder:      "Do you trust the contents of this directory?" → "Yes, continue"
  - Update available!: must NOT press the default ("Update now") → pick "Skip"
  - Hooks need review: must NOT press the default ("Review hooks") → pick "Trust all"
"""

from __future__ import annotations

import pytest

from cmt.codex_warmup import run_codex_warmup, BANNER_MARKER

TRUST = (
    "> You are in /tmp\n"
    "Do you trust the contents of this directory?\n"
    "› 1. Yes, continue\n"
    "  2. No, quit"
)
def _update(hl: int) -> str:
    rows = ["Update now (runs `npm install -g @openai/codex`)", "Skip", "Skip until next version"]
    body = "\n".join(f"{'›' if i == hl else ' '} {i}. {r}" for i, r in enumerate(rows, 1))
    return (
        "✨ Update available! 0.134.0 → 0.135.0\n"
        "Release notes: https://github.com/openai/codex/releases/latest\n\n"
        f"{body}\n\nPress enter to continue"
    )


def _hooks(hl: int) -> str:
    rows = ["Review hooks", "Trust all and continue", "Continue without trusting (hooks won't run)"]
    body = "\n".join(f"{'›' if i == hl else ' '} {i}. {r}" for i, r in enumerate(rows, 1))
    return (
        "Hooks need review\n6 hooks are new or changed.\n\n"
        f"{body}\n\nPress enter to confirm or esc to go back"
    )


UPDATE = _update(1)          # boot default highlights the dangerous "Update now"
UPDATE_SEL = _update(2)      # after pressing "2", highlight on "Skip"
HOOKS = _hooks(1)            # boot default highlights "Review hooks"
HOOKS_SEL = _hooks(2)        # after pressing "2", highlight on "Trust all"
BANNER = f"{BANNER_MARKER} (v0.135.0)\n› Implement {{feature}}"


class _FakeIO:
    """Emits scripted screens and records key presses. Optionally advances the
    script whenever a particular key is seen (to model 'Enter confirms')."""

    def __init__(self, scripted_screens: list[str]) -> None:
        self.screens = list(scripted_screens)
        self.keys_sent: list[str] = []
        self.captures = 0

    def capture(self) -> str:
        self.captures += 1
        if len(self.screens) <= 1:
            return self.screens[0] if self.screens else ""
        return self.screens.pop(0)

    def keys(self, key: str) -> None:
        self.keys_sent.append(key)


def test_banner_already_present_returns_immediately() -> None:
    io = _FakeIO([BANNER])
    run_codex_warmup(capture=io.capture, send_key=io.keys, deadline_s=2.0, poll_interval=0.01)
    assert io.keys_sent == []


def test_trust_modal_selects_yes_then_banner() -> None:
    # poll 1: digit "1"; poll 2: same modal -> "Enter"; poll 3: banner.
    io = _FakeIO([TRUST, TRUST, BANNER])
    run_codex_warmup(capture=io.capture, send_key=io.keys, deadline_s=2.0, poll_interval=0.01)
    assert io.keys_sent == ["1", "Enter"]


def test_update_modal_picks_skip_never_update_now() -> None:
    io = _FakeIO([UPDATE, UPDATE_SEL, BANNER])
    run_codex_warmup(capture=io.capture, send_key=io.keys, deadline_s=2.0, poll_interval=0.01)
    # "Skip" is option 2 — we must select 2, never the highlighted default (1).
    assert io.keys_sent == ["2", "Enter"]


def test_hooks_modal_picks_trust_all() -> None:
    io = _FakeIO([HOOKS, HOOKS_SEL, BANNER])
    run_codex_warmup(capture=io.capture, send_key=io.keys, deadline_s=2.0, poll_interval=0.01)
    # "Trust all and continue" is option 2.
    assert io.keys_sent == ["2", "Enter"]


def test_waits_for_highlight_before_confirming() -> None:
    """Safety: while the digit hasn't moved the highlight off the dangerous
    default, we keep pressing the digit and never send Enter (which would
    confirm 'Update now')."""
    io = _FakeIO([UPDATE, UPDATE, UPDATE_SEL, BANNER])  # default lingers one extra poll
    run_codex_warmup(capture=io.capture, send_key=io.keys, deadline_s=2.0, poll_interval=0.01)
    assert io.keys_sent == ["2", "2", "Enter"]


def test_chained_modals_update_then_hooks_then_banner() -> None:
    io = _FakeIO([UPDATE, UPDATE_SEL, HOOKS, HOOKS_SEL, BANNER])
    run_codex_warmup(capture=io.capture, send_key=io.keys, deadline_s=2.0, poll_interval=0.01)
    assert io.keys_sent == ["2", "Enter", "2", "Enter"]


def test_digit_that_confirms_does_not_send_stray_enter() -> None:
    """If pressing the digit also confirms (modal advances before we'd send
    Enter), no stray Enter is emitted onto the next screen's default."""
    # poll 1: UPDATE -> send "2"; poll 2: already advanced to banner.
    io = _FakeIO([UPDATE, BANNER])
    run_codex_warmup(capture=io.capture, send_key=io.keys, deadline_s=2.0, poll_interval=0.01)
    assert io.keys_sent == ["2"]


def test_does_not_repress_during_render_lag() -> None:
    """While the same modal lingers after being fully answered, no more keys."""
    io = _FakeIO([TRUST, TRUST, TRUST, TRUST, BANNER])
    run_codex_warmup(capture=io.capture, send_key=io.keys, deadline_s=2.0, poll_interval=0.01)
    assert io.keys_sent == ["1", "Enter"]


def test_times_out_when_no_banner() -> None:
    io = _FakeIO(["nothing here matches any pattern"])
    with pytest.raises(TimeoutError):
        run_codex_warmup(capture=io.capture, send_key=io.keys, deadline_s=0.2, poll_interval=0.05)


def test_timeout_message_includes_last_modal() -> None:
    # An unknown modal we have no pick for: never answered, times out with detail.
    unknown = "Pick a color\n› 1. Red\n  2. Blue\nPress enter to continue"
    io = _FakeIO([unknown])
    with pytest.raises(TimeoutError, match="Red"):
        run_codex_warmup(capture=io.capture, send_key=io.keys, deadline_s=0.2, poll_interval=0.05)

"""Tests for the codex post-spawn warmup state machine.

The machine takes ``capture`` and ``keys`` callables (so we can mock both)
and a deadline. It captures the screen, matches known modal patterns, sends
the right key sequence, and loops until the codex banner shows up.

Modals seen in real codex 0.134.0 with --dangerously-bypass-approvals-and-sandbox
+ --dangerously-bypass-hook-trust:
  - Trust folder: "Do you trust the contents of this directory?" → press Enter
  - (Update / Hooks bypassed by flags in the bypass invocation.)
"""

from __future__ import annotations

import pytest

from cmt.codex_warmup import run_codex_warmup, BANNER_MARKER, TRUST_MODAL_MARKER


class _FakeIO:
    """Records key presses and emits scripted screen states."""

    def __init__(self, scripted_screens: list[str]) -> None:
        self.screens = list(scripted_screens)
        self.keys_sent: list[str] = []
        self.captures = 0

    def capture(self) -> str:
        self.captures += 1
        if not self.screens:
            return ""
        # Last screen sticks
        if len(self.screens) == 1:
            return self.screens[0]
        return self.screens.pop(0)

    def keys(self, key: str) -> None:
        self.keys_sent.append(key)


def test_banner_already_present_returns_immediately() -> None:
    io = _FakeIO([f"some output\n{BANNER_MARKER} (v0.134.0)\n› Implement {{feature}}"])
    run_codex_warmup(capture=io.capture, send_key=io.keys, deadline_s=2.0, poll_interval=0.01)
    assert io.keys_sent == []
    assert io.captures >= 1


def test_handles_trust_modal_then_banner() -> None:
    io = _FakeIO([
        f"> You are in /tmp\n{TRUST_MODAL_MARKER}\n› 1. Yes, continue\n  2. No, quit",
        f"OpenAI Codex (v0.134.0)\n› Implement {{feature}}",
    ])
    run_codex_warmup(capture=io.capture, send_key=io.keys, deadline_s=2.0, poll_interval=0.01)
    assert "Enter" in io.keys_sent
    # Final screen should match banner before returning.


def test_times_out_when_no_banner() -> None:
    io = _FakeIO(["nothing here matches any pattern"])
    with pytest.raises(TimeoutError):
        run_codex_warmup(capture=io.capture, send_key=io.keys, deadline_s=0.3, poll_interval=0.05)


def test_does_not_repress_already_handled_modal() -> None:
    """Once Trust modal is handled, we shouldn't keep pressing Enter every
    poll while waiting for the banner — that could double-submit and
    advance other modals unintentionally. The machine should only press
    a modal's key once per modal-occurrence."""
    io = _FakeIO([
        f"{TRUST_MODAL_MARKER}\n› 1. Yes, continue",   # poll 1: Trust → Enter
        f"{TRUST_MODAL_MARKER}\n› 1. Yes, continue",   # poll 2: still showing (slow render) → NOT re-pressed
        f"{TRUST_MODAL_MARKER}\n› 1. Yes, continue",   # poll 3: still
        f"OpenAI Codex (v0.134.0)\n› ready",
    ])
    run_codex_warmup(capture=io.capture, send_key=io.keys, deadline_s=2.0, poll_interval=0.01)
    # Exactly one Enter — we don't spam during the modal's render lag.
    assert io.keys_sent == ["Enter"]

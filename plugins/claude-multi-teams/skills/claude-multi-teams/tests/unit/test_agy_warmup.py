"""Tests for the agy post-spawn warmup state machine."""

import pytest

from cmt.agy_warmup import run_agy_warmup, TRUST_MODAL_MARKER
from cmt.agy_screen import STATUS_DONE_MARKER


class _FakeIO:
    def __init__(self, screens: list[str]) -> None:
        self.screens = list(screens)
        self.keys_sent: list[str] = []

    def capture(self) -> str:
        if not self.screens:
            return ""
        if len(self.screens) == 1:
            return self.screens[0]
        return self.screens.pop(0)

    def keys(self, key: str) -> None:
        self.keys_sent.append(key)


def test_ready_marker_already_present_returns_immediately() -> None:
    io = _FakeIO([f"some output\n{STATUS_DONE_MARKER}\n"])
    run_agy_warmup(capture=io.capture, send_key=io.keys, deadline_s=2.0, poll_interval=0.01)
    assert io.keys_sent == []


def test_trust_modal_then_ready() -> None:
    io = _FakeIO([
        f"{TRUST_MODAL_MARKER}\n> Yes, I trust this folder",
        f"banner here\n{STATUS_DONE_MARKER}",
    ])
    run_agy_warmup(capture=io.capture, send_key=io.keys, deadline_s=2.0, poll_interval=0.01)
    assert "Enter" in io.keys_sent


def test_times_out_when_never_ready() -> None:
    io = _FakeIO(["nothing here matches anything"])
    with pytest.raises(TimeoutError):
        run_agy_warmup(capture=io.capture, send_key=io.keys, deadline_s=0.3, poll_interval=0.05)


def test_does_not_repress_trust_modal_during_render_lag() -> None:
    io = _FakeIO([
        f"{TRUST_MODAL_MARKER}",   # poll 1: send Enter
        f"{TRUST_MODAL_MARKER}",   # poll 2: still visible → no repress
        f"{TRUST_MODAL_MARKER}",   # poll 3: still visible → no repress
        f"{STATUS_DONE_MARKER}",
    ])
    run_agy_warmup(capture=io.capture, send_key=io.keys, deadline_s=2.0, poll_interval=0.01)
    assert io.keys_sent == ["Enter"]

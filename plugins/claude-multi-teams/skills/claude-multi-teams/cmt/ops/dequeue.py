"""cmt dequeue — atomically take the oldest pending inbox message.

Returns the message as JSON on stdout (or empty if inbox empty).
A scheduler loops dequeue → cmt ask → enqueue replies → repeat."""

from __future__ import annotations

from pathlib import Path

from cmt import inbox, state


def dequeue(agent: str, state_dir: Path | None = None) -> inbox.Message | None:
    sd = state_dir if state_dir is not None else state.default_dir()
    return inbox.dequeue(sd, agent)

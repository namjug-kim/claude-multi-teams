"""cmt enqueue — fire-and-forget write to an agent's inbox.

Used by the actor-model pattern. Unlike ``cmt ask`` which blocks until
the target replies, ``enqueue`` returns immediately after the message is
durably written to disk."""

from __future__ import annotations

from pathlib import Path

from cmt import inbox, state


def enqueue(
    target: str,
    content: str,
    sender: str = "",
    replies_to: str | None = None,
    state_dir: Path | None = None,
) -> inbox.Message:
    sd = state_dir if state_dir is not None else state.default_dir()
    return inbox.enqueue(sd, target, content, sender=sender, replies_to=replies_to)

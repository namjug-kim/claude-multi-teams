"""Per-agent message inboxes — the actor-model side of cmt.

Each agent has a directory ``$STATE_DIR/inbox/<agent>/`` holding pending
messages as files named ``<iso-timestamp>-<uuid>.json``. The timestamp
prefix makes lexicographic sort = FIFO order. ``dequeue`` is atomic via
``rename`` so two readers can never claim the same message.

In contrast to ``cmt ask`` (which BLOCKS the caller until the target's
turn finishes), ``enqueue`` is fire-and-forget — the caller writes a
message and returns immediately. A scheduler (or each agent itself,
between turns) drains its inbox by calling ``dequeue`` + processing.

Because nothing blocks while another agent is reasoning, the wait-for
graph is empty by construction → deadlock is structurally impossible.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class Message:
    msg_id: str          # unique per message, stable across rename
    to: str              # target agent name
    sender: str          # 'sender' (not 'from' — reserved kw); empty string = orchestrator
    content: str         # body of the message
    replies_to: str | None  # msg_id this is a reply to, if any
    ts: str              # ISO 8601 UTC, sortable


def _inbox_dir(state_dir: Path, agent: str) -> Path:
    return state_dir / "inbox" / agent


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H-%M-%S-%f") + "Z"


def enqueue(
    state_dir: Path,
    to: str,
    content: str,
    sender: str = "",
    replies_to: str | None = None,
) -> Message:
    """Write a new message to ``to``'s inbox. Returns the persisted Message
    (with assigned msg_id and timestamp)."""
    msg = Message(
        msg_id=uuid.uuid4().hex,
        to=to,
        sender=sender,
        content=content,
        replies_to=replies_to,
        ts=_now_iso(),
    )
    d = _inbox_dir(state_dir, to)
    d.mkdir(parents=True, exist_ok=True)
    # filename = sortable ts + unique suffix
    path = d / f"{msg.ts}-{msg.msg_id[:8]}.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(asdict(msg)))
    tmp.replace(path)
    return msg


def dequeue(state_dir: Path, agent: str) -> Message | None:
    """Take the oldest pending message from ``agent``'s inbox and delete it.
    Returns ``None`` if the inbox is empty. Atomic via ``rename`` — a parallel
    dequeue races safely; at most one wins per message."""
    d = _inbox_dir(state_dir, agent)
    if not d.exists():
        return None
    files = sorted(d.glob("*.json"))
    for f in files:
        # Skip half-written tmp files
        if f.name.endswith(".json.tmp"):
            continue
        taken = f.with_suffix(".taken")
        try:
            f.rename(taken)
        except FileNotFoundError:
            # Another reader grabbed this one
            continue
        try:
            data = json.loads(taken.read_text())
            taken.unlink()
            return Message(**data)
        except Exception:
            # On parse failure, drop the broken message and continue
            taken.unlink(missing_ok=True)
            continue
    return None


def peek(state_dir: Path, agent: str) -> list[Message]:
    """Non-destructive read of all pending messages, oldest first."""
    d = _inbox_dir(state_dir, agent)
    if not d.exists():
        return []
    out: list[Message] = []
    for f in sorted(d.glob("*.json")):
        if f.name.endswith(".json.tmp"):
            continue
        try:
            out.append(Message(**json.loads(f.read_text())))
        except Exception:
            continue
    return out


def has_messages(state_dir: Path, agent: str) -> bool:
    return any(_inbox_dir(state_dir, agent).glob("*.json")) \
        if _inbox_dir(state_dir, agent).exists() else False


def count(state_dir: Path, agent: str) -> int:
    return len(peek(state_dir, agent))


def clear(state_dir: Path, agent: str) -> int:
    """Drop all pending messages for an agent. Returns the count removed."""
    d = _inbox_dir(state_dir, agent)
    if not d.exists():
        return 0
    n = 0
    for f in list(d.glob("*.json")):
        try:
            f.unlink()
            n += 1
        except FileNotFoundError:
            pass
    return n

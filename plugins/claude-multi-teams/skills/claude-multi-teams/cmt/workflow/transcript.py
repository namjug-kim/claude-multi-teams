"""Append-only shared history under ``$CMT_STATE_DIR/transcript/<topic>.jsonl``.

Answers "how did we get here?": every contribution is one JSON line
``{ts, from, content}``, never consumed, read by tailing. Distinct from
the inbox (point-to-point, consumed) and KV (current state, overwritten).
"""

from __future__ import annotations

import datetime as _dt
import json
import re
from pathlib import Path

from cmt import state

_TOPIC_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


def _validate_topic(topic: str) -> None:
    if not _TOPIC_RE.match(topic):
        raise ValueError(
            f"invalid transcript topic {topic!r}: must match [a-z0-9][a-z0-9_-]*"
        )


def _path(topic: str, state_dir: Path | None) -> Path:
    return (state_dir or state.default_dir()) / "transcript" / f"{topic}.jsonl"


def append(topic: str, content: str, frm: str | None = None,
           state_dir: Path | None = None) -> None:
    _validate_topic(topic)
    p = _path(topic, state_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": _dt.datetime.now(_dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "from": frm or "",
        "content": content,
    }
    with p.open("a") as f:
        f.write(json.dumps(entry) + "\n")


def tail(topic: str, n: int | None = None,
         state_dir: Path | None = None) -> list[dict]:
    _validate_topic(topic)
    p = _path(topic, state_dir)
    if not p.exists():
        return []
    out: list[dict] = []
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    if n is not None:
        out = out[-n:]
    return out

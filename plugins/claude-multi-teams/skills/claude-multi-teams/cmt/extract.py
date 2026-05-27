"""Per-agent response extraction from session logs / screen captures."""

from __future__ import annotations

import json
from pathlib import Path


def extract_jsonl_assistant(jsonl_path: Path, baseline_offset: int = 0) -> str:
    """Return all assistant text written to ``jsonl_path`` at or after ``baseline_offset``.

    Walks the file from ``baseline_offset`` (a byte position in the file) to end,
    finds every ``type == "assistant"`` event, and concatenates the ``text`` blocks
    from each event's ``message.content``. Non-text blocks (``tool_use`` etc.)
    are ignored. Malformed lines are skipped silently.

    Callers (typically the ``ask`` op) capture ``jsonl_path.stat().st_size``
    immediately before sending a prompt, then call with that as
    ``baseline_offset`` after detecting the turn is done; that yields exactly
    the assistant text produced in response to the prompt — including text
    surrounding tool calls.
    """
    parts: list[str] = []
    with open(jsonl_path) as f:
        f.seek(baseline_offset)
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") != "assistant":
                continue
            content = event.get("message", {}).get("content")
            if isinstance(content, str):
                parts.append(content)
                continue
            if not isinstance(content, list):
                continue
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(block.get("text", ""))
    return "".join(parts).strip()

"""Per-agent done-detection strategies.

Foundation primitives. ``ask`` plus ``wait-status`` compose these into the
"block until the agent's turn is over" surface.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable, Literal

AskResult = Literal["done", "dead"]
AgentStatus = Literal["working", "done", "blocked", "dead"]

# stop_reason values that mean the turn is fully over (no further assistant
# message is pending from this prompt). Other values like "tool_use" or
# "pause_turn" mean the model is mid-turn and another assistant message is
# expected after the next tool result / continuation.
_TERMINAL_STOP_REASONS = frozenset({"end_turn", "stop_sequence", "max_tokens"})


def await_jsonl_done(
    jsonl_path: Path,
    baseline_offset: int,
    is_alive: Callable[[], bool],
    poll_interval: float = 0.5,
) -> AskResult:
    """Poll ``jsonl_path`` until an assistant event with a terminal stop_reason
    appears after ``baseline_offset``. Return ``"done"`` on completion or
    ``"dead"`` if ``is_alive()`` ever returns False.

    Honors the foundation contract: no wall-clock or idle timeout. The only
    abort condition is pane/agent death, surfaced through ``is_alive``.
    Tolerates the jsonl file not yet existing (claude only writes it on
    the first user input) and malformed/partial lines (which can appear
    during a concurrent write).
    """
    while True:
        if not is_alive():
            return "dead"
        last_stop: str | None = None
        try:
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
                    sr = event.get("message", {}).get("stop_reason")
                    if sr:
                        last_stop = sr
        except FileNotFoundError:
            pass
        if last_stop in _TERMINAL_STOP_REASONS:
            return "done"
        time.sleep(poll_interval)


def status_jsonl(
    jsonl_path: Path,
    baseline_offset: int,
    pane_alive: bool,
) -> AgentStatus:
    """One-shot read of an agent's current status from its jsonl + pane liveness.

    ``baseline_offset`` is "where the current turn began" (the file size
    captured when the latest ask sent its prompt). Semantics:

    - pane gone → ``dead``
    - jsonl has no new bytes since baseline → ``done`` (idle)
    - new bytes but no assistant event with a terminal stop_reason yet → ``working``
    - new bytes ending in an assistant event with a terminal stop_reason → ``done``

    ``blocked`` is not detected at the jsonl layer (no current claude/codex
    state surfaces tool-permission modals there); the agy capture-pane strategy
    in a later slice owns that.
    """
    if not pane_alive:
        return "dead"
    if not jsonl_path.exists():
        return "done"
    try:
        size = jsonl_path.stat().st_size
    except FileNotFoundError:
        return "done"
    if size <= baseline_offset:
        return "done"
    last_stop: str | None = None
    saw_event = False
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
            saw_event = True
            if event.get("type") == "assistant":
                sr = event.get("message", {}).get("stop_reason")
                if sr is not None:
                    last_stop = sr
    if last_stop in _TERMINAL_STOP_REASONS:
        return "done"
    return "working" if saw_event else "done"


# Codex rollout-file strategy. Codex emits events under ``type=event_msg`` with
# a ``payload.type`` discriminator. ``task_complete`` is the terminal marker.
def _scan_codex(jsonl_path: Path, baseline_offset: int) -> tuple[bool, bool]:
    """Return ``(saw_any_event, saw_task_complete)`` for events after offset.

    Tolerates the file not existing yet (codex creates it only on the first
    prompt) and malformed/partial lines (concurrent writes).
    """
    saw_event = False
    saw_complete = False
    try:
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
                if event.get("type") != "event_msg":
                    continue
                saw_event = True
                payload = event.get("payload") or {}
                if payload.get("type") == "task_complete":
                    saw_complete = True
    except FileNotFoundError:
        pass
    return saw_event, saw_complete


def await_codex_done(
    jsonl_path: Path,
    baseline_offset: int,
    is_alive: Callable[[], bool],
    poll_interval: float = 0.5,
) -> AskResult:
    """Poll ``jsonl_path`` until a ``task_complete`` event appears after
    ``baseline_offset``. Returns ``"done"`` or ``"dead"`` (mirrors
    ``await_jsonl_done`` for claude). No wall-clock or idle timeout."""
    while True:
        if not is_alive():
            return "dead"
        _, complete = _scan_codex(jsonl_path, baseline_offset)
        if complete:
            return "done"
        time.sleep(poll_interval)


def status_codex(
    jsonl_path: Path,
    baseline_offset: int,
    pane_alive: bool,
) -> AgentStatus:
    """One-shot status read from codex rollout. Mirrors ``status_jsonl`` shape:
    pane gone → dead; no file / no new bytes → done; events but no
    task_complete → working; task_complete present → done.
    """
    if not pane_alive:
        return "dead"
    if not jsonl_path.exists():
        return "done"
    try:
        size = jsonl_path.stat().st_size
    except FileNotFoundError:
        return "done"
    if size <= baseline_offset:
        return "done"
    saw_event, complete = _scan_codex(jsonl_path, baseline_offset)
    if complete:
        return "done"
    return "working" if saw_event else "done"

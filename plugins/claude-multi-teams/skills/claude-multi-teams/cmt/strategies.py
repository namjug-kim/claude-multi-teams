"""Per-agent done-detection strategies.

Foundation primitives. ``ask`` plus ``wait-status`` compose these into the
"block until the agent's turn is over" surface.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal

AskResult = Literal["done", "blocked", "dead"]
AgentStatus = Literal["working", "done", "blocked", "dead"]

# stop_reason values that mean the turn is fully over (no further assistant
# message is pending from this prompt). Other values like "tool_use" or
# "pause_turn" mean the model is mid-turn and another assistant message is
# expected after the next tool result / continuation.
_TERMINAL_STOP_REASONS = frozenset({"end_turn", "stop_sequence", "max_tokens"})

# Tools that hand control back to the *user* and park the turn until answered.
# When claude ends a turn on one of these with no tool_result yet, no terminal
# stop_reason is ever written - the jsonl-tail strategy would otherwise treat
# the idle, input-waiting pane as "working" forever.
_INTERACTIVE_TOOLS = frozenset({"AskUserQuestion"})


@dataclass(frozen=True)
class TurnScan:
    """One pass over a claude jsonl turn region after ``baseline_offset``."""
    saw_event: bool
    last_terminal: bool
    pending_question: dict | None


def _scan_jsonl_turn(jsonl_path: Path, baseline_offset: int) -> TurnScan:
    """Scan a turn region once, classifying its end state.

    Tracks every ``tool_result`` id seen so an answered interactive tool is not
    mistaken for a pending one, and tracks the last main-chain assistant event.
    """
    saw_event = False
    answered_ids: set[str] = set()
    last_stop: str | None = None
    last_interactive: tuple[str | None, dict] | None = None
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
                saw_event = True
                msg = event.get("message")
                content = msg.get("content") if isinstance(msg, dict) else None
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "tool_result":
                            tid = block.get("tool_use_id")
                            if tid:
                                answered_ids.add(tid)
                if event.get("type") != "assistant" or event.get("isSidechain"):
                    continue
                last_stop = msg.get("stop_reason") if isinstance(msg, dict) else None
                last_interactive = None
                if isinstance(content, list):
                    for block in content:
                        if not isinstance(block, dict) or block.get("type") != "tool_use":
                            continue
                        if block.get("name") in _INTERACTIVE_TOOLS:
                            last_interactive = (block.get("id"), block.get("input") or {})
    except FileNotFoundError:
        pass

    pending = None
    if last_interactive is not None:
        tid, payload = last_interactive
        if tid not in answered_ids:
            pending = payload
    return TurnScan(
        saw_event=saw_event,
        last_terminal=last_stop in _TERMINAL_STOP_REASONS,
        pending_question=pending,
    )


def await_jsonl_done(
    jsonl_path: Path,
    baseline_offset: int,
    is_alive: Callable[[], bool],
    poll_interval: float = 0.5,
    on_poll: Callable[[], None] | None = None,
) -> AskResult:
    """Poll ``jsonl_path`` until the turn after ``baseline_offset`` ends.

    Returns ``"done"`` on a terminal stop_reason, ``"blocked"`` if the turn
    parks on an interactive tool such as AskUserQuestion, or ``"dead"`` if
    ``is_alive()`` ever returns False.

    Honors the foundation contract: no wall-clock or idle timeout. The only
    abort conditions are pane death and an input-waiting block.
    Tolerates the jsonl file not yet existing (claude only writes it on
    the first user input) and malformed/partial lines (which can appear
    during a concurrent write).
    """
    while True:
        if not is_alive():
            return "dead"
        scan = _scan_jsonl_turn(jsonl_path, baseline_offset)
        if scan.last_terminal:
            return "done"
        if scan.pending_question is not None:
            return "blocked"
        if on_poll is not None:
            on_poll()
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
    - turn parked on an interactive tool awaiting an answer → ``blocked``
    - new bytes but no terminal stop_reason yet → ``working``
    - new bytes ending in an assistant event with a terminal stop_reason → ``done``

    Use :func:`pending_question` to read the structured question for a blocked
    claude turn.
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
    scan = _scan_jsonl_turn(jsonl_path, baseline_offset)
    if scan.last_terminal:
        return "done"
    if scan.pending_question is not None:
        return "blocked"
    return "working" if scan.saw_event else "done"


def pending_question(jsonl_path: Path, baseline_offset: int) -> dict | None:
    """The structured AskUserQuestion input the turn is parked on, or None."""
    return _scan_jsonl_turn(jsonl_path, baseline_offset).pending_question


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

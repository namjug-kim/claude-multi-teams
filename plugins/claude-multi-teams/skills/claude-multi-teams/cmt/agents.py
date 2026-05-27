"""Per-agent specifications.

Each spec is a small dataclass + a few pure functions. The data-and-strategy
shape (rather than a class hierarchy) keeps the variation legible: claude vs
codex vs agy is three rows in the AGENTS table, not three subclasses.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass(frozen=True)
class SpawnContext:
    """Inputs handed to a spec's spawn-time hooks. ``session_uuid`` is meaningful
    for agents that accept ``--session-id`` (claude); codex/agy ignore it."""
    name: str
    agent_id: str
    cwd: str
    session_uuid: str


@dataclass(frozen=True)
class AgentSpec:
    name: str
    propagate_env_prefixes: tuple[str, ...]
    build_argv: Callable[[SpawnContext], list[str]]
    session_file: Callable[[SpawnContext, dict[str, str]], str | None]


def _claude_argv(ctx: SpawnContext) -> list[str]:
    # CMT_CLAUDE_BIN lets tests (and power users) substitute a different
    # binary path without relying on PATH manipulation — tmux's -e PATH=...
    # injection is clobbered by macOS shell rc files that re-set PATH.
    binary = os.environ.get("CMT_CLAUDE_BIN", "claude")
    return [
        binary,
        "--session-id", ctx.session_uuid,
        "--dangerously-skip-permissions",
    ]


def _claude_session_file(ctx: SpawnContext, env: dict[str, str]) -> str:
    base = env.get("CLAUDE_CONFIG_DIR") or os.environ.get("CLAUDE_CONFIG_DIR") \
        or str(Path.home() / ".claude")
    cwd_dashed = ctx.cwd.replace("/", "-")
    return f"{base}/projects/{cwd_dashed}/{ctx.session_uuid}.jsonl"


AGENTS: dict[str, AgentSpec] = {
    "claude": AgentSpec(
        name="claude",
        propagate_env_prefixes=("CLAUDE_", "ANTHROPIC_"),
        build_argv=_claude_argv,
        session_file=_claude_session_file,
    ),
    # codex, agy added in subsequent slices.
}

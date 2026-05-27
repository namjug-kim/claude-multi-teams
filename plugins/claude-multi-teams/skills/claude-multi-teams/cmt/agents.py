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
    # Optional hook called after the pane is split + agent CLI launched.
    # Signature: (ctx, pane_id) -> None. Used by codex to drive its spawn-time
    # modal state machine (Trust folder, etc.) and wait for the agent banner.
    # claude doesn't need one in the default-flag environment.
    post_spawn_warmup: Callable[[SpawnContext, str], None] | None = None
    # Optional hook called before the agent CLI is launched. Returns a string
    # to persist in AgentState.spawn_marker — codex uses it to snapshot the
    # max-mtime of ``~/.codex/sessions`` so the rollout file created after the
    # first prompt can be discovered.
    pre_spawn_marker: Callable[[SpawnContext], str | None] | None = None
    # Optional hook called on the first ``ask`` if session_file is still None,
    # to resolve a delayed session file. Signature: (ctx, state) -> str | None.
    resolve_session_file: Callable[..., str | None] | None = None
    # Per-agent done / status / extract dispatch. Defaults wired below to the
    # claude (jsonl + stop_reason) strategy.
    await_done: Callable[..., "object"] | None = None
    status_fn: Callable[..., "object"] | None = None
    extract_response: Callable[..., str] | None = None


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


def _codex_argv(ctx: SpawnContext) -> list[str]:
    binary = os.environ.get("CMT_CODEX_BIN", "codex")
    return [
        binary,
        "--dangerously-bypass-approvals-and-sandbox",
        "--dangerously-bypass-hook-trust",
    ]


def _codex_session_file(ctx: SpawnContext, env: dict[str, str]) -> str | None:
    # Codex creates ~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl only after
    # the first prompt. Spawn cannot know the path; resolve_session_file
    # discovers it on the first ask.
    return None


def _codex_pre_spawn_marker(ctx: SpawnContext) -> str | None:
    # Snapshot the max-mtime of the codex sessions tree as a float string.
    # On the first ask we scan for a rollout newer than this.
    from cmt import codex_session
    return str(codex_session.snapshot_max_mtime(codex_session.sessions_root()))


def _codex_post_spawn_warmup(ctx: SpawnContext, pane_id: str) -> None:
    """Run the codex spawn-time modal state machine against the live pane.
    Returns once the codex banner is on screen, or raises ``TimeoutError``.
    """
    from cmt import codex_warmup, mux
    codex_warmup.run_codex_warmup(
        capture=lambda: mux.capture(pane_id, mode="full"),
        send_key=lambda key: mux.send_keys(pane_id, key),
    )


def _codex_resolve_session_file(ctx: SpawnContext, spawn_marker: str | None) -> str | None:
    """Block until a new rollout file appears, return its path. Called from
    the first ``ask`` if state.session_file is still None for codex.

    ``spawn_marker`` is the float-string captured by ``_codex_pre_spawn_marker``
    at spawn time. Times out after 10s if codex never wrote a new rollout —
    in which case ``ask`` will raise.
    """
    from cmt import codex_session
    after = float(spawn_marker) if spawn_marker else 0.0
    found = codex_session.wait_for_new_rollout(
        codex_session.sessions_root(),
        after=after,
        timeout=10.0,
        poll_interval=0.1,
    )
    return str(found) if found is not None else None


def _build_agents() -> dict[str, AgentSpec]:
    # Import strategies / extract lazily to avoid a circular import at module
    # load time (strategies/extract are pure, but cmt/__init__ collection order
    # is easier to reason about with this defer).
    from cmt import extract as _extract
    from cmt import strategies as _strategies

    return {
        "claude": AgentSpec(
            name="claude",
            propagate_env_prefixes=("CLAUDE_", "ANTHROPIC_"),
            build_argv=_claude_argv,
            session_file=_claude_session_file,
            await_done=_strategies.await_jsonl_done,
            status_fn=_strategies.status_jsonl,
            extract_response=_extract.extract_jsonl_assistant,
        ),
        "codex": AgentSpec(
            name="codex",
            propagate_env_prefixes=("CODEX_", "OPENAI_"),
            build_argv=_codex_argv,
            session_file=_codex_session_file,
            pre_spawn_marker=_codex_pre_spawn_marker,
            post_spawn_warmup=_codex_post_spawn_warmup,
            resolve_session_file=_codex_resolve_session_file,
            await_done=_strategies.await_codex_done,
            status_fn=_strategies.status_codex,
            extract_response=_extract.extract_codex_response,
        ),
        # agy added in a subsequent slice.
    }


AGENTS: dict[str, AgentSpec] = _build_agents()

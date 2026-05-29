"""cmt spawn — create a pane, start an agent, record state."""

from __future__ import annotations

import dataclasses
import datetime as _dt
import os
import shlex
import uuid
from pathlib import Path

from cmt import agents, mux, state


def spawn(
    agent: str,
    name: str,
    cwd: str | None = None,
    replace: bool = False,
    state_dir: Path | None = None,
    parent_pane: str | None = None,
) -> state.AgentState:
    """Spawn ``agent`` in a new pane under ``name``.

    Returns the recorded AgentState. Raises:
      - ``ValueError`` for unknown agent or invalid name
      - ``FileExistsError`` if an agent with that name already exists and
        ``replace=False``
      - ``RuntimeError`` if not running inside a tmux pane (no parent to split)
    """
    state.validate_name(name)
    spec = agents.AGENTS.get(agent)
    if spec is None:
        raise ValueError(f"unknown agent {agent!r} (known: {sorted(agents.AGENTS)})")

    cwd = cwd or os.getcwd()

    existing = state.load(name, state_dir=state_dir)
    if existing is not None:
        if not replace:
            raise FileExistsError(
                f"agent {name!r} already exists (pane {existing.pane_id}). "
                f"use `cmt kill {name}` first, or `cmt spawn --replace {agent} {name}`."
            )
        # Guard the close the same way `kill` does: a stale/foreign pane id
        # must not fall through to cmux's focused-surface fallback (the user's
        # main tab). See cmt.ops.kill.
        if mux.pane_alive(existing.pane_id):
            mux.kill_pane(existing.pane_id)
        state.remove(name, state_dir=state_dir)

    parent = parent_pane or os.environ.get("TMUX_PANE")
    if not parent:
        raise RuntimeError(
            "no parent pane: cmt spawn must run inside a tmux pane (or set TMUX_PANE)."
        )

    agent_id = uuid.uuid4().hex[:16]
    session_uuid = str(uuid.uuid4())
    ctx = agents.SpawnContext(name=name, agent_id=agent_id, cwd=cwd, session_uuid=session_uuid)
    argv = spec.build_argv(ctx)

    # Capture spawn-time bookmark (e.g., codex max-mtime over sessions tree)
    # BEFORE launching, so the new rollout file can be located later.
    spawn_marker: str | None = None
    if spec.pre_spawn_marker is not None:
        spawn_marker = spec.pre_spawn_marker(ctx)

    env_vars: dict[str, str] = {"CMT_AGENT_ID": agent_id}
    # Framework-wide env that every spawned agent inherits so it can call
    # cmt back (e.g. for `cmt whoami` from inside the agent's Bash tool).
    for k in ("CMT_STATE_DIR",):
        if k in os.environ:
            env_vars[k] = os.environ[k]
    for prefix in spec.propagate_env_prefixes:
        for k, v in os.environ.items():
            if k.startswith(prefix):
                env_vars[k] = v

    cmd = shlex.join(argv)
    pane_id = mux.split_pane(parent, cwd, cmd, env_vars)
    session_file = spec.session_file(ctx, env_vars)

    # Run agent-specific spawn-time warmup (e.g., codex Trust-folder modal).
    if spec.post_spawn_warmup is not None:
        spec.post_spawn_warmup(ctx, pane_id)

    s = state.AgentState(
        name=name,
        agent=agent,
        agent_id=agent_id,
        pane_id=pane_id,
        cwd=cwd,
        started_at=_dt.datetime.now(_dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        session_file=session_file,
        baseline_offset=0,
        spawn_marker=spawn_marker,
    )
    state.save(s, state_dir=state_dir)
    return s

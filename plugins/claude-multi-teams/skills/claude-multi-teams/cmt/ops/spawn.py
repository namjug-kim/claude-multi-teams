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
            # Verify the close landed before dropping the record and reusing the
            # name. cmux close-surface is best-effort (check=False); if the pane
            # is still alive the close failed, and removing its state here would
            # orphan a live pane — its record overwritten by the new spawn.
            if mux.pane_alive(existing.pane_id):
                raise RuntimeError(
                    f"replace: could not close existing pane {existing.pane_id} "
                    f"for {name!r} (still alive after close); not dropping its "
                    f"state. Retry, or `cmt kill {name}` then spawn."
                )
        state.remove(name, state_dir=state_dir)

    parent = parent_pane or os.environ.get("TMUX_PANE") or mux.current_pane()
    if not parent:
        raise RuntimeError(
            "no parent pane: cmt spawn must run inside a tmux/cmux pane "
            "(or set TMUX_PANE)."
        )

    agent_id = uuid.uuid4().hex[:16]
    session_uuid = str(uuid.uuid4())
    sd = state_dir if state_dir is not None else state.default_dir()
    ctx = agents.SpawnContext(
        name=name, agent_id=agent_id, cwd=cwd,
        session_uuid=session_uuid, state_dir=sd,
    )
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
    # Spec-supplied env wins over propagated vars (codex overrides CODEX_HOME
    # to its per-agent isolated home).
    if spec.spawn_env is not None:
        env_vars.update(spec.spawn_env(ctx))

    cmd = shlex.join(argv)
    pane_id = mux.split_pane(parent, cwd, cmd, env_vars)
    session_file = spec.session_file(ctx, env_vars)

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
    # Record state BEFORE warmup. The warmup window can be minutes
    # (CMT_CODEX_WARMUP_DEADLINE); a hard-kill (SIGKILL/reboot) during it would
    # otherwise leave a live pane with no state file — an orphan no cmt command
    # could ever reap. With the record in place, `cmt kill <name>` can still
    # close it. A clean warmup failure tears down both pane and state below.
    state.save(s, state_dir=state_dir)

    # Run agent-specific spawn-time warmup (e.g., codex Trust-folder modal).
    # On failure, close the pane AND drop the record we just wrote, so a failed
    # spawn leaves neither an orphan pane nor stale state.
    if spec.post_spawn_warmup is not None:
        try:
            spec.post_spawn_warmup(ctx, pane_id)
        except BaseException:
            try:
                mux.kill_pane(pane_id)
            except Exception:
                pass
            state.remove(name, state_dir=state_dir)
            raise

    return s

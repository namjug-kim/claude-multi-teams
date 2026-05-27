"""Per-agent state persistence under ``$CMT_STATE_DIR/agents/<name>.json``."""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

_NAME_RE = re.compile(r"^[a-z0-9-]{1,32}$")


@dataclass(frozen=True)
class AgentState:
    name: str
    agent: str            # claude | codex | agy
    agent_id: str         # CMT_AGENT_ID — uuid4 hex slice, stable across pane recycle
    pane_id: str          # mux-native id, e.g. "%23"
    cwd: str
    started_at: str       # iso8601
    session_file: str | None = None   # claude/codex jsonl path; None for agy
    baseline_offset: int = 0          # bytes-into-jsonl when last ask began
    # Spawn-time bookmark, interpreted per-agent. codex uses it to store the
    # max-mtime of ~/.codex/sessions before spawn (as a float string) so the
    # rollout file created after the first prompt can be located.
    spawn_marker: str | None = None


def validate_name(name: str) -> None:
    if not isinstance(name, str) or not _NAME_RE.match(name):
        raise ValueError(
            f"invalid agent name {name!r}: must match [a-z0-9-]{{1,32}}"
        )


def default_dir() -> Path:
    override = os.environ.get("CMT_STATE_DIR")
    if override:
        return Path(override)
    return Path.home() / ".cache" / "cmt"


def _agent_path(name: str, state_dir: Path) -> Path:
    return state_dir / "agents" / f"{name}.json"


def save(state: AgentState, state_dir: Path | None = None) -> None:
    validate_name(state.name)
    sd = state_dir or default_dir()
    agents_dir = sd / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    path = _agent_path(state.name, sd)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(asdict(state), indent=2, sort_keys=True))
    tmp.replace(path)


def load(name: str, state_dir: Path | None = None) -> AgentState | None:
    sd = state_dir or default_dir()
    path = _agent_path(name, sd)
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    return AgentState(**data)


def list_all(state_dir: Path | None = None) -> list[AgentState]:
    sd = state_dir or default_dir()
    agents_dir = sd / "agents"
    if not agents_dir.exists():
        return []
    out: list[AgentState] = []
    for p in sorted(agents_dir.glob("*.json")):
        try:
            out.append(AgentState(**json.loads(p.read_text())))
        except (json.JSONDecodeError, TypeError):
            # tolerate corrupted state files — never crash list
            continue
    return out


def remove(name: str, state_dir: Path | None = None) -> None:
    sd = state_dir or default_dir()
    path = _agent_path(name, sd)
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def find_by_agent_id(agent_id: str, state_dir: Path | None = None) -> AgentState | None:
    """Reverse lookup: stable agent_id (CMT_AGENT_ID env) → AgentState.
    Used by ``whoami`` from inside a spawned pane."""
    for s in list_all(state_dir=state_dir):
        if s.agent_id == agent_id:
            return s
    return None

"""Agent roles — a workflow-layer concern, stored apart from raw agent state.

A Role is a stable identity string. `wf ask` prepends it to every prompt so
an agent can't drift out of its assigned stance across turns (the failure
where a "pro-monorepo" agent started arguing the opposite). The raw layer
knows nothing about roles; `cmt ask` sends prompts verbatim.
"""

from __future__ import annotations

from pathlib import Path

from cmt import state


def _roles_dir(state_dir: Path | None) -> Path:
    return (state_dir or state.default_dir()) / "workflow" / "roles"


def _path(name: str, state_dir: Path | None) -> Path:
    state.validate_name(name)
    return _roles_dir(state_dir) / name


def set_role(name: str, role: str, state_dir: Path | None = None) -> None:
    p = _path(name, state_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(role)
    tmp.replace(p)


def get_role(name: str, state_dir: Path | None = None) -> str | None:
    p = _path(name, state_dir)
    if not p.exists():
        return None
    return p.read_text()

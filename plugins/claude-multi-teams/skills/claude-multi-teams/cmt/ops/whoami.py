"""cmt whoami — running inside a spawned pane, identify ourselves.

Reads ``$CMT_AGENT_ID`` (injected at spawn) and resolves to the agent's
state. Returns ``None`` if the env is unset or the id is unknown.
"""

from __future__ import annotations

import os
from pathlib import Path

from cmt import state


def whoami(state_dir: Path | None = None) -> state.AgentState | None:
    agent_id = os.environ.get("CMT_AGENT_ID")
    if not agent_id:
        return None
    return state.find_by_agent_id(agent_id, state_dir=state_dir)

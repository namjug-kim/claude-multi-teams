"""cmt wait-status — block until agent reaches a target status.

Returns ``True`` if the target was reached. Returns ``False`` if the pane
died first (and ``dead`` wasn't the target). Per CONTEXT.md, callers wanting
a wall-clock cap wrap with shell ``timeout``.
"""

from __future__ import annotations

import time
from pathlib import Path

from cmt import strategies
from cmt.ops import status as status_op


def wait_status(
    name: str,
    target: strategies.AgentStatus,
    state_dir: Path | None = None,
    poll_interval: float = 0.5,
) -> bool:
    while True:
        cur = status_op.status(name, state_dir=state_dir)
        if cur == target:
            return True
        if cur == "dead" and target != "dead":
            return False
        time.sleep(poll_interval)

"""cmt doctor - explain whether this process can spawn sibling agents."""

from __future__ import annotations

import dataclasses
import os

from cmt import mux, state


@dataclasses.dataclass(frozen=True)
class DoctorReport:
    host: str
    backend: str
    spawn_ready: bool
    parent_pane: str | None
    reason: str
    tmux: str | None
    tmux_pane: str | None
    cmux_socket_path: str | None
    cmt_state_dir: str
    cmt_agent_id: str | None


def _host() -> str:
    tmux = os.environ.get("TMUX", "")
    if mux._tmux_points_at_cmux(tmux):
        return "cmux"
    if tmux:
        return "tmux"
    if os.environ.get("CMUX_SOCKET_PATH"):
        return "cmux"
    return "none"


def _backend() -> str:
    return "cmux" if mux._use_cmux_native() else "tmux"


def inspect() -> DoctorReport:
    """Return a small, parseable diagnosis of the current mux context."""
    tmux = os.environ.get("TMUX")
    tmux_pane = os.environ.get("TMUX_PANE")
    cmux_socket_path = os.environ.get("CMUX_SOCKET_PATH")

    parent = tmux_pane
    lookup_error: str | None = None
    if not parent:
        try:
            parent = mux.current_pane()
        except Exception as e:  # pragma: no cover - defensive CLI diagnosis
            lookup_error = f"{type(e).__name__}: {e}"

    host = _host()
    backend = _backend()
    ready = bool(parent)
    if ready:
        reason = f"parent pane resolved; cmt spawn will use the {backend} backend"
    elif lookup_error:
        reason = (
            "could not resolve a parent pane; cmt spawn needs a real tmux pane "
            f"or cmux teams surface ({lookup_error})"
        )
    elif host == "none":
        reason = (
            "no parent pane; run from inside real tmux or cmux teams, "
            "or set TMUX_PANE to a live pane"
        )
    else:
        reason = (
            "mux-like environment detected but no parent pane resolved; "
            "set TMUX_PANE or run from an interactive mux pane"
        )

    return DoctorReport(
        host=host,
        backend=backend,
        spawn_ready=ready,
        parent_pane=parent,
        reason=reason,
        tmux=tmux,
        tmux_pane=tmux_pane,
        cmux_socket_path=cmux_socket_path,
        cmt_state_dir=str(state.default_dir()),
        cmt_agent_id=os.environ.get("CMT_AGENT_ID"),
    )


def render(report: DoctorReport) -> str:
    def show(value: str | None) -> str:
        return value if value else "(unset)"

    lines = [
        f"host: {report.host}",
        f"backend: {report.backend}",
        f"spawn-ready: {'yes' if report.spawn_ready else 'no'}",
        f"parent-pane: {show(report.parent_pane)}",
        f"reason: {report.reason}",
        f"TMUX: {show(report.tmux)}",
        f"TMUX_PANE: {show(report.tmux_pane)}",
        f"CMUX_SOCKET_PATH: {show(report.cmux_socket_path)}",
        f"CMT_STATE_DIR: {report.cmt_state_dir}",
        f"CMT_AGENT_ID: {show(report.cmt_agent_id)}",
    ]
    return "\n".join(lines)

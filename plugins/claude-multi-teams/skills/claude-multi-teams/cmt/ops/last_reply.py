"""cmt last-reply — re-extract the most recent assistant text from jsonl.

Uses ``baseline_offset`` saved by the most recent ask (set just before the
prompt was sent). Returns an empty string if no ask has been made.
"""

from __future__ import annotations

from pathlib import Path

from cmt import agents, state


def last_reply(name: str, state_dir: Path | None = None) -> str:
    s = state.load(name, state_dir=state_dir)
    if s is None:
        raise FileNotFoundError(f"agent {name!r} not found.")
    spec = agents.AGENTS.get(s.agent)
    if spec is None or spec.extract_response is None:
        return ""
    if s.session_file is None and spec.resolve_session_file is not None:
        # codex pre-first-ask: nothing to extract yet
        return ""
    if s.session_file is not None and not Path(s.session_file).exists():
        return ""
    return spec.extract_response(s)

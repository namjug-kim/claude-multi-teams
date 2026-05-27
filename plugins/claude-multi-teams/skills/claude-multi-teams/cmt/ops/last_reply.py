"""cmt last-reply — re-extract the most recent assistant text from jsonl.

Uses ``baseline_offset`` saved by the most recent ask (set just before the
prompt was sent). Returns an empty string if no ask has been made.
"""

from __future__ import annotations

from pathlib import Path

from cmt import extract, state


def last_reply(name: str, state_dir: Path | None = None) -> str:
    s = state.load(name, state_dir=state_dir)
    if s is None:
        raise FileNotFoundError(f"agent {name!r} not found.")
    if s.session_file is None:
        return ""
    session = Path(s.session_file)
    if not session.exists():
        return ""
    return extract.extract_jsonl_assistant(session, baseline_offset=s.baseline_offset)

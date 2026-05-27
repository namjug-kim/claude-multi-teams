"""Tests for codex rollout file discovery.

Codex creates ``~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`` only after the
first prompt. cmt snapshots the sessions root's max-mtime at spawn time, then
on first ask scans for files newer than that snapshot.
"""

import os
import time
from pathlib import Path

from cmt.codex_session import (
    sessions_root,
    snapshot_max_mtime,
    find_new_rollout,
)


def test_sessions_root_default_is_under_home(monkeypatch) -> None:
    monkeypatch.delenv("CODEX_HOME", raising=False)
    monkeypatch.setenv("HOME", "/tmp/fakehome-codex")
    assert sessions_root() == Path("/tmp/fakehome-codex/.codex/sessions")


def test_sessions_root_respects_codex_home(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    assert sessions_root() == tmp_path / "sessions"


def test_snapshot_returns_zero_when_no_rollouts(tmp_path: Path) -> None:
    # Empty sessions tree: snapshot should be 0.0 (no files yet)
    assert snapshot_max_mtime(tmp_path) == 0.0


def test_snapshot_returns_max_mtime_when_files_exist(tmp_path: Path) -> None:
    d = tmp_path / "2026" / "05" / "27"
    d.mkdir(parents=True)
    older = d / "rollout-2026-05-27T10-00-00-aaa.jsonl"
    newer = d / "rollout-2026-05-27T11-00-00-bbb.jsonl"
    older.write_text("{}\n")
    newer.write_text("{}\n")
    # Force ordering via os.utime
    os.utime(older, (1000.0, 1000.0))
    os.utime(newer, (2000.0, 2000.0))
    assert snapshot_max_mtime(tmp_path) == 2000.0


def test_find_new_rollout_returns_file_appearing_after_snapshot(tmp_path: Path) -> None:
    d = tmp_path / "2026" / "05" / "27"
    d.mkdir(parents=True)
    pre = d / "rollout-pre.jsonl"
    pre.write_text("{}\n")
    os.utime(pre, (1000.0, 1000.0))

    marker = snapshot_max_mtime(tmp_path)
    # New rollout appears later
    new = d / "rollout-new.jsonl"
    new.write_text('{"type":"session_meta"}\n')
    os.utime(new, (2000.0, 2000.0))

    found = find_new_rollout(tmp_path, after=marker)
    assert found == new


def test_find_new_rollout_none_when_no_new(tmp_path: Path) -> None:
    d = tmp_path / "2026" / "05" / "27"
    d.mkdir(parents=True)
    (d / "rollout-pre.jsonl").write_text("{}\n")
    marker = snapshot_max_mtime(tmp_path)
    assert find_new_rollout(tmp_path, after=marker) is None


def test_find_new_rollout_picks_newest_when_multiple(tmp_path: Path) -> None:
    d = tmp_path / "2026" / "05" / "27"
    d.mkdir(parents=True)
    marker = snapshot_max_mtime(tmp_path)  # 0
    a = d / "rollout-a.jsonl"
    b = d / "rollout-b.jsonl"
    a.write_text("{}\n")
    b.write_text("{}\n")
    os.utime(a, (1500.0, 1500.0))
    os.utime(b, (2500.0, 2500.0))
    assert find_new_rollout(tmp_path, after=marker) == b


def test_find_new_rollout_handles_missing_root(tmp_path: Path) -> None:
    # Sessions root doesn't exist (first-ever codex launch).
    missing = tmp_path / "never_created"
    assert find_new_rollout(missing, after=0.0) is None


def test_find_new_rollout_polling_window(tmp_path: Path) -> None:
    """Default ``find_new_rollout`` is one-shot. The polling wrapper
    ``wait_for_new_rollout`` blocks until a new file appears or timeout."""
    from cmt.codex_session import wait_for_new_rollout
    import threading

    d = tmp_path / "2026" / "05" / "27"
    d.mkdir(parents=True)
    marker = snapshot_max_mtime(tmp_path)

    def writer():
        time.sleep(0.2)
        p = d / "rollout-late.jsonl"
        p.write_text('{"type":"session_meta"}\n')

    t = threading.Thread(target=writer)
    t.start()
    found = wait_for_new_rollout(tmp_path, after=marker, timeout=2.0, poll_interval=0.05)
    t.join()
    assert found is not None
    assert found.name == "rollout-late.jsonl"


def test_wait_for_new_rollout_times_out(tmp_path: Path) -> None:
    from cmt.codex_session import wait_for_new_rollout

    marker = snapshot_max_mtime(tmp_path)
    found = wait_for_new_rollout(tmp_path, after=marker, timeout=0.3, poll_interval=0.05)
    assert found is None

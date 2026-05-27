"""Tests for the per-agent inbox primitives."""

from __future__ import annotations

import threading
from pathlib import Path

from cmt import inbox


def test_enqueue_returns_message_with_fields(tmp_path: Path) -> None:
    msg = inbox.enqueue(tmp_path, to="alice", content="hello", sender="bob")
    assert msg.to == "alice"
    assert msg.sender == "bob"
    assert msg.content == "hello"
    assert msg.msg_id  # non-empty
    assert msg.ts
    assert msg.replies_to is None


def test_dequeue_returns_oldest_then_deletes(tmp_path: Path) -> None:
    a = inbox.enqueue(tmp_path, to="alice", content="first")
    b = inbox.enqueue(tmp_path, to="alice", content="second")
    got1 = inbox.dequeue(tmp_path, "alice")
    got2 = inbox.dequeue(tmp_path, "alice")
    got3 = inbox.dequeue(tmp_path, "alice")
    assert got1 is not None and got1.content == "first"
    assert got2 is not None and got2.content == "second"
    assert got3 is None


def test_dequeue_empty_returns_none(tmp_path: Path) -> None:
    assert inbox.dequeue(tmp_path, "ghost") is None


def test_enqueue_creates_inbox_dir_lazily(tmp_path: Path) -> None:
    assert not (tmp_path / "inbox" / "alice").exists()
    inbox.enqueue(tmp_path, to="alice", content="x")
    assert (tmp_path / "inbox" / "alice").is_dir()


def test_peek_is_nondestructive(tmp_path: Path) -> None:
    inbox.enqueue(tmp_path, to="alice", content="x")
    inbox.enqueue(tmp_path, to="alice", content="y")
    peeked = inbox.peek(tmp_path, "alice")
    assert [m.content for m in peeked] == ["x", "y"]
    assert inbox.count(tmp_path, "alice") == 2


def test_has_messages(tmp_path: Path) -> None:
    assert inbox.has_messages(tmp_path, "alice") is False
    inbox.enqueue(tmp_path, to="alice", content="x")
    assert inbox.has_messages(tmp_path, "alice") is True
    inbox.dequeue(tmp_path, "alice")
    assert inbox.has_messages(tmp_path, "alice") is False


def test_clear_removes_all(tmp_path: Path) -> None:
    inbox.enqueue(tmp_path, to="alice", content="x")
    inbox.enqueue(tmp_path, to="alice", content="y")
    assert inbox.clear(tmp_path, "alice") == 2
    assert inbox.count(tmp_path, "alice") == 0


def test_concurrent_dequeue_safe(tmp_path: Path) -> None:
    """Two parallel dequeues must NOT return the same message."""
    inbox.enqueue(tmp_path, to="alice", content="only-one")
    results: list = []

    def take():
        results.append(inbox.dequeue(tmp_path, "alice"))

    threads = [threading.Thread(target=take) for _ in range(5)]
    for t in threads: t.start()
    for t in threads: t.join()
    got = [m for m in results if m is not None]
    assert len(got) == 1, f"expected 1 winner, got {len(got)}"


def test_replies_to_preserved(tmp_path: Path) -> None:
    parent = inbox.enqueue(tmp_path, to="alice", content="q")
    inbox.enqueue(tmp_path, to="bob", content="answer", replies_to=parent.msg_id)
    msg = inbox.dequeue(tmp_path, "bob")
    assert msg is not None
    assert msg.replies_to == parent.msg_id


def test_orchestrator_sender_default(tmp_path: Path) -> None:
    msg = inbox.enqueue(tmp_path, to="alice", content="x")
    assert msg.sender == ""  # orchestrator (no name)

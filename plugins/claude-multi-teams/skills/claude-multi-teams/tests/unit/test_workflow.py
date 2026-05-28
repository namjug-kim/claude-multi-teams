"""Workflow layer: role storage, role-aware ask, kv, transcript."""

from __future__ import annotations

from pathlib import Path

from cmt.workflow import ask as wf_ask
from cmt.workflow import kv, role, transcript


# --- role ---

def test_role_set_get_roundtrip(tmp_path: Path) -> None:
    role.set_role("alice", "PRO-MONOREPO advocate", state_dir=tmp_path)
    assert role.get_role("alice", state_dir=tmp_path) == "PRO-MONOREPO advocate"


def test_role_get_missing_is_none(tmp_path: Path) -> None:
    assert role.get_role("ghost", state_dir=tmp_path) is None


# --- role-aware ask prepends identity then delegates to raw ask ---

def test_wf_ask_prepends_role(tmp_path: Path, monkeypatch) -> None:
    role.set_role("alice", "PRO-MONOREPO advocate", state_dir=tmp_path)
    seen = {}
    monkeypatch.setattr(wf_ask.raw_ask, "ask",
                        lambda name, prompt, state_dir=None: seen.update(name=name, prompt=prompt) or "ok")
    wf_ask.ask("alice", "your move", state_dir=tmp_path)
    assert seen["name"] == "alice"
    assert "Your role: PRO-MONOREPO advocate" in seen["prompt"]
    assert seen["prompt"].endswith("your move")


def test_wf_ask_without_role_sends_verbatim(tmp_path: Path, monkeypatch) -> None:
    seen = {}
    monkeypatch.setattr(wf_ask.raw_ask, "ask",
                        lambda name, prompt, state_dir=None: seen.update(prompt=prompt) or "ok")
    wf_ask.ask("alice", "raw prompt", state_dir=tmp_path)
    assert seen["prompt"] == "raw prompt"  # no prelude


# --- kv ---

def test_kv_put_get_with_namespaced_key(tmp_path: Path) -> None:
    kv.put("feature/17/status", "reviewing", state_dir=tmp_path)
    assert kv.get("feature/17/status", state_dir=tmp_path) == "reviewing"


def test_kv_get_missing_is_none(tmp_path: Path) -> None:
    assert kv.get("nope", state_dir=tmp_path) is None


# --- transcript ---

def test_transcript_append_and_tail(tmp_path: Path) -> None:
    transcript.append("debate", "first", frm="alice", state_dir=tmp_path)
    transcript.append("debate", "second", frm="bob", state_dir=tmp_path)
    entries = transcript.tail("debate", state_dir=tmp_path)
    assert [e["content"] for e in entries] == ["first", "second"]
    assert [e["from"] for e in entries] == ["alice", "bob"]
    assert transcript.tail("debate", n=1, state_dir=tmp_path)[0]["content"] == "second"

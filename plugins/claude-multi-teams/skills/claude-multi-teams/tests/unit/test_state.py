import json
from pathlib import Path

import pytest

from cmt import state
from cmt.state import AgentState


def _sample(name: str = "alice") -> AgentState:
    return AgentState(
        name=name,
        agent="claude",
        agent_id="abc123def456",
        pane_id="%23",
        cwd="/tmp/proj",
        started_at="2026-05-27T08:36:42Z",
        session_file="/Users/x/.claude-spare/projects/-tmp-proj/<uuid>.jsonl",
        baseline_offset=0,
    )


def test_validate_name_accepts_slugs() -> None:
    for n in ["a", "alice", "alice-1", "abc-123-def", "z" * 32]:
        state.validate_name(n)  # must not raise


def test_validate_name_rejects_bad() -> None:
    bad = ["", "A", "alice!", "alice space", "/alice", "alice/", "a" * 33, "alice_underscore"]
    for n in bad:
        with pytest.raises(ValueError):
            state.validate_name(n)


def test_save_and_load_roundtrip(tmp_path: Path) -> None:
    s = _sample()
    state.save(s, state_dir=tmp_path)
    loaded = state.load("alice", state_dir=tmp_path)
    assert loaded == s


def test_load_returns_none_for_missing(tmp_path: Path) -> None:
    assert state.load("ghost", state_dir=tmp_path) is None


def test_save_writes_json_at_expected_path(tmp_path: Path) -> None:
    state.save(_sample("bob"), state_dir=tmp_path)
    expected = tmp_path / "agents" / "bob.json"
    assert expected.exists()
    loaded = json.loads(expected.read_text())
    assert loaded["name"] == "bob"
    assert loaded["agent"] == "claude"


def test_list_all_returns_all_saved(tmp_path: Path) -> None:
    state.save(_sample("alice"), state_dir=tmp_path)
    state.save(_sample("bob"), state_dir=tmp_path)
    state.save(_sample("carol"), state_dir=tmp_path)
    names = sorted(s.name for s in state.list_all(state_dir=tmp_path))
    assert names == ["alice", "bob", "carol"]


def test_list_all_empty(tmp_path: Path) -> None:
    assert state.list_all(state_dir=tmp_path) == []


def test_remove_deletes_file(tmp_path: Path) -> None:
    state.save(_sample("alice"), state_dir=tmp_path)
    state.remove("alice", state_dir=tmp_path)
    assert state.load("alice", state_dir=tmp_path) is None


def test_remove_missing_is_idempotent(tmp_path: Path) -> None:
    state.remove("ghost", state_dir=tmp_path)  # must not raise


def test_save_rejects_invalid_name(tmp_path: Path) -> None:
    s = AgentState(
        name="BadName!",
        agent="claude",
        agent_id="x",
        pane_id="%1",
        cwd="/",
        started_at="t",
    )
    with pytest.raises(ValueError):
        state.save(s, state_dir=tmp_path)


def test_save_creates_parent_dir(tmp_path: Path) -> None:
    nested = tmp_path / "deep" / "down"
    # nested doesn't exist yet
    state.save(_sample(), state_dir=nested)
    assert (nested / "agents" / "alice.json").exists()


def test_default_state_dir_uses_env_override(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CMT_STATE_DIR", str(tmp_path / "custom"))
    assert state.default_dir() == tmp_path / "custom"


def test_default_state_dir_fallback(monkeypatch) -> None:
    monkeypatch.delenv("CMT_STATE_DIR", raising=False)
    assert state.default_dir() == Path.home() / ".cache" / "cmt"

"""CLI dispatch tests. Exercises ``python -m cmt`` argparse + op routing.

Goes through the same ops integration path as test_ops.py but enters via main().
"""

import os
import time
from pathlib import Path

import pytest

from cmt.__main__ import main


def test_help_exits_zero(capsys) -> None:
    with pytest.raises(SystemExit) as ei:
        main(["--help"])
    assert ei.value.code == 0
    out = capsys.readouterr().out
    assert "spawn" in out and "ask" in out and "kill" in out


def test_unknown_command_exits_nonzero() -> None:
    with pytest.raises(SystemExit) as ei:
        main(["totally-not-a-command"])
    assert ei.value.code != 0


def test_spawn_via_cli(tmp_path: Path, tmux_server, fake_claude, monkeypatch) -> None:
    monkeypatch.setenv("CMT_STATE_DIR", str(tmp_path / "state"))
    rc = main(["spawn", "claude", "alice", "--cwd", str(tmp_path)])
    assert rc == 0
    from cmt import state
    assert state.load("alice") is not None


def test_ask_via_cli_prints_reply(
    tmp_path: Path, tmux_server, fake_claude, monkeypatch, capsys
) -> None:
    monkeypatch.setenv("CMT_STATE_DIR", str(tmp_path / "state"))
    main(["spawn", "claude", "alice", "--cwd", str(tmp_path)])
    time.sleep(0.3)
    rc = main(["ask", "alice", "ping"])
    assert rc == 0
    captured = capsys.readouterr().out
    assert "echo: ping" in captured


def test_kill_via_cli(
    tmp_path: Path, tmux_server, fake_claude, monkeypatch
) -> None:
    monkeypatch.setenv("CMT_STATE_DIR", str(tmp_path / "state"))
    main(["spawn", "claude", "alice", "--cwd", str(tmp_path)])
    rc = main(["kill", "alice"])
    assert rc == 0
    from cmt import state
    assert state.load("alice") is None


def test_status_of_unknown_prints_dead(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.setenv("CMT_STATE_DIR", str(tmp_path / "state"))
    rc = main(["status", "ghost"])
    assert rc == 0
    assert capsys.readouterr().out.strip() == "dead"


def test_list_empty_via_cli(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("CMT_STATE_DIR", str(tmp_path / "state"))
    rc = main(["list"])
    assert rc == 0
    assert "no agents" in capsys.readouterr().out


def test_list_json_via_cli(
    tmp_path: Path, tmux_server, fake_claude, monkeypatch, capsys
) -> None:
    monkeypatch.setenv("CMT_STATE_DIR", str(tmp_path / "state"))
    main(["spawn", "claude", "alice", "--cwd", str(tmp_path)])
    capsys.readouterr()  # drop "spawned alice..." line
    main(["list", "--json"])
    import json as _json
    data = _json.loads(capsys.readouterr().out)
    assert len(data) == 1 and data[0]["name"] == "alice"


def test_whoami_via_cli_when_unset(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.setenv("CMT_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.delenv("CMT_AGENT_ID", raising=False)
    rc = main(["whoami"])
    assert rc == 1

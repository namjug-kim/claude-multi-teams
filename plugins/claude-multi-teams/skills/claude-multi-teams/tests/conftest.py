import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

# Make the cmt package importable without an install step.
SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR))


_REAL_TMUX = "/opt/homebrew/bin/tmux"


@pytest.fixture
def tmux_server(monkeypatch):
    """Detached real-tmux server on a short /tmp socket.

    Hard-wires the absolute path to homebrew tmux (``/opt/homebrew/bin/tmux``)
    so the fixture NEVER lands on the cmux ``tmux`` shim when tests run inside
    ``cmux claude-teams``. Going through the shim would create real cmux
    panes/workspaces in the user's window — destructive pollution we will not
    tolerate.

    Also rewrites $PATH so cmt.mux's own ``tmux`` subprocess calls (running
    in this same test process) hit real tmux, and clears $CMUX_SOCKET_PATH so
    paste_bracketed takes the real-tmux branch (not the cmux native bypass).
    """
    if not Path(_REAL_TMUX).exists():
        pytest.skip(f"real tmux binary not found at {_REAL_TMUX}")
    shim_dir = str(Path.home() / ".cmuxterm" / "claude-teams-bin")
    paths = ["/opt/homebrew/bin"] + [
        p for p in os.environ.get("PATH", "").split(":")
        if p != shim_dir and p != "/opt/homebrew/bin"
    ]
    monkeypatch.setenv("PATH", ":".join(paths))
    monkeypatch.delenv("CMUX_SOCKET_PATH", raising=False)

    sock = Path(f"/tmp/cmt-test-{os.getpid()}-{time.monotonic_ns()}.sock")
    try:
        subprocess.run(
            [_REAL_TMUX, "-S", str(sock), "new-session", "-d", "-s", "t",
             "-x", "200", "-y", "60", "bash"],
            check=True,
        )
        root_pane = subprocess.run(
            [_REAL_TMUX, "-S", str(sock), "list-panes", "-F", "#{pane_id}"],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
        monkeypatch.setenv("TMUX", f"{sock},0,0")
        monkeypatch.setenv("TMUX_PANE", root_pane)
        yield root_pane
    finally:
        subprocess.run([_REAL_TMUX, "-S", str(sock), "kill-server"], check=False)
        try:
            sock.unlink()
        except FileNotFoundError:
            pass


@pytest.fixture
def fake_codex(tmp_path: Path, monkeypatch):
    """Install a fake codex binary and a sandboxed ``CODEX_HOME``.

    The fake immediately prints the "OpenAI Codex" banner (so the spawn-time
    warmup state machine exits without sending any modal keys), then reads
    pasted prompt lines from stdin (stripping bracketed-paste markers). For
    each prompt it writes one rollout jsonl file in ``$CODEX_HOME/sessions/
    YYYY/MM/DD/rollout-<uuid>.jsonl`` containing:

      - event_msg/task_started
      - event_msg/user_message    (echo of prompt)
      - event_msg/agent_message   (reply text "echo: <prompt>")
      - event_msg/task_complete   (last_agent_message = the same reply)

    Returns a dict with ``bin`` (Path to the fake) and ``home`` (Path to the
    sandboxed CODEX_HOME).
    """
    home = tmp_path / "codex-home"
    home.mkdir()
    script = tmp_path / "fake-codex"
    script.write_text(r'''#!/usr/bin/env python3
import datetime, json, os, re, sys, uuid

# Eat the bypass flags (we don't actually need them for our fake)
for _ in range(len(sys.argv) - 1):
    arg = sys.argv.pop()
    if arg.startswith("--"):
        continue

home = os.environ.get("CODEX_HOME") or os.path.expanduser("~/.codex")
sessions_root = os.path.join(home, "sessions")

# Print banner so post_spawn_warmup sees "OpenAI Codex" and returns immediately.
print("OpenAI Codex (v0.0.0-fake)", flush=True)

bp_re = re.compile(rb"\x1b\[2(00|01)~")
rollout_path = None  # created on first prompt; same file across all turns

for line in sys.stdin.buffer:
    cleaned = bp_re.sub(b"", line).decode("utf-8", "replace").strip()
    if not cleaned:
        continue
    if rollout_path is None:
        now = datetime.datetime.utcnow()
        day_dir = os.path.join(sessions_root, f"{now.year}", f"{now.month:02d}", f"{now.day:02d}")
        os.makedirs(day_dir, exist_ok=True)
        fname = f"rollout-{now.strftime('%Y-%m-%dT%H-%M-%S')}-{uuid.uuid4().hex}.jsonl"
        rollout_path = os.path.join(day_dir, fname)
    reply = f"echo: {cleaned}"
    with open(rollout_path, "a") as f:
        def emit(payload):
            f.write(json.dumps({"type": "event_msg", "payload": payload}) + "\n")
        emit({"type": "task_started"})
        emit({"type": "user_message", "message": cleaned})
        emit({"type": "agent_message", "message": reply})
        emit({"type": "task_complete", "last_agent_message": reply})
    print(reply, flush=True)
''')
    script.chmod(0o755)
    monkeypatch.setenv("CMT_CODEX_BIN", str(script))
    monkeypatch.setenv("CODEX_HOME", str(home))
    return {"bin": script, "home": home}


@pytest.fixture
def fake_claude(tmp_path: Path, monkeypatch):
    """Install a fake claude binary and point ``CMT_CLAUDE_BIN`` at it.

    The fake reads pasted lines from stdin (stripping bracketed-paste markers)
    and writes claude-shaped jsonl events: one ``user`` event and one
    ``assistant`` event with ``stop_reason: end_turn`` per prompt. The reply
    text is always ``"echo: <prompt>"`` for deterministic asserts.
    """
    config_dir = tmp_path / "claude-config"
    config_dir.mkdir()
    script = tmp_path / "fake-claude"
    script.write_text(
        '#!/usr/bin/env python3\n'
        'import json, sys, os, re\n'
        'session_id = None\n'
        'args = sys.argv[1:]\n'
        'while args:\n'
        '    if args[0] == "--session-id":\n'
        '        session_id = args[1]; args = args[2:]\n'
        '    elif args[0] == "--dangerously-skip-permissions":\n'
        '        args = args[1:]\n'
        '    else:\n'
        '        args = args[1:]\n'
        'cwd_dashed = os.getcwd().replace("/", "-")\n'
        'config_dir = os.environ.get("CLAUDE_CONFIG_DIR", os.path.expanduser("~/.claude"))\n'
        'jsonl = f"{config_dir}/projects/{cwd_dashed}/{session_id}.jsonl"\n'
        'os.makedirs(os.path.dirname(jsonl), exist_ok=True)\n'
        'bp_re = re.compile(rb"\\x1b\\[2(00|01)~")\n'
        'for line in sys.stdin.buffer:\n'
        '    cleaned = bp_re.sub(b"", line).decode("utf-8", "replace").strip()\n'
        '    if not cleaned:\n'
        '        continue\n'
        '    with open(jsonl, "a") as f:\n'
        '        f.write(json.dumps({"type": "user", "message": {"role": "user", "content": cleaned}}) + "\\n")\n'
        '        f.write(json.dumps({"type": "assistant", "message": {\n'
        '            "role": "assistant",\n'
        '            "content": [{"type": "text", "text": f"echo: {cleaned}"}],\n'
        '            "stop_reason": "end_turn",\n'
        '        }}) + "\\n")\n'
    )
    script.chmod(0o755)
    monkeypatch.setenv("CMT_CLAUDE_BIN", str(script))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config_dir))
    return {"bin": script, "config_dir": config_dir}

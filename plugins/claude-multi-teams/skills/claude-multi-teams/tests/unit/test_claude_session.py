"""claude session-file path derivation must match claude's own slug, which
is built from the *canonical* (symlink-resolved) cwd."""

from __future__ import annotations

import os
from pathlib import Path

from cmt import agents


def test_claude_session_file_resolves_symlinked_cwd(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
    real = tmp_path / "real_project"
    real.mkdir()
    link = tmp_path / "link_project"
    link.symlink_to(real)

    ctx = agents.SpawnContext(name="a", agent_id="id", cwd=str(link),
                              session_uuid="uuid123")
    got = agents._claude_session_file(ctx, {})

    canonical_slug = os.path.realpath(str(link)).replace("/", "-")
    assert f"/projects/{canonical_slug}/uuid123.jsonl" in got
    assert canonical_slug.endswith("real_project")   # resolved to the target
    assert "link_project" not in got                 # not the symlink name

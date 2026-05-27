"""Sanity-level wiring tests for the agy AgentSpec.

Full ops-against-fake-binary tests are intentionally not included here:
agy uses ANSI cursor positioning to overwrite the bottom status line in
place, so a faithful fake would need to drive tmux's renderer to simulate
the working→done flip. We rely on the unit-level coverage in test_agy_screen
+ test_agy_warmup for the logic, and on tests/smoke/smoke_agy.sh for the
ops-level e2e against real agy.
"""

from cmt import agents


def test_agy_registered() -> None:
    assert "agy" in agents.AGENTS


def test_agy_argv_includes_skip_permissions() -> None:
    spec = agents.AGENTS["agy"]
    ctx = agents.SpawnContext(name="a", agent_id="id", cwd="/tmp", session_uuid="")
    argv = spec.build_argv(ctx)
    assert argv[0].endswith("agy")
    assert "--dangerously-skip-permissions" in argv


def test_agy_session_file_is_always_none() -> None:
    spec = agents.AGENTS["agy"]
    ctx = agents.SpawnContext(name="a", agent_id="id", cwd="/tmp", session_uuid="")
    assert spec.session_file(ctx, {}) is None


def test_agy_has_warmup_and_dispatch_hooks() -> None:
    spec = agents.AGENTS["agy"]
    assert spec.post_spawn_warmup is not None
    assert spec.await_done is not None
    assert spec.status_fn is not None
    assert spec.extract_response is not None
    # agy is screen-based — no rollout/session-file resolver needed.
    assert spec.resolve_session_file is None


def test_agy_env_prefixes_include_gemini() -> None:
    # agy talks to Google Gemini under the hood; propagate the relevant env.
    spec = agents.AGENTS["agy"]
    assert any("GEMINI_" == p or "GOOGLE_" == p for p in spec.propagate_env_prefixes)

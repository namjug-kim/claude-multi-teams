# 0008 — Per-agent `CODEX_HOME` to isolate rollout discovery

**Status:** Accepted (2026-05-29)

## Context

Codex, unlike claude, has no `--session-id` flag: it names its own rollout
file (`rollout-<iso>-<uuid>.jsonl`) and only writes it *after* the first
prompt. cmt discovered that file by snapshotting the max-mtime of
`$CODEX_HOME/sessions` at spawn (the `spawn_marker`), then on the first ask
scanning the **whole shared sessions tree** for the newest rollout with
`mtime > marker` (`codex_session.find_new_rollout`).

This is unambiguous for one codex at a time — exactly one new rollout appears.
It breaks under concurrency. Dogfooding a multi-team review with 10+ codex
agents in one shared `$CODEX_HOME` produced:

- answers **cross-wired** to the wrong pane,
- **byte-identical duplicate** replies across agents,
- some panes left **dead** (bound to a file that wasn't theirs).

Root cause: with N concurrent first-asks, N rollout files land in the same
`sessions/YYYY/MM/DD/` within milliseconds. Every agent scans the *same*
global root and several resolve to the *same* newest file. "Newest mtime in a
shared dir" is not a unique key per pane.

claude never has this problem: `--session-id <uuid>` makes its jsonl path
deterministic (ADR context in `agents.py`). This ADR gives codex an equivalent
guarantee without a flag codex doesn't offer.

This is the third sibling-concurrency cross-wire fixed in cmt, after the shared
tmux paste-buffer (ADR-0007 context) and the cmux CLI daemon race (ADR-0004).

## Decision

Give each codex pane its **own `CODEX_HOME`** at
`<state_dir>/codex-home/<agent_id>`, injected via a new `AgentSpec.spawn_env`
hook (which overrides the propagated `CODEX_*` env). The home is seeded to
behave exactly like the real one:

```
seed_agent_home(home, source):
    symlink every top-level entry of `source` into `home`   # auth, config,
                                                            # skills, hooks, …
    EXCEPT `sessions/`, which becomes a real empty dir
```

The single carve-out — a private real `sessions/` — is the whole isolation.
Everything else stays shared by symlink, so codex behaves identically to the
old single-home setup. Discovery now scans only this agent's private tree, so
the one rollout that appears is unambiguous regardless of how many siblings
spawn at once.

The home path is **derived** from `(state_dir, agent_id)`, both known at spawn
and at the first ask, so no new `AgentState` field is needed. `SpawnContext`
gained a `state_dir` so the codex hooks can compute it.

`cmt kill` removes the per-agent home (`shutil.rmtree`, best-effort). Its
entries are symlinks — rmtree drops the links, not the real `~/.codex` files;
only the private `sessions/` rollouts (no longer needed once the pane is gone)
are real.

## Why mirror the whole home, not just symlink auth + config?

A real `~/.codex` carries far more than credentials — `config.toml`, `hooks`,
`rules`, `skills`, `plugins`, `memories`, sqlite state. Cherry-picking auth +
config would silently change codex behavior for every spawned agent.
Symlinking everything-but-`sessions` is no worse than today's fully-shared
home for those files and fixes only the thing that needs fixing.

## Why not content-correlation (match our prompt in the rollout)?

We considered binding by "the rollout whose first user `input_text` equals the
prompt we just sent." It fixes the fan-out case (distinct prompts) but still
collides when several agents are sent the *same* prompt — exactly the
consensus / debate pattern cmt is built for. Isolation is collision-proof
regardless of prompt content.

## Consequences

- **Per-spawn cost:** create a dir + a handful of symlinks (no copies). Trivial
  against codex startup.
- **Auth-refresh nuance:** if codex rewrites `auth.json` via tmp+rename, the
  rename replaces the symlink with a real file in the private home, so a
  refreshed token isn't written back to the shared home. Acceptable for
  short-lived sibling panes; the next spawn re-symlinks from the (possibly
  stale) shared home.
- **`spawn_marker` is now usually `0.0`** (the private sessions tree starts
  empty). It's kept as a guard against any pre-existing file.
- **No behavior change for claude/agy** — `spawn_env` is codex-only.

# 0002 — Dual mux backend: real tmux and cmux native CLI

**Status:** Accepted (2026-05-27)

## Context

cmt has to run in two host environments:

1. **Real tmux.** Standard developer shell with `$TMUX` pointing at a real
   tmux server socket. Splits / paste-buffer / send-keys / capture-pane
   all work as documented.
2. **cmux claude-teams.** A cmux-managed terminal session where `$TMUX`
   starts with `/tmp/cmux-claude-teams/...` and the `tmux` binary on PATH
   is a **shim** (`~/.cmuxterm/claude-teams-bin/tmux`) that translates a
   subset of tmux commands into cmux ones.

We need ``cmt spawn alice`` to produce a pane the user can see and switch
to in *both* environments — i.e., a real tmux pane in case 1, and a real
cmux surface in the sidebar in case 2.

### Why we can't just use the tmux shim everywhere

We tried. The shim:

- ``split-window`` creates a **shim-only pseudo-pane** invisible to cmux's
  UI. The pane exists for the shim's bookkeeping but the user never sees
  it. (The point of running inside cmux is the sidebar.)
- ``paste-buffer -p`` does not deliver real bracketed paste to the
  receiving TUI; markers appear as literal text in the agent's prompt
  buffer.

Confirmed empirically — Path A ("just use tmux") fails in cmux claude-teams.

## Decision

cmt picks the backend per-call based on `$TMUX`:

```python
def _use_cmux_native() -> bool:
    return os.environ.get("TMUX", "").startswith("/tmp/cmux-claude-teams")
```

- If True → call the **cmux native CLI** directly (`cmux new-pane`,
  `cmux paste-buffer`, `cmux send-key`, `cmux capture-pane`,
  `cmux close-surface`, `cmux list-pane-surfaces`).
- Otherwise → call the **tmux CLI** directly.

Each mux primitive (`split_pane`, `paste_bracketed`, `send_keys`,
`capture`, `pane_alive`, `list_panes`, `kill_pane`) has a `_tmux_*` and a
`_cmux_*` implementation; the public function dispatches on
`_use_cmux_native()`.

Pane ids are stored in their mux-native form: `%23` / `%<uuid>` for real
tmux, `surface:<N>` for cmux. The downstream code treats them as opaque
identifiers.

### Key-name translation

tmux and cmux use different syntaxes for modifier keys (`C-u` vs
`ctrl+u`, `Enter` vs `enter`, etc.). The cmux backend has a small
translation table (`_TMUX_TO_CMUX_KEY`) so callers can speak tmux syntax
uniformly.

### Bracketed paste on the cmux backend

`cmux set-buffer --name <buf> -- <text>` then
`cmux paste-buffer --name <buf> --surface <pane>`. Native bracketed
paste — the receiving TUI sees real BPS markers, agents read prompts
cleanly without corruption.

## Why not abstract the shell layer

We considered building one "AbstractMux" interface with two
implementations. Rejected — the primitive set is small enough (~9 ops),
and the per-op behavior is divergent enough (different flag semantics,
different capture modes, different key syntaxes), that a single-file
dispatch with `_tmux_*` / `_cmux_*` pairs is more legible than an
abstract interface plus two adapters.

## Consequences

- **Plain cmux without `claude-teams` is NOT a supported host.** Its pty
  env lacks the identifiers a spawned worker needs.
- **Smoke coverage is split.** `smoke_claude.sh` / `smoke_phase2.sh` test
  real-tmux paths against a freshly-started tmux server; `smoke_cmux.sh`
  / `smoke_codex.sh` / `smoke_agy.sh` test cmux paths against the user's
  actual cmux session.
- The cmux CLI was found to be **non-reentrant for concurrent
  invocations** during a parallel-ask demo. See [[0004-cmux-cli-serialization]].

# 0009 — `kill` never closes the pane cmt runs in

**Status:** Accepted (2026-05-29)

## Context

cmt persists each agent's pane id in its state file. Under the cmux backend
that id is the `surface:N` ref returned by `cmux new-pane` (`"OK surface:58
pane:53 …"`). `surface:N` is a **volatile positional ref**: cmux reassigns the
number as surfaces open and close. The only stable per-surface identifier is a
UUID (`$CMUX_SURFACE_ID`), and the cmux CLI does **not** expose it —
`list-pane-surfaces --json` returns `index` / `ref` / `selected` / `title`,
no UUID.

So a state file can outlive the pane it describes, and its stored `surface:N`
can later point at a *different* pane — including the user's main / orchestrator
pane. `cmt kill` trusted that ref and ran `cmux close-surface --surface
surface:N`, so a stale entry could close an unrelated live pane.

This bit hard during dogfooding: a `cmt kill --all` against the default state
dir (which had accumulated real agents) closed panes whose recycled refs now
pointed elsewhere, taking down the main pane — the session had to be resumed.
tmux `%`-ids are recyclable the same way, so this is not cmux-specific.

PR #1 (`d4bf057`) addressed the *empty / malformed / cross-backend* arm of this:
`close-surface` (and the input/capture ops) fall back to the **focused** surface
only when `--surface` is empty or unresolvable, so it added `_is_cmux_surface`
(require `^surface:\d+$`) plus a kill-time `pane_alive()` check. Its commit body
names the remaining gap explicitly: *"the recycled-but-live `surface:N` case
needs identity verification and is left as follow-up."* This ADR is that
follow-up — a well-formed, live `surface:N` that has been recycled onto a
*different* real pane passes every check `d4bf057` added, yet `close-surface`
will faithfully close that real pane.

## Decision

On top of `d4bf057`'s guards, make it a hard invariant: **`kill` and `kill
--all` never close the pane cmt is running in** — the cheapest identity check
that closes the recycled-but-live gap for the one pane that matters most.

- `mux.current_pane()` returns that pane — tmux: `$TMUX_PANE`; cmux: the ref of
  the `selected` surface from `list-pane-surfaces --json` (cmux gives a process
  no ref to its *own* surface, only the UUID, so the focused surface is the
  usable proxy — and when cmt is driven interactively that *is* the orchestrator
  pane).
- `kill <name>` **raises** if the target's `pane_id` matches the current pane —
  loud, because an explicit single kill landing on the current pane means a
  stale/recycled id, not a real teardown.
- `kill --all` **skips** the current-pane entry (leaves it tracked) and tears
  down the rest, then warns on stderr. One poisoned entry must neither take down
  the orchestrator nor abort the sweep.

## Why not fix the root — store a stable id instead of a volatile ref?

That's the real cure, but cmux's CLI doesn't surface a stable per-surface id to
its owning process, can't enumerate UUIDs to map a ref→UUID, and has no
settable per-surface title cmt could stamp as an ownership marker (titles are
set by the agent TUI, not us). With the available surface, the orchestrator-pane
guard is the protection we *can* guarantee, and it covers the catastrophic case.

## Consequences

- **Residual risk:** a stale ref pointing at a *non-current, non-cmt* pane can
  still be closed — the guard only protects the pane cmt runs in. Mitigate by
  not letting the shared default state dir accumulate dead agents (kill agents
  when done; prefer a scoped `$CMT_STATE_DIR` for throwaway fleets).
- **`kill --all` may leave one entry** (the current-pane match) tracked. That's
  intentional; it's almost certainly stale and removing it would mean closing
  the orchestrator. Clean it manually if real.
- **No behavior change** for the normal case — agents live in their own panes,
  never the orchestrator's, so the guard is a no-op.

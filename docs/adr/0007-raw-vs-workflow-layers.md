# 0007 — Raw vs workflow layers; minimal delivery, no daemon

**Status:** Accepted (2026-05-28)

## Context

A 3-agent debate demo (alice/bob/carol arguing monorepo vs polyrepo)
exposed two delivery failures:

- **Role swap.** Parallel `cmt ask` calls swapped agents' prompts —
  alice argued the position assigned to bob.
- **Role drift.** Agents "forgot" their assigned stance across turns.

That prompted a design pass (worked through with a codex sibling) on
whether cmt needed a heavier substrate: shared state stores, a
first-class workflow object, an event bus, per-actor locks, an
`ask --timeout` / resume mechanism, even a daemon. The question was how
much of that to build now versus defer.

Two root causes turned out to be mechanism bugs, not architecture gaps:

- The role swap was tmux's **shared default paste-buffer** — one ask's
  `set-buffer` clobbered another's before its `paste-buffer` fired
  (cmux already avoided this with named buffers, [[0004-cmux-cli-serialization]]).
- A follow-on hang was a **bracketed paste + immediate Enter race** — the
  Enter landed mid-paste, got swallowed, and the prompt sat unsent while
  `ask` blocked forever waiting for a turn that never started.

## Decision

**1. Split `cmt` into two layers sharing one binary.**

- **Raw layer** (`cmt <verb>`) — pure agent manipulation. `cmt ask`
  sends a prompt verbatim and injects nothing.
- **Workflow layer** (`cmt wf <verb>`) — multi-agent composition: role,
  kv (world state), transcript (history), the actor extension
  (enqueue / dequeue / inbox, moved here from the foundation,
  [[0006-actor-inbox-primitives]]), and a role-aware `wf ask` that
  prepends the agent's role then delegates to raw ask.

**2. Fix the demo failures with the minimal mechanism.**

- Named per-pane paste buffer (mirror cmux) — kills the swap.
- `ask` confirms the turn actually started (jsonl grew past baseline /
  status `working`) and re-presses Enter if not — kills the hang.
- `wf ask` prepends the role — kills the drift.
- `.calls` markers record `owner_pid` and self-heal when the owner is
  dead — a crashed/Ctrl-C'd ask no longer pins the target `TargetBusy`
  forever.

## What we deliberately did NOT build

The point of this ADR. A future reader hitting multi-agent races should
reach for these primitives first, not assume the heavier machinery is
missing by oversight:

- **No daemon.** cmt stays an invocation-based CLI over flatfile state,
  preserving [[0001-python-runtime]] / [[0002-mux-dual-backend]] (no
  server, mux shelled out) and keeping all state inspectable on disk. A
  detached-watcher experiment confirmed a background process *can* hold
  an `flock` past caller exit, so the daemon-free async option stays
  open — it is unbuilt, not impossible.
- **No async delivery** (`ask --timeout`, `ask-resume`, per-ask durable
  records, a turn watcher). Every target workflow is blocking: the
  orchestrator drives one phase at a time, parallel asks each block in
  their own shell process holding their own target mutex. Timeout/resume
  solves "fire a long ask, stop waiting, collect later" — a workflow we
  do not yet have.
- **No auto-routing of context.** Passive store / active flow: a
  workflow script reads the stores and embeds context into prompts
  itself; the only thing injected automatically is the role, by
  `wf ask`. Auto-routing would have *hidden* exactly the kind of bug the
  role swap was — silent delivery of the wrong content.
- **No workflow object** (`cmt workflow init/...`). `CMT_STATE_DIR` per
  run already isolates a workflow's agents and stores.
- **No event bus.** A single blocking orchestrator sequences phases
  directly; cross-process triggers are not needed yet.
- **No DSL.** Workflows are plain shell composing the primitives.

## Consequences

- **Raw `ask` is now pure.** Callers needing identity stability use
  `wf ask`. (An earlier iteration auto-prepended role inside raw `ask`;
  reverted so the raw layer injects nothing.)
- **The raw surface stays small** — 12 manipulation verbs — matching the
  foundation's stated minimalism, while multi-agent composition has a
  clear home under `wf`.
- **Deferred features are de-risked, not designed out.** The
  timeout/resume/event-stream design and the watcher-feasibility finding
  are recorded for when a genuinely non-blocking workflow needs them; the
  decision here is sequencing, not rejection.

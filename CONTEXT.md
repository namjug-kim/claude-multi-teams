# Glossary

Project terminology. Implementation-free. Update as grill resolves more terms.

## Agent

An AI CLI (one of: `claude`, `codex`, `agy`) running as a long-lived,
interactive TUI process inside a mux pane. v1 ships exactly these three.

An agent is **not** a one-shot invocation (`claude -p`, `agy --print`); those
modes are explicitly out of scope. The unit is "a CLI sitting in a pane,
waiting for the next prompt".

## Mux (multiplexer)

The host environment that owns panes. Two are in scope, with two backends:

- **Real tmux**       — `$TMUX` set, talks to a tmux server. Uses the `tmux`
  CLI directly.
- **cmux claude-teams** — `$TMUX` starts with `/tmp/cmux-claude-teams/`.
  The cmux `tmux` shim is on PATH but we bypass it. Reason: the shim's
  ``split-window`` creates *shim-only pseudo-panes* invisible to cmux's UI,
  and its ``paste-buffer -p`` does not deliver real bracketed paste to the
  receiving TUI. Instead the framework calls `cmux` (the native CLI)
  directly — `cmux new-pane`, `cmux paste-buffer`, `cmux send-key`,
  `cmux capture-pane`, `cmux close-surface`. Spawned panes ARE real cmux
  surfaces, visible in the sidebar.

Backend is selected per-call by `mux._use_cmux_native()` (one env-prefix
check). Pane ids are stored in their mux-native form: `%<UUID>`/`%<N>` for
real tmux, `surface:<N>` for cmux.

Plain cmux (without `claude-teams`) is **not** a mux for our purposes — its
pty env lacks the identifiers a spawned worker needs to recognize itself.

## Pane

A mux-managed terminal region. Hosts exactly one agent. Created by `spawn`,
torn down by `kill`. Identified by the mux-native pane id (e.g. tmux `%23`).

## Spawn

Create a pane, launch an agent in it with the agent-appropriate
permission-bypass flag (so tool-permission modals do not block automated
prompting), and record bookkeeping needed to drive it later.

## Prompt / Ask

A single turn: send text to an agent and recover the agent's reply.

## Response retrieval channel

How an agent's reply is recovered from its pane. Per-agent:

| agent | channel | done marker |
|---|---|---|
| `claude` | jsonl session file tail (`~/.claude/projects/.../<uuid>.jsonl`) | terminal `stop_reason` event |
| `codex`  | jsonl rollout file tail (new file per session, mtime-detected) | terminal `stop_reason` event |
| `agy`    | `tmux capture-pane -p -S - -E -` (full scrollback) + parse turn block between `> <prompt>` line and the next `─{40,}` divider | bottom status-line flip `esc to cancel` → `? for shortcuts` |

claude/codex are jsonl-based (exact text, structured events). agy has no
consumable file trail (`.pb` conversation files are opaque binary), so its
channel is the rendered TUI screen and its done marker is a string flip.

## Permission modal

A TUI dialog an agent shows when it wants approval (tool call, dangerous
edit, etc.). v1 sidesteps these by launching every agent with the
agent-appropriate skip-permissions flag, so they should not appear by
default. The framework must still expose general send-keys / send-text /
capture primitives so a caller can drive an arbitrary modal if one ever
surfaces.

## Runtime

Python only (target version TBD). No bash scripts, no shell-based glue.

Mux operations are still shelled out (`subprocess` against `tmux` /
`paste-buffer` / `capture-pane` / etc.) — `tmux` is the only third-party
CLI dependency.

## Foundation primitives (v1 surface)

The foundation exposes exactly the operations below — **12 core** primitives
that every workflow uses, plus **3 actor-model extension** primitives added
when multi-agent P2P / consensus patterns came online. Additions to either
set require explicit grill.

### Lifecycle

| op | role |
|---|---|
| `spawn` | create a pane, start an agent with permission-bypass flags, inject a self-id env var (`CMT_AGENT_ID=<uuid>`), record a state file. Returns the agent's stable id. |
| `kill` | tear down a pane and drop its state. |
| `list` | enumerate currently tracked agents (JSON output). |

### Input

| op | role |
|---|---|
| `send-prompt` | bracketed-paste text into a pane, then press Enter. The framework's main "give the agent something to do" primitive. |
| `send-keys` | send an arbitrary key sequence (`Enter`, `Down`, `Esc`, `Tab`, etc). Used for modal navigation when a permission/survey modal slips past the permission-bypass default. |

### Output / observation

| op | role |
|---|---|
| `capture` | read pane screen as plain text. Modes: visible / full-scrollback (default) / wrap-joined (tmux `-J`, important for agy where long indented response lines wrap at terminal width). |
| `extract-response` | return the agent's last reply as a clean string. Per-agent parser: jsonl assistant-message walk for claude/codex, `> <prompt>` … `─{40,}` block for agy. |

### State detection

| op | role |
|---|---|
| `agent-status` | one-shot read: returns `working` / `done` / `blocked`. Per-agent detector (status-line flip for agy; jsonl `stop_reason` for claude/codex; body pattern match for `blocked`). |
| `wait-status` | block until `agent-status` reaches a target value, with timeout. |
| `wait-output` | block until pane text matches a regex/substring, with timeout. Used for: warm-up (agent banner appearance after spawn), modal-pattern detection, partial-response sentinel watching. |

### Composite

| op | role |
|---|---|
| `ask` | the foundation's main user-facing op. Atomic: load state → `send-prompt` → `wait-status(done)` → `extract-response` → return text. If `blocked` reached, surface to caller (do not auto-dismiss in v1; caller decides kill / send-keys / escalate). |

### Self-identification

| op | role |
|---|---|
| `whoami` | when invoked from inside a spawned pane, resolve `$CMT_AGENT_ID` → state file → return that agent's own metadata. Lets a spawned agent identify itself and reach sibling agents. |

### Actor-model extension (added 2026-05-27 for P2P / consensus)

| op | role |
|---|---|
| `enqueue` | fire-and-forget write to an agent's inbox at `$STATE_DIR/inbox/<agent>/<ts>-<uuid>.json`. Returns immediately. Used by a scheduler to deliver one-way messages without blocking. |
| `dequeue` | atomically take the oldest pending inbox message for an agent (FIFO by ts prefix; `rename` to claim). Returns nothing when empty (rc=1). |
| `inbox` | peek or `--clear` an agent's inbox. Diagnostic / scheduler aid. |

`ask` and the actor ops solve different problems: `ask` is the natural
"please answer this now" verb and blocks until the agent responds, with
cycle/mutex guards (see [Deadlock safety](#deadlock-safety) below).
`enqueue` + `dequeue` are the building blocks of a non-blocking
scheduler — agents process messages one at a time on their own turns,
no agent ever waits on another, so the wait-for graph is empty by
construction and deadlock is structurally impossible.


## Deadlock safety

Two layers, depending on which P2P pattern a workflow uses:

1. **Sync (`cmt ask` from inside a spawned pane).** Before sending the
   prompt, the call records its chain at
   `$STATE_DIR/.calls/<target>.json` using atomic `O_CREAT|O_EXCL`. The
   file holds the chain of agent names leading up to the call AND
   doubles as a per-target mutex.
   - **`CycleDetected`** if the target already appears in that chain
     (would create a wait-for cycle).
   - **`TargetBusy`** if a different call against the same target is
     in flight (atomic create fails).
   - **`DepthExceeded`** if the chain length exceeds `DEFAULT_MAX_DEPTH`
     (6 by default).
2. **Actor (`cmt enqueue` / `cmt dequeue`).** Agents never block on
   each other; a scheduler routes messages between inboxes one at a
   time. There is no wait-for relationship to deadlock.

Workflows pick a layer: short interactive debates do well with the sync
layer (faster, more natural turn-taking); long-running or many-agent
workflows that must survive crashes/restarts use the actor layer
(deadlock-proof, audit-friendly transcript).


## Per-agent spawn specifics (verified by demo, 2026-05-27)

| concern | claude | codex | agy |
|---|---|---|---|
| invocation flags | `--session-id <uuid4>` `--dangerously-skip-permissions` | `--ask-for-approval never` | `--dangerously-skip-permissions` |
| session/response file | predictable path; framework globs `~/.claude-spare/projects/*/<uuid>.jsonl` (appears ~0.3s after first prompt) | rollout file at `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`; framework caches max-mtime before spawn, detects new mtime after first prompt (~0.5s) | none tracked — `.pb` files don't persist for short sessions and are opaque even if they did; capture-pane is the only channel |
| warm-up signal | jsonl file existing | jsonl file appearing after first prompt | bottom status-line shows `? for shortcuts` (banner is misleading: appears ~4s before agent is actually ready to accept paste) |
| spawn-time modals | none observed (theme picker may appear on first-ever launch — handle when seen) | sequence of up to 3 modals: Update-available (`Down Enter` to skip) → Trust-folder (`Enter` for Yes) → Hooks-review (`Down Down Enter` to skip) — order conditional on environment state | none under permission-skip flag (survey modal may appear after a tool decline — handle when seen) |
| spawn-time modal handler shape | a small polling state machine — capture screen, match a known modal pattern, send the right key sequence, loop until banner detected. Same shape for all agents; only patterns differ. |

The `--ask-for-approval never` (codex) and `--dangerously-skip-permissions`
(claude/agy) flags suppress in-conversation tool-approval modals, but
**not spawn-time modals** (update notice, trust folder, hooks review,
survey). Spawn-time modal handling is required for every agent.

## Permission model

All agents launched with their agent-appropriate skip-permissions flag.
Default-path tool permission modals do not appear, so `ask` does not need
to navigate them.

If a modal does appear (agent version change, an unforeseen survey
modal, etc.), the framework reflects this as `agent-status == blocked`.
The framework never auto-clicks. The caller (workflow or human) decides
the response, using `send-keys` to drive the modal explicitly.

## CLI surface

Single binary `cmt`. Subcommand tree, one verb per primitive op:

```
cmt spawn <agent> <name> [--cwd DIR] [--replace]
cmt kill <name> | --all
cmt list [--json]
cmt ask <name> "prompt" | @file | -
cmt send <name> "text" [--no-enter]
cmt keys <name> KEY [KEY ...]
cmt capture <name> [--mode visible|full|wrapped]
cmt last-reply <name>
cmt status <name>
cmt wait-status <name> <target>
cmt wait-output <name> --match REGEX [--text]
cmt whoami [--json]

cmt enqueue <target> "msg" [--sender NAME] [--replies-to ID] [--json]
cmt dequeue <agent> [--json]
cmt inbox   <agent> [--clear] [--json]
```

Outputs: human-readable by default; `--json` flag where structured output
is useful. `cmt ask` prints reply text on stdout only (no JSON wrapping —
keeps `reply=$(cmt ask alice "...")` ergonomic).

## Liveness and timeouts

The framework imposes **no wall-clock or idle timeout on `cmt ask`**. It
blocks until the agent reports `done`, `dead`, or `blocked`. Callers
needing a cap wrap with shell `timeout` themselves.

`cmt status` is the liveness primitive:

| status | meaning |
|---|---|
| `working` | agent alive and busy on the current turn |
| `done` | agent alive and idle; last reply ready to extract |
| `blocked` | agent alive but waiting on a modal (a tool/permission/survey dialog has appeared despite skip flags) |
| `dead` | pane process gone or agent crashed |

`cmt ask` polls `status` internally. `done` returns the reply, `dead`
raises an error, `blocked` surfaces the modal text (the caller decides
the response with `send`/`keys` or chooses to kill). It never auto-aborts
on silence — quiet thinking is indistinguishable from a hang at this
layer, and the framework prefers to wait rather than guess.

## Agent name rules

- charset: `[a-z0-9-]{1,32}` (slug). Strict for pane title / state file /
  log id safety.
- conflict on spawn: explicit error with the next action printed.
  `--replace` for intentional overwrite (kills the existing agent first).

## Out of scope (intentionally)

- Multi-level hierarchy (workspace > tab > pane) — flat agent list only.
- Focus / layout direction / no-focus splits — framework picks any split,
  caller does not control geometry.
- Session detach/reattach / persistent server — owned by the host mux
  (tmux or cmux claude-teams), not re-implemented here.
- Native pty management or agent-specific hook subscriptions — we read
  agent state via mux capture + jsonl tail, not by binding to agent
  internals.

## Workflow (forward reference — not in foundation scope)

A bounded multi-agent run with a clear start and end. Examples:

- 3 agents discuss until consensus reached (short workflow — minutes)
- 1 implementer + 1 reviewer + 1 tester cycling until a feature is shipped
  (long workflow — possibly days or weeks)

Each workflow is one logical "flow". When the workflow phase is designed
it will introduce the flow concept: how a flow is named, where its
events live, how spawned sibling agents inherit the flow id, how a flow
ends. Foundation phase ships none of this; it only ships the agent
primitives a workflow would call into.

Specifically: foundation does **not** write any cross-call observability
log. There is no `flow.log` or events file under `~/.cache/cmt/`.
Per-flow logging is a workflow concern.

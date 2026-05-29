# claude-multi-teams

A multi-agent harness for running **claude**, **codex**, and **agy**
(Antigravity / Gemini) side by side as long-lived TUI workers inside a
terminal multiplexer. The `cmt` CLI gives you 15 primitives — spawn,
ask, kill, status, wait-status, capture, message-passing — and works
identically in real **tmux** and in **`cmux claude-teams`** (which uses
its native CLI under the hood).

Built for the workflow where you want a second (or third) AI in the
loop: an independent reviewer, a parallel investigator, a P2P
discussion until consensus is reached.

## Installation

This repo is a Claude Code **marketplace** with one plugin (`claude-multi-teams`).

```
/plugin marketplace add https://github.com/namjug-kim/claude-multi-teams
/plugin install claude-multi-teams@claude-multi-teams-marketplace
```

For local development against the working copy:

```
/plugin marketplace add /path/to/claude-multi-teams
/plugin install claude-multi-teams@claude-multi-teams-marketplace
```

## Quick start

From a tmux or `cmux claude-teams` session:

```bash
CMT=plugins/claude-multi-teams/skills/claude-multi-teams/bin/cmt

$CMT spawn claude alice
$CMT spawn codex  bob
$CMT spawn agy    carol

reply=$($CMT ask alice "review foo.py and flag the top issue")
echo "$reply"

$CMT kill --all
```

## The 15 primitives

The 12 **foundation** ops (every workflow uses these):

```
cmt spawn <agent> <name> [--cwd DIR] [--replace]
cmt kill  <name> | --all
cmt list  [--json]

cmt ask         <name> "prompt"          # send + wait-done + return reply
cmt send        <name> "text" [--no-enter]
cmt keys        <name> KEY [KEY ...]
cmt capture     <name> [--mode visible|full|wrapped]
cmt modal       <name> [--json]          # parse a blocking selection modal (rc=1 if none)
cmt last-reply  <name>

cmt status       <name>                  # working | done | blocked | dead
cmt wait-status  <name> <target>
cmt wait-output  <name> --match REGEX [--text]

cmt whoami       [--json]                # called from inside an agent's pane
```

The 3 **actor-model extensions** for deadlock-proof P2P / consensus
patterns:

```
cmt enqueue <target> "msg" [--sender NAME] [--replies-to ID]
cmt dequeue <agent>
cmt inbox   <agent> [--clear]
```

## Agents

| name   | CLI it drives             | response channel |
|--------|---------------------------|------------------|
| claude | Anthropic Claude Code CLI | per-session jsonl (`~/.claude/projects/.../<uuid>.jsonl`) |
| codex  | OpenAI codex CLI          | rollout jsonl (`~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`) — mtime-detected after first prompt |
| agy    | Google Antigravity CLI    | `tmux capture-pane` — bottom status line + `> <prompt>` … `─{5,}` divider block |

All three launch with their respective skip-permissions flags. Each has
a small spawn-time modal handler (Trust folder, etc.) — see
[`docs/adr/0003`](docs/adr/0003-agy-screen-channel.md) and the
per-agent specifics in [`CONTEXT.md`](CONTEXT.md).

## Multiplexer support

`cmt` autodetects which backend to use:

- **Real tmux** (`$TMUX` set, not pointing at cmux's fake path): calls the
  `tmux` CLI directly.
- **cmux claude-teams** (`$TMUX` starts with `/tmp/cmux-claude-teams/` *or*
  `$CMUX_SOCKET_PATH` is set, which is the case inside any cmux-spawned
  pane): bypasses the tmux shim and calls the `cmux` native CLI
  (`new-pane`, `paste-buffer`, `send-key`, `capture-pane`,
  `close-surface`). Spawned panes appear as real surfaces in the cmux
  sidebar.

Concurrent cmux calls are serialized via a host-wide flock on
`/tmp/cmt-cmux.lock` to avoid races. See
[`docs/adr/0002`](docs/adr/0002-mux-dual-backend.md) and
[`docs/adr/0004`](docs/adr/0004-cmux-cli-serialization.md).

## P2P safety

A spawned agent can ask its siblings via `cmt ask <other>` from its own
Bash tool. Two failure modes are blocked automatically:

- **`CycleDetected`** — if a nested `cmt ask` would re-enter an agent
  already in the calling chain. Prevents `A→B→A` style deadlocks at the
  primitive level.
- **`TargetBusy`** — atomic per-target mutex. Two concurrent calls
  against the same agent: one wins, the other gets a clear error.

For long-running workflows where you want a structurally deadlock-proof
pattern, use the actor extension (`enqueue` / `dequeue`) — agents never
block on each other; a scheduler routes messages between inboxes one at
a time. See [`docs/adr/0005`](docs/adr/0005-callchain-cycle-prevention.md)
and [`docs/adr/0006`](docs/adr/0006-actor-inbox-primitives.md).

## State

All harness state lives at `$CMT_STATE_DIR` (default `~/.cache/cmt`):

```
agents/<name>.json         # one file per spawned worker
.calls/<target>.json       # per-target in-flight marker (sync P2P guard)
.cmt-cmux.lock             # host-wide cmux CLI serialization (/tmp, not state)
inbox/<agent>/<ts>.json    # actor-model message queue
```

Per-flow workspaces should set their own `CMT_STATE_DIR` to isolate.

## Requirements

- Python 3.10+
- a multiplexer environment — real **tmux** (`$TMUX` set) or a Claude Code
  launched via **`cmux claude-teams`**
- the agent CLI(s) you intend to drive on `$PATH` (`claude`, `codex`, `agy`)

## License

MIT (set later if/when this gets published broadly — for now treat as
personal/team use).

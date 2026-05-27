# claude-multi-teams

A multi-agent harness for Claude Code (and codex), running inside a terminal
multiplexer. Spawn worker panes, hand them prompts, capture replies through
their session jsonl, fan out to several reviewers in parallel, run impl ↔
review loops, and visualize the call tree.

claude-multi-teams works in real **tmux** sessions and in **cmux** terminals when you
launch your primary Claude Code via `cmux claude-teams` — cmux ships a tmux
shim that translates the tmux CLI into its native surface API, so claude-multi-teams
talks the same protocol in either environment. See "Multiplexer support" below.

This plugin packages the `claude-multi-teams` skill — a single skill plus its bash
runtime (`lib/`, `scripts/`).

## Installation

This repo is a Claude Code **marketplace** with one plugin (`claude-multi-teams`).

```
/plugin marketplace add https://github.com/namjug-kim/claude-multi-teams
/plugin install claude-multi-teams@claude-multi-teams-marketplace
```

For local development (before pushing changes), point at the working copy
directly:

```
/plugin marketplace add /path/to/claude-multi-teams
/plugin install claude-multi-teams@claude-multi-teams-marketplace
```

## Skill

| Skill | What it does |
|---|---|
| `claude-multi-teams` | Spawn / ask / fan out / review against tmux-resident agents |

After install, invoke from any Claude Code session inside tmux (or inside a
`cmux claude-teams` session — see "Multiplexer support" below):

```
/claude-multi-teams ...
```

See `skills/claude-multi-teams/SKILL.md` for the full surface.

## Scripts (runtime)

The skill drives bash scripts. Available manually if you need them outside
the skill prompts:

| Script | Purpose |
|---|---|
| `spawn.sh` | Create a pane with a named claude/codex worker |
| `ask.sh` | Send a prompt and block until the worker replies |
| `ask-skill.sh` | Like `ask.sh` but forces a real `/<skill>` slash invocation |
| `ask-group.sh` | P2P discussion router (@mention based) until consensus / deadlock |
| `review.sh` | impl ↔ N reviewers loop for a configurable number of rounds |
| `last-reply.sh` | Recover the most recent reply from the session jsonl |
| `list.sh` | Show all spawned workers + status |
| `kill.sh` | Tear down a worker's pane and state |
| `viewer.sh` | ASCII call tree from `flow.log` |
| `viewer-html.sh` | Pretty browser view, optional `--watch` auto-refresh |
| `viewer-md.sh` | Markdown view (intended to be pasted into a parent's reply) |

## Requirements

- `bash` 3.2+ (macOS compatible)
- a multiplexer environment — real **tmux** (`$TMUX` set) or a Claude Code
  launched via **`cmux claude-teams`** (which provides a tmux-compatible shim)
- `jq`, `python3`
- `claude` CLI (Anthropic) and/or `codex` CLI (OpenAI) on `$PATH`

## Multiplexer support

claude-multi-teams drives panes through the tmux CLI in both supported environments:

- **Real tmux**: `lib/mux-tmux.sh` calls the real `tmux` server. Native paste
  via `paste-buffer -p` (server-atomic bracketed paste).
- **cmux claude-teams**: cmux's launcher installs a tmux shim
  (`~/.cmuxterm/claude-teams-bin/tmux` → `cmux __tmux-compat`) that translates
  the tmux CLI into cmux's surface API. The shim has no `load-buffer`, but
  cmux's *native* CLI does: claude-multi-teams detects `$CMUX_SOCKET_PATH`
  and routes its bracketed paste through `cmux set-buffer` + `cmux paste-buffer
  --surface <uuid>` (cmux's paste implementation simulates bracketed paste
  internally). The buffer name is per-pane, so repeated pastes overwrite a
  single buffer instead of leaking one per call (cmux has no `delete-buffer`).

To use under cmux, launch your primary Claude with:

```
cmux claude-teams
```

For an isolated config dir (e.g. `claude-spare` workflow):

```
CLAUDE_CONFIG_DIR=$HOME/.claude-spare cmux claude-teams
```

`CLAUDE_*` / `ANTHROPIC_*` envs propagate to every spawned worker
automatically.

## State

All harness state lives at `$ALPHAFORK_STATE_DIR` (default
`~/.cache/claude-multi-teams`):

- `agents/<name>.json` — one file per spawned worker
- `flow.log` — append-only call trace (jsonl)
- `handoff/` — long prompts handed to codex via file
- `flow.html` — viewer-html output (when used)

## License

MIT (set later if/when this gets published broadly — for now treat as
personal/team use).

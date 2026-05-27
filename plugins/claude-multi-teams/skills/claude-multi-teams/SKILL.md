---
name: claude-multi-teams
description: Spawn and drive sibling AI CLI agents (claude / codex / agy) in long-lived tmux or cmux panes via the `cmt` CLI. Use when the user asks to coordinate a second AI for review / parallel investigation / writing+reviewing / "ask another model" — or when *you* (the assistant) decide a different model would handle a subtask better. Provides 12 foundation primitives (spawn / kill / list / ask / send / keys / capture / last-reply / status / wait-status / wait-output / whoami) and works in both real tmux and `cmux claude-teams`.
allowed-tools: Bash
---

# claude-multi-teams (cmt)

A foundation for running other AI CLI agents as worker panes alongside your
own Claude Code session. Spawn one or more sibling agents, ask them
questions, observe their state, and collect their replies — all from
the shell via `cmt`.

## When to use this skill

Reach for `cmt` when the user (or your own task plan) needs another LLM
in the loop:

- "Have codex look at this and tell me if it's correct."
- "Ask another model what it'd do."
- "Run gemini in parallel and compare answers."
- "Spawn a reviewer, then iterate until it's satisfied."
- "I want a second pair of eyes — independent context."

Do **not** use `cmt` for things you can do in this session yourself
(simple file edits, single-turn questions, tasks where a fresh
conversation has no value). The point is sibling agents with their own
context window, not extra invocations of the same model.

## Where `cmt` lives

The binary is at:

```
plugins/claude-multi-teams/skills/claude-multi-teams/bin/cmt
```

It's a shell stub that forwards to `python -m cmt.__main__`. Run by
absolute path or `cd` into the skill directory and use `./bin/cmt`.

Setup before first use (in your shell environment):

- Make sure `$TMUX_PANE` is set (you are inside a tmux or cmux pane).
- Optionally export `CMT_STATE_DIR=<dir>` to isolate agent state to a
  workflow-specific directory. Defaults to `~/.cache/cmt`.

## The three agents

| name   | what it is               | invocation flag(s) cmt uses |
|--------|--------------------------|------------------------------|
| claude | Anthropic claude CLI     | `--session-id <uuid> --dangerously-skip-permissions` |
| codex  | OpenAI codex CLI         | `--dangerously-bypass-approvals-and-sandbox --dangerously-bypass-hook-trust` |
| agy    | Google Antigravity CLI   | `--dangerously-skip-permissions` |

All three are launched with their respective permission-bypass flags so
in-conversation tool prompts don't block automated asks. Spawn-time
modals (Trust folder, etc.) are handled automatically.

## The 12 primitives

```
cmt spawn <agent> <name> [--cwd DIR] [--replace]
cmt kill  <name> | --all
cmt list  [--json]

cmt ask         <name> "prompt"          # send + wait-done + return reply
cmt send        <name> "text" [--no-enter]
cmt keys        <name> KEY [KEY ...]     # Enter / Esc / Tab / Up / C-u / ...
cmt capture     <name> [--mode visible|full|wrapped]
cmt last-reply  <name>                   # re-extract most recent reply

cmt status       <name>                  # working | done | blocked | dead
cmt wait-status  <name> <target>
cmt wait-output  <name> --match REGEX [--text]

cmt whoami       [--json]                # from inside a spawned pane → self lookup
```

### `cmt ask` is the main verb

```
$ cmt spawn codex bob
spawned bob (agent=codex, pane=surface:103)

$ cmt ask bob "Is this regex anchored correctly? \n\n^[a-z]+$"
Yes, that pattern is anchored on both ends ...
```

Atomically: send the prompt → poll until the agent's turn is done →
return the assistant text on stdout. **No timeout** — `cmt ask` blocks
until the agent reports `done`, `dead`, or `blocked`. Callers wanting a
wall-clock cap wrap with shell `timeout`.

### Multi-agent flows

Sibling agents can be asked sequentially or in parallel. Parallel works
correctly under both backends (cmux CLI calls are flock-serialized
internally, so concurrent asks don't race):

```bash
cmt spawn claude alice
cmt spawn codex  bob
cmt spawn agy    carol

# parallel
(cmt ask alice "summarize foo.py"  > /tmp/a &)
(cmt ask bob   "review foo.py"     > /tmp/b &)
(cmt ask carol "what tests are missing in foo.py?" > /tmp/c &)
wait

cmt kill --all
```

### `cmt whoami` — self-identification from inside an agent

A spawned agent receives `CMT_AGENT_ID` + `CMT_STATE_DIR` in its
environment. If the agent uses its shell tool to run `cmt whoami`, it
gets back its own name + agent type + pane id + stable id. This lets a
spawned worker call sibling workers (look up `cmt list`, then
`cmt ask <other-name> "..."`).

## Important rules

1. **`cmt ask` has no timeout.** If you suspect an agent is hung, use
   `cmt status <name>` to check. A `dead` status means the pane process
   is gone; `blocked` means a modal appeared that the agent's
   `--skip-permissions` flag didn't catch.
2. **Names are slugs**: `[a-z0-9-]{1,32}`. Conflicts on spawn raise an
   error unless `--replace` is passed.
3. **State files** live under `$CMT_STATE_DIR/agents/<name>.json`. A
   workflow that wants its own namespace should set `CMT_STATE_DIR`
   before any `cmt` calls.
4. **Permission bypass is per-agent at spawn time.** Inside a spawned
   pane, the agent runs in its respective "skip approvals" mode. Treat
   spawned agents accordingly — don't `cmt spawn` an agent for code you
   wouldn't trust.

## Status / liveness

| status   | meaning                                                         |
|----------|-----------------------------------------------------------------|
| working  | agent alive and busy on the current turn                        |
| done     | agent alive and idle; last reply ready to extract               |
| blocked  | agent alive but waiting on a modal (rare; mostly bypassed)      |
| dead     | pane process gone or agent crashed                              |

`cmt wait-status <name> done` blocks until the target status is reached.
Useful in shell scripts to fence steps.

## Capture modes

| mode    | content                                                          |
|---------|------------------------------------------------------------------|
| visible | currently visible viewport (cheap; for status line checks)       |
| full    | full scrollback + visible (for agy response extraction; default) |
| wrapped | scrollback with line wrap joined (for long indented agy lines)   |

`cmt last-reply` already does the right thing per-agent; reach for
`cmt capture` only when you need raw pane text (e.g., to inspect a
modal the agent is showing).

## Anti-patterns

- **Don't poll `cmt status` in a tight loop.** Use `cmt wait-status` or
  `cmt wait-output`, which poll efficiently inside cmt.
- **Don't `cmt ask` an agent that's still working on the previous
  turn.** `cmt ask` already serializes via the `done` gate, but
  `cmt send` + `cmt keys` do not — those are raw primitives.
- **Don't re-`cmt spawn` an existing agent without `--replace`.** It
  errors, intentionally. `--replace` kills the old pane first.

## Where to learn more

- `CONTEXT.md` at the repo root — living glossary of the framework's
  vocabulary.
- `docs/adr/` — design records: python runtime, mux dual-backend, agy
  screen channel, cmux CLI serialization.
- `tests/smoke/smoke_{claude,codex,cmux,agy,phase2}.sh` — readable
  end-to-end examples of every primitive.

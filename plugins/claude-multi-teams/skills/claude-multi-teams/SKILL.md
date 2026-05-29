---
name: claude-multi-teams
description: Spawn and drive sibling AI CLI agents (claude / codex / agy) in long-lived tmux or cmux panes via the `cmt` CLI. Use when the user asks to coordinate a second AI for review / parallel investigation / writing+reviewing / "ask another model" — or when *you* (the assistant) decide a different model would handle a subtask better. Provides 13 foundation primitives (spawn / kill / list / ask / send / keys / capture / modal / last-reply / status / wait-status / wait-output / whoami) plus 3 actor-model extensions (enqueue / dequeue / inbox) for deadlock-proof P2P / consensus flows. Works in both real tmux and `cmux claude-teams`.
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

## The primitives

Two layers in one binary. **Raw layer** (`cmt <verb>`) is pure agent
manipulation — `cmt ask` sends a prompt verbatim. **Workflow layer**
(`cmt wf <verb>`) composes several agents: role, kv, transcript, the actor
extension, and a role-aware ask.

```
# raw layer
cmt spawn <agent> <name> [--cwd DIR] [--replace]
cmt kill  <name> | --all
cmt list  [--json]

cmt ask         <name> "prompt"          # send verbatim + wait-done + reply
cmt send        <name> "text" [--no-enter]
cmt keys        <name> KEY [KEY ...]     # Enter / Esc / Tab / Up / C-u / ...
cmt capture     <name> [--mode visible|full|wrapped]
cmt modal       <name> [--json]          # parse a blocking selection modal (rc=1 if none)
cmt last-reply  <name>                   # re-extract most recent reply

cmt status       <name>                  # working | done | blocked | dead
cmt wait-status  <name> <target>
cmt wait-output  <name> --match REGEX [--text]

cmt whoami       [--json]                # from inside a spawned pane → self lookup

# workflow layer
cmt wf role set <name> "role"            # stable identity for the agent
cmt wf role get <name>
cmt wf ask  <name> "prompt"              # prepend role, then raw ask
cmt wf put  <key> "value"  / cmt wf get <key>          # KV: world state
cmt wf log  append <topic> "text" [--from NAME]        # transcript: history
cmt wf log  tail   <topic> [--n N] [--json]
cmt wf enqueue <target> "msg" [--sender NAME] [--replies-to ID]  # actor: FIFO
cmt wf dequeue <agent>                                           # atomic take
cmt wf inbox   <agent> [--clear]                                 # peek / drain
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

### P2P (agent-to-agent) and deadlock safety

`cmt ask` from inside a spawned agent's Bash tool lets that agent call
its siblings directly. Two failure modes are blocked automatically — you
do not need to design around them:

| error            | when it fires | what to do |
|------------------|---------------|------------|
| `CycleDetected`  | A asks B asks A — the second `cmt ask alice` is rejected because alice already appears in the calling chain | redesign the flow to be acyclic, or use actor pattern |
| `TargetBusy`     | Two `cmt ask <X>` calls overlap for the same target | wait or retry; only one outstanding ask per agent |
| `DepthExceeded`  | Chain length exceeds the default cap (6) | likely a runaway recursion — break the chain |

For long-running or many-agent flows where the cycle guard is too
restrictive, use the **actor pattern** instead — agents never call each
other directly; a scheduler writes to inboxes:

```bash
# scheduler routes one message at a time, no agent blocks on another
cmt wf enqueue alice "Topic: <something>. Reply with AGREE/DISAGREE/POSITION/INTENT."
while true; do
  for n in alice bob carol; do
    msg=$(cmt wf dequeue $n --json 2>/dev/null) || continue
    reply=$(cmt wf ask $n "$msg")
    # fan reply out to other inboxes, append to transcript, etc.
  done
  # break when all inboxes empty
done
```

This is the deadlock-proof pattern: the wait-for graph is empty by
construction.

### `cmt whoami` — self-identification from inside an agent

A spawned agent receives `CMT_AGENT_ID` + `CMT_STATE_DIR` in its
environment. If the agent uses its shell tool to run `cmt whoami`, it
gets back its own name + agent type + pane id + stable id. This lets a
spawned worker call sibling workers (look up `cmt list`, then
`cmt ask <other-name> "..."`).

## Workflow recipes

These are the higher-level patterns the foundation primitives compose
into. Reach for these first when the user asks for a named pattern
("토론 돌려봐", "review loop", "consensus") — don't reinvent.

### Multi-agent debate (actor-model) — `cmt-debate`

One bundled helper, lives next to `cmt`:

```
bin/cmt-debate "<topic>" --spawn               # spawn defaults + run
bin/cmt-debate "<topic>"                       # against already-spawned agents
bin/cmt-debate "<topic>" --keep                # leave agents up after
bin/cmt-debate "<topic>" --agents alice,bob    # custom subset
```

What it does: seeds alice / bob / carol with the topic in an
AGREE / DISAGREE / POSITION / INTENT structured format, then loops a
scheduler — dequeue one message per agent, dispatch via `cmt ask`, fan
the reply back out via `cmt enqueue` to the other inboxes. Stops when
every inbox is empty (natural consensus) or hits `MAX_ROUNDS=6`. A
neutral `judge` (claude) reads the transcript and prints a verdict.

Transcript saved to `$CMT_STATE_DIR/debate-<ts>.log`.

When *not* to use the helper: if you need custom round structure
(e.g., 1 round position + 1 round rebuttal only), or non-default
agents, or you want to inspect intermediate state — do it inline:

```bash
cmt spawn claude alice && cmt spawn codex bob && cmt spawn agy carol

# round 1: each takes a position, in parallel
( cmt ask alice "<topic> — position" > /tmp/r1-alice & )
( cmt ask bob   "<topic> — position" > /tmp/r1-bob   & )
( cmt ask carol "<topic> — position" > /tmp/r1-carol & )
wait

# round 2: each rebuts the other two, sequentially so they see each other
cmt ask alice "Rebut these: bob=$(cat /tmp/r1-bob), carol=$(cat /tmp/r1-carol)"
# ... etc

cmt kill --all
```

The point: **don't write a `.sh` file for ad-hoc demos**. Either call
`cmt-debate` for the canned pattern, or run the primitives inline with
parallel Bash tool calls.

### Reviewer loop (one agent reviews until satisfied)

```bash
cmt spawn codex reviewer
reply=$(cmt ask reviewer "Review foo.py. Reply DONE on its own line when satisfied, else list issues.")
while ! grep -q '^DONE$' <<< "$reply"; do
  # ... fix the issues ...
  reply=$(cmt ask reviewer "Re-review foo.py.")
done
cmt kill reviewer
```

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

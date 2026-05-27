# 0006 — Actor-model inbox primitives (enqueue / dequeue / inbox)

**Status:** Accepted (2026-05-27)

## Context

`cmt ask` is synchronous — the caller blocks until the target's turn
finishes. With cycle prevention ([[0005-callchain-cycle-prevention]])
that becomes safe for short interactive debates, but it has structural
limits for the longer kind of workflow this framework wants to support:

- A multi-hour "implement → review → test" loop where each agent runs
  many turns over the course of a day.
- A consensus-style debate where the natural pattern is *each agent
  reads the current state, contributes one turn, hands off*. Sync
  ask-pyramids of any depth blow up.
- Workflows that should survive a crash / interruption / scheduler
  restart — re-pickup from a transcript without losing in-flight work.

We want a model where:

- Agents are **workers**: they take a message off their inbox, run one
  LLM turn against it, optionally emit messages to other agents'
  inboxes, and return.
- A **scheduler** decides who runs next (round-robin, priority,
  whatever the workflow needs) by dispatching dequeued messages via
  `cmt ask`.
- No agent ever blocks on another. The wait-for graph is empty by
  construction; deadlock is structurally impossible.

This is the standard actor / message-passing pattern, recast to fit
the cmt foundation.

## Decision

Add three CLI verbs and a backing module (`cmt/inbox.py`):

```
cmt enqueue <target> "msg" [--sender NAME] [--replies-to ID]
cmt dequeue <agent>                    # rc=1 if empty; rc=0 + body to stdout
cmt inbox   <agent> [--clear] [--json] # peek / drain
```

Storage: one file per pending message at
`$STATE_DIR/inbox/<agent>/<ts>-<uuid8>.json`. The timestamp prefix gives
lexicographic = FIFO order; the uuid suffix de-collides within a single
millisecond.

`dequeue` is atomic via `Path.rename` — two readers cannot claim the
same message; the loser gets `FileNotFoundError` on the rename and
skips. The race is bounded and self-resolving:

```python
for f in sorted(d.glob("*.json")):
    taken = f.with_suffix(".taken")
    try:
        f.rename(taken)            # only one rename wins
    except FileNotFoundError:
        continue                   # another reader got this one
    data = json.loads(taken.read_text())
    taken.unlink()
    return Message(**data)
```

Schema (`cmt.inbox.Message`):

| field        | meaning |
|--------------|---------|
| `msg_id`     | uuid4 hex, stable across rename |
| `to`         | target agent name (redundant with directory, kept for portability) |
| `sender`     | sender agent name, or `""` for orchestrator |
| `content`    | message body |
| `replies_to` | optional `msg_id` of the parent message (for threading / audit) |
| `ts`         | ISO 8601 UTC, sortable |

`cmt ask` and the actor verbs **coexist**. A scheduler typically uses
both: `dequeue` to take work, `ask` to dispatch the LLM turn,
`enqueue` to fan replies back out.

### Demoed end-to-end

`/tmp/actor_debate.py` (scheduler) + 3 agents (alice / bob / carol) +
the same refactoring-PR topic from the mediator-pattern demo. The
scheduler seeded each inbox once, then looped:

1. For each agent: `cmt dequeue` (skip if empty).
2. `cmt ask <agent>` with the inbox message + current transcript tail.
3. Parse `INTENT:` — `continue` → fan reply out to other inboxes;
   `done` → stop forwarding from this agent.
4. Append the (agent, reply) pair to `$STATE_DIR/transcript.log`.

Termination: when every inbox was empty in a round. A judge agent
spawned at the end synthesized the verdict: **Reached** in 9 turns
across 4 rounds, 131s wallclock (vs ~30s for the equivalent
mediator-style debate — the trade-off we expected).

## Why not put a scheduler in cmt itself

The foundation gives primitives; the scheduler is a workflow concern.
The same inbox/dequeue/enqueue verbs support multiple scheduling
strategies (round-robin, priority queues, judges, voting) — we don't
want to hard-code one. Workflow-phase helpers will package useful
patterns as scripts, leaving the foundation small.

## Consequences

- **Deadlock-proof multi-agent flows are possible from the
  foundation.** A scheduler that never lets an agent call another
  agent directly cannot deadlock — `cmt ask` only runs from the
  scheduler, never recursively from inside an agent's turn.
- **Audit transcripts are natural.** `inbox/<agent>/` is the durable
  message log; the scheduler typically also writes a `transcript.log`
  for human reading. Both survive crashes.
- **Slower than the sync mediator pattern.** Each message is one
  scheduler tick + one LLM turn; an N-round debate is `N × agents`
  sequential turns instead of `N × parallel`. Measured: ~4× slower for
  the same consensus. Acceptable for the workflows that need it.
- **The sync layer is still the right default for short debates.**
  Workflows pick: `cmt ask` for quick agent-to-agent calls (with
  cycle/mutex guards from [[0005-callchain-cycle-prevention]]),
  `enqueue` + `dequeue` for long-running or large-fanout flows that
  must survive restarts.

# 0005 — Cycle prevention + per-target mutex for `cmt ask`

**Status:** Accepted (2026-05-27)

## Context

A spawned agent can call `cmt ask <other>` from its own Bash tool —
that's the only way real agent-to-agent (P2P) conversation can happen
inside the framework. But the synchronous nature of `cmt ask` (it
blocks until the target's turn finishes) gives that capability a sharp
edge: the wait-for graph can contain cycles, and a cycle is a
deadlock.

Concretely, two failure modes appeared as soon as we ran multi-agent
demos:

1. **Cycle**. alice's turn calls `cmt ask bob`. bob's turn calls
   `cmt ask alice`. Alice is still in her turn, blocked on bob. Bob
   is blocked on alice. Both wait forever.
2. **Parallel mutex.** Two `cmt ask alice` from sibling shells (e.g.,
   from a parallel fanout) interleave their `paste-buffer` + `wait`
   on alice's pane. Sometimes both reads attribute the same reply to
   different callers; sometimes the second paste lands during the
   first's `wait` and confuses the jsonl-tail strategy.

We considered:

- **Just rely on workflow discipline.** The user designs flows that
  avoid cycles. Fragile — a coding-agent's Bash tool will happily try
  what looks reasonable and silently hang.
- **Timeout-based deadlock detection.** If a turn doesn't finish in
  N seconds, treat as deadlock and fail. False positives on legit slow
  turns; doesn't help with parallel-mutex.
- **In-process mutex.** Doesn't cross process boundaries — sibling
  shells / nested cmt invocations need cross-process serialization.

## Decision

Track every in-flight `cmt ask` in a state file
`$STATE_DIR/.calls/<target>.json`, created via atomic
`O_CREAT|O_EXCL`. The file contents are the chain of agent names
leading up to the call; the file's existence is the mutex.

```python
# cmt/callchain.py — sketch
def acquire(target, state_dir):
    caller = name_for(os.environ.get("CMT_AGENT_ID"))  # None if orchestrator
    chain  = read_chain_of(caller) if caller else []
    if target in chain:                       raise CycleDetected(chain + [target])
    if len(chain) + 1 > MAX_DEPTH:            raise DepthExceeded(chain + [target])
    try:
        atomic_write(target.calls_file, chain + [target])
    except FileExistsError:                   raise TargetBusy(read_chain_of(target))
```

Three failure modes surfaced cleanly:

- **`CycleDetected`** — chain would re-enter an agent. Reject *before*
  the second paste touches the pane.
- **`TargetBusy`** — atomic create fails because someone else owns the
  in-flight marker. Caller decides retry / give up.
- **`DepthExceeded`** — chain length over the configured cap (default
  6). Catches runaway recursion even if cycle-detection misses
  something subtle.

`acquire` is paired with `release` in a `try/finally` inside
`ops/ask.ask()`, so the file is cleaned up on success, failure, or
crash of the python process. (Crashes leave a stale file; manual
cleanup is acceptable for now — `$STATE_DIR/.calls/` is small.)

### Why a file, not a lock daemon

- **Cross-process by construction.** Multiple `cmt` invocations from
  different shells coordinate through the shared filesystem.
- **Self-documenting.** The file's contents are the chain — `cat
  $STATE_DIR/.calls/alice.json` shows exactly who is currently calling
  alice. Diagnosing a hang is a glance at a directory.
- **Atomic on POSIX.** `O_CREAT|O_EXCL` gives the mutex semantics
  without a separate lockfile per se.

### Why a per-target file, not a single global lock

A single global lock would serialize every `cmt ask` across the
session, killing the parallelism we already got from per-call flocks
on the cmux CLI. Per-target locks let alice + carol be called in
parallel cleanly while still preventing two callers from interleaving
on the same agent.

## Consequences

- **Sync P2P is safe.** Verified live: a deliberate `alice → bob →
  cmt ask alice` was rejected with chain
  `['alice', 'bob', 'alice']` before bob's Bash could touch alice's
  pane.
- **Parallel fanout to the same target now errors clearly** instead
  of corrupting state — two `cmt ask alice` calls: one wins, the
  other gets `TargetBusy: alice is already being called (chain: ['alice'])`.
- **Workflow code stays simple.** The cycle guard makes "let agents
  call each other freely" a safe default; only acyclic call graphs
  are even attempted, and the error message tells the caller why.
- **It does NOT detect all deadlocks.** Specifically, a non-cyclic
  but resource-contended scenario (A→B and C→B simultaneously, B is
  already in turn) raises `TargetBusy` for the loser instead of
  proceeding, which is the right call but technically a degradation
  of throughput. For the deadlock-proof-by-construction model, use the
  actor extension (see [[0006-actor-inbox-primitives]]).
- **Long-running flows want the actor model** anyway — the sync layer
  is for short interactive debates; multi-hour flows should not block
  shells on `cmt ask`.

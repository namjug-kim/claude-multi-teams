# 0004 — Serialize cmux CLI calls with a host-wide flock

**Status:** Accepted (2026-05-27)

## Context

A live demo ran three agents in parallel — `cmt ask alice` (claude),
`cmt ask bob` (codex), `cmt ask carol` (agy) — fired simultaneously
from one shell with `&` and `wait`. Two of the three failed:

```
subprocess.CalledProcessError: Command
  ['cmux', 'paste-buffer', '--name', 'cmt-surface-102', '--surface', 'surface:102']
  returned non-zero exit status 1.
```

A retry showed all three reporting "pane is dead" — `cmux capture-pane
--lines 1` (used by `_cmux_pane_alive`) returned non-zero even though
the surfaces were demonstrably alive in the sidebar.

Each cmt process used a distinct buffer name (`cmt-surface-<id>`), so the
failure wasn't buffer-name collision. The race is in the cmux CLI ↔
daemon channel itself when sibling CLIs hit it concurrently.

Sequential asks always worked; the failure was 100% concurrency-induced.

## Decision

Wrap every invocation of the cmux binary in a per-call host-wide
`fcntl.flock` on `/tmp/cmt-cmux.lock`:

```python
lock_fd = os.open(_CMUX_LOCK_PATH, os.O_CREAT | os.O_RDWR, 0o600)
try:
    fcntl.flock(lock_fd, fcntl.LOCK_EX)
    return subprocess.run(["cmux", *args], **kwargs)
finally:
    fcntl.flock(lock_fd, fcntl.LOCK_UN)
    os.close(lock_fd)
```

The lock is held only for the duration of a single subprocess, so
operations on different panes don't block each other beyond the short
window the CLI itself takes (~10–50ms).

After the change, the same parallel demo succeeded:

```
alice: ALPHA-2
bob:   BETA-2
carol: GAMMA-2
```

The 5-smoke parallel run (`smoke_claude` + `smoke_phase2` + `smoke_cmux`
+ `smoke_codex` + `smoke_agy` simultaneously) finishes in ~25s instead
of ~90s sequentially, all five green.

## Why a host-wide lock, not in-process?

cmt processes are *separate* — a workflow that runs `cmt ask` from
multiple shells (or as separate background jobs) needs cross-process
serialization. `threading.Lock` would only help within one Python
interpreter. `flock` on a file works across processes and across shells
on the same host.

## Why not retry-on-failure instead?

Retries could mask the underlying race but would:

- Add latency variance (a retry adds 100ms+ on each ask),
- Need to know *which* errors are racey vs real (cmux exit codes don't
  distinguish), and
- Still hit the race on every ask under load — only resolving it after N
  attempts.

Serialization is constant-cost and predictable.

## Why not patch cmux?

It might be the right long-term answer, but it's upstream and not in our
control. The lock is a 10-line workaround inside our `_cmux` helper —
contained, removable if cmux gains its own concurrency safety.

## Consequences

- **Per-call lock add ~1ms overhead per cmux invocation.** Trivial against
  any LLM round-trip.
- **Throughput is bounded** — two simultaneous `cmt` processes won't
  parallelize their cmux CLI hits, but they *will* parallelize the parts
  that don't go through cmux (e.g. await_jsonl_done's file polling for
  claude/codex). The end-to-end wallclock gain remains substantial; the
  3.6× speedup on the 5-smoke parallel run is the measurement.
- **The lock file lives at `/tmp/cmt-cmux.lock`** — created on first use,
  no cleanup needed (the lock is released on process exit even on
  crashes, and the file itself is harmless).
- Only the **cmux** backend is locked. `_tmux` calls are unlocked — real
  tmux doesn't have the same daemon-race issue under sibling CLI usage.

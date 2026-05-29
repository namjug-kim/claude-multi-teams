# Architecture Decision Records

Short, dated records of the major irreversible design choices in cmt.
The format is "context → decision → consequences" — light enough to
write before the decision rather than after.

| #    | title                                                   | when       |
|------|---------------------------------------------------------|------------|
| 0001 | [Python as the only runtime](0001-python-runtime.md)    | 2026-05-27 |
| 0002 | [Dual mux backend (tmux + cmux native CLI)](0002-mux-dual-backend.md) | 2026-05-27 |
| 0003 | [agy response retrieval via screen capture](0003-agy-screen-channel.md) | 2026-05-27 |
| 0004 | [Serialize cmux CLI calls with flock](0004-cmux-cli-serialization.md) | 2026-05-27 |
| 0005 | [Cycle prevention + per-target mutex for `cmt ask`](0005-callchain-cycle-prevention.md) | 2026-05-27 |
| 0006 | [Actor-model inbox primitives](0006-actor-inbox-primitives.md) | 2026-05-27 |
| 0007 | [Raw vs workflow layers; minimal delivery, no daemon](0007-raw-vs-workflow-layers.md) | 2026-05-28 |
| 0008 | [Per-agent `CODEX_HOME` to isolate rollout discovery](0008-codex-home-isolation.md) | 2026-05-29 |
| 0009 | [`kill` never closes the pane cmt runs in](0009-kill-never-closes-current-pane.md) | 2026-05-29 |

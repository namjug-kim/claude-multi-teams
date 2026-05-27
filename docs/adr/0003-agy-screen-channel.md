# 0003 — agy response retrieval via screen capture

**Status:** Accepted (2026-05-27)

## Context

claude and codex both write structured jsonl session files to disk
(`~/.claude-spare/projects/.../*.jsonl`, `~/.codex/sessions/.../rollout-*.jsonl`).
For those, "is the turn done?" and "what did the assistant say?" are
both answered by tailing the file.

agy (Antigravity CLI 1.0.2) does not give us that. Its conversation files
under `~/.antigravity/` are:

- **opaque binary blobs** (`.pb` — protobuf) that we'd have to decode
  using an unstable internal schema, and
- **not persisted for short sessions** — empirically the file isn't even
  written for many one-shot interactions.

We need *some* channel.

## Decision

For agy, the response channel is the rendered TUI itself, accessed via
`tmux capture-pane -p -S - -E -` (or its cmux equivalent).

### Done detection

agy renders a status line at the bottom of the screen:

| screen state           | bottom line marker  |
|------------------------|---------------------|
| idle, ready for input  | `? for shortcuts`   |
| a turn is in progress  | `esc to cancel`     |

`status_from_screen(screen, pane_alive)` returns:

- `dead` if `pane_alive` is False
- `working` if `esc to cancel` is in the captured text
- `done` otherwise

`await_done(capture, is_alive)` polls until `? for shortcuts` is present
**and** `esc to cancel` is absent — i.e., the turn really has finished.

### Response extraction

A completed turn renders in the scrollback as:

```
─────────────────────────────────────────
> Reply with one word: APPLE
                                          
  APPLE
                                          
─────────────────────────────────────────
>                ← empty next input area
─────────────────────────────────────────
? for shortcuts                  Gemini …
```

`extract_response(screen)`:

1. Walks the captured text and finds the **last** line that matches
   `^>\s+\S` (rendered user prompt — has content after `>`, distinguishing
   it from the empty current-input `>`).
2. Collects following lines until a divider line of `[─-]{5,}` is reached.
3. Strips agy's 2-space indent and trailing blanks; returns the joined
   text.

### Why "warmup waits for `? for shortcuts`" and not the banner

agy renders its banner ~4 seconds before the input area is actually ready
to accept paste. Banner presence is misleading — pasting at that moment
gets dropped. The `? for shortcuts` marker is the authoritative signal
that the TUI's input loop is alive.

### Trust-folder modal

agy shows the same kind of trust-folder modal codex does ("Do you trust
the contents of this project?" — default Yes). The warmup state machine
in `cmt/agy_warmup.py` matches that marker and presses Enter, mirroring
the codex warmup shape.

## Why not parse the `.pb` files

Tried, briefly. They:

- Don't appear until *after* a multi-turn conversation (sometimes never
  for short sessions),
- Carry a protobuf schema we don't control,
- Would create a fragile binding to internal Antigravity layout.

Capture-pane is a stable interface, the markers are user-facing UI text
(unlikely to change without notice), and the failure modes are
debuggable by anyone who can read a pane.

## Consequences

- **Divider regex calibrated to pane width.** agy renders the divider as a
  full-width run of `─`, so the length varies — a side-pane surface
  (~21 cols visible) shows ~18-character dividers; a full-width pane
  shows 150+. The regex `[─-]{5,}` covers both without matching ordinary
  markdown `---`. Calibration came from the parallel demo — see
  [[0004-cmux-cli-serialization]].
- **No `baseline_offset` for agy.** `AgentState.session_file` is always
  None and `baseline_offset` is always 0. `last_reply` re-captures the
  pane every call — fresh state, no caching layer.
- **Per-call screen captures are the cost.** Sub-second; not a bottleneck
  against LLM-turn timescales.

"""Workflow layer — multi-agent composition on top of the raw `cmt` primitives.

The raw layer (`cmt spawn/ask/send/keys/capture/status/...`) is pure agent
manipulation: it drives one pane and sends exactly what it's given. This
package adds everything needed to compose *several* agents into a flow:

- **role**       — stable identity, prepended by `wf ask` so an agent can't
                   drift out of character across turns.
- **kv**         — current world state (one value per key).
- **transcript** — append-only shared history per topic.
- **inbox**      — point-to-point actor message passing (enqueue/dequeue).

Per the passive-store / active-flow split: these are passive stores. A
workflow script reads them, embeds the context into a prompt, and writes
results back. The only context the layer injects on its own is the Role,
applied by `wf ask`.
"""

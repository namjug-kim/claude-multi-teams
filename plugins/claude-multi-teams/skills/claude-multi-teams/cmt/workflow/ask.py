"""`cmt wf ask` — a role-aware wrapper over the raw `cmt ask`.

The only place the workflow layer auto-injects context: it looks up the
agent's Role and prepends an identity prelude, then delegates to the raw
ask (which sends the prompt verbatim and blocks until the turn is done).
Everything else a workflow wants an agent to see it embeds in the prompt
itself.
"""

from __future__ import annotations

from pathlib import Path

from cmt.ops import ask as raw_ask
from cmt.workflow import role as role_mod


def ask(name: str, prompt: str, state_dir: Path | None = None) -> str:
    role = role_mod.get_role(name, state_dir=state_dir)
    if role:
        prelude = (
            f"[Your name is {name}. Your role: {role}. "
            f"Stay strictly in this role for every reply.]"
        )
        prompt = f"{prelude}\n\n{prompt}"
    return raw_ask.ask(name, prompt, state_dir=state_dir)

"""``cmt`` CLI entry point. Dispatch only — no business logic here.

Two namespaces:
  - top-level ``cmt <verb>``      — the raw layer (pure agent manipulation)
  - ``cmt wf <verb>``             — the workflow layer (role / kv / transcript /
                                    inbox + a role-aware ask)
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path

from cmt.ops import ask as ask_op
from cmt.ops import capture as capture_op
from cmt.ops import keys as keys_op
from cmt.ops import kill as kill_op
from cmt.ops import last_reply as last_reply_op
from cmt.ops import list_ as list_op
from cmt.ops import modal as modal_op
from cmt.ops import send as send_op
from cmt.ops import spawn as spawn_op
from cmt.ops import status as status_op
from cmt.ops import wait_output as wait_output_op
from cmt.ops import wait_status as wait_status_op
from cmt.ops import whoami as whoami_op
from cmt.workflow import ask as wf_ask_op
from cmt.workflow import inbox as wf_inbox
from cmt.workflow import kv as wf_kv
from cmt.workflow import role as wf_role
from cmt.workflow import transcript as wf_transcript


def _read_prompt(p: str) -> str:
    if p == "-":
        return sys.stdin.read()
    if p.startswith("@"):
        return Path(p[1:]).read_text()
    return p


def _emit(text: str) -> None:
    sys.stdout.write(text)
    if not text.endswith("\n"):
        sys.stdout.write("\n")


# --------------------------------------------------------------------------
# Raw layer
# --------------------------------------------------------------------------


def _cmd_spawn(args) -> int:
    s = spawn_op.spawn(agent=args.agent, name=args.name, cwd=args.cwd,
                       replace=args.replace)
    print(f"spawned {s.name} (agent={s.agent}, pane={s.pane_id})")
    return 0


def _cmd_ask(args) -> int:
    _emit(ask_op.ask(args.name, _read_prompt(args.prompt)))
    return 0


def _cmd_kill(args) -> int:
    if args.all:
        kill_op.kill_all()
    else:
        if not args.name:
            print("error: name required (or pass --all)", file=sys.stderr)
            return 2
        try:
            kill_op.kill(args.name)
        except RuntimeError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
    return 0


def _cmd_send(args) -> int:
    send_op.send(args.name, args.text, enter=not args.no_enter)
    return 0


def _cmd_keys(args) -> int:
    keys_op.keys(args.name, args.keys)
    return 0


def _cmd_capture(args) -> int:
    sys.stdout.write(capture_op.capture(args.name, mode=args.mode))
    return 0


def _cmd_modal(args) -> int:
    m = modal_op.inspect(args.name)
    if m is None:
        if args.json:
            print("null")
        else:
            print("(no modal)")
        return 1
    if args.json:
        print(json.dumps(dataclasses.asdict(m)))
    else:
        print(m.render())
    return 0


def _cmd_last_reply(args) -> int:
    reply = last_reply_op.last_reply(args.name)
    if reply:
        _emit(reply)
    return 0


def _cmd_status(args) -> int:
    print(status_op.status(args.name))
    return 0


def _cmd_wait_status(args) -> int:
    ok = wait_status_op.wait_status(args.name, target=args.target)
    return 0 if ok else 2


def _cmd_wait_output(args) -> int:
    ok = wait_output_op.wait_output(args.name, pattern=args.match, as_text=args.text)
    return 0 if ok else 2


def _cmd_whoami(args) -> int:
    me = whoami_op.whoami()
    if me is None:
        print("error: not running inside a tracked agent pane (CMT_AGENT_ID unset/unknown)",
              file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(dataclasses.asdict(me), indent=2))
    else:
        print(f"{me.name} (agent={me.agent}, pane={me.pane_id}, id={me.agent_id})")
    return 0


def _cmd_list(args) -> int:
    agents = list_op.list_agents()
    if args.json:
        print(json.dumps([dataclasses.asdict(s) for s in agents], indent=2))
        return 0
    if not agents:
        print("(no agents tracked)")
        return 0
    print(f"{'NAME':<20} {'AGENT':<8} {'PANE':<8} {'STARTED':<28} CWD")
    for s in agents:
        print(f"{s.name:<20} {s.agent:<8} {s.pane_id:<8} {s.started_at:<28} {s.cwd}")
    return 0


# --------------------------------------------------------------------------
# Workflow layer (cmt wf ...)
# --------------------------------------------------------------------------


def _wf_role_set(args) -> int:
    wf_role.set_role(args.name, _read_prompt(args.role))
    return 0


def _wf_role_get(args) -> int:
    role = wf_role.get_role(args.name)
    if role is None:
        return 1
    _emit(role)
    return 0


def _wf_ask(args) -> int:
    _emit(wf_ask_op.ask(args.name, _read_prompt(args.prompt)))
    return 0


def _wf_put(args) -> int:
    wf_kv.put(args.key, _read_prompt(args.value))
    return 0


def _wf_get(args) -> int:
    val = wf_kv.get(args.key)
    if val is None:
        return 1
    _emit(val)
    return 0


def _wf_log(args) -> int:
    if args.log_cmd == "append":
        wf_transcript.append(args.topic, _read_prompt(args.content), frm=args.frm)
        return 0
    entries = wf_transcript.tail(args.topic, n=args.n)
    if args.json:
        print(json.dumps(entries, indent=2))
        return 0
    for e in entries:
        frm = e.get("from") or "(orchestrator)"
        print(f"[{e.get('ts','')}] {frm}: {e.get('content','')}")
    return 0


def _wf_enqueue(args) -> int:
    from cmt import state as _state
    msg = wf_inbox.enqueue(_state.default_dir(), args.target, _read_prompt(args.content),
                           sender=args.sender or "", replies_to=args.replies_to)
    if args.json:
        print(json.dumps(dataclasses.asdict(msg)))
    else:
        print(msg.msg_id)
    return 0


def _wf_dequeue(args) -> int:
    from cmt import state as _state
    msg = wf_inbox.dequeue(_state.default_dir(), args.agent)
    if msg is None:
        return 1
    if args.json:
        print(json.dumps(dataclasses.asdict(msg)))
    else:
        _emit(msg.content)
    return 0


def _wf_inbox(args) -> int:
    from cmt import state as _state
    sd = _state.default_dir()
    if args.clear:
        print(f"cleared {wf_inbox.clear(sd, args.agent)} messages")
        return 0
    msgs = wf_inbox.peek(sd, args.agent)
    if args.json:
        print(json.dumps([dataclasses.asdict(m) for m in msgs], indent=2))
        return 0
    if not msgs:
        print("(empty)")
        return 0
    for m in msgs:
        sender = m.sender or "(orchestrator)"
        print(f"[{m.ts}] from={sender} -> {m.to}: {m.content[:80]}")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cmt", description="claude-multi-teams")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("spawn", help="create a pane and start an agent")
    sp.add_argument("agent", choices=["claude", "codex", "agy"])
    sp.add_argument("name")
    sp.add_argument("--cwd", default=None)
    sp.add_argument("--replace", action="store_true")
    sp.set_defaults(func=_cmd_spawn)

    sp = sub.add_parser("ask", help="send a prompt verbatim, block until done, print reply")
    sp.add_argument("name")
    sp.add_argument("prompt", help="prompt text; @file for file; - for stdin")
    sp.set_defaults(func=_cmd_ask)

    sp = sub.add_parser("kill", help="tear down an agent (or all)")
    sp.add_argument("name", nargs="?")
    sp.add_argument("--all", action="store_true")
    sp.set_defaults(func=_cmd_kill)

    sp = sub.add_parser("send", help="paste text into a pane (default + Enter)")
    sp.add_argument("name")
    sp.add_argument("text")
    sp.add_argument("--no-enter", action="store_true", dest="no_enter")
    sp.set_defaults(func=_cmd_send)

    sp = sub.add_parser("keys", help="send arbitrary key sequence (Enter, Down, Tab, ...)")
    sp.add_argument("name")
    sp.add_argument("keys", nargs="+")
    sp.set_defaults(func=_cmd_keys)

    sp = sub.add_parser("capture", help="read pane screen text")
    sp.add_argument("name")
    sp.add_argument("--mode", choices=["visible", "full", "wrapped"], default="full")
    sp.set_defaults(func=_cmd_capture)

    sp = sub.add_parser("modal", help="inspect a startup selection modal (rc=1 if none); answer via `keys`")
    sp.add_argument("name")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=_cmd_modal)

    sp = sub.add_parser("last-reply", help="re-extract the most recent assistant text")
    sp.add_argument("name")
    sp.set_defaults(func=_cmd_last_reply)

    sp = sub.add_parser("status", help="working | done | blocked | dead")
    sp.add_argument("name")
    sp.set_defaults(func=_cmd_status)

    sp = sub.add_parser("wait-status", help="block until agent reaches a target status")
    sp.add_argument("name")
    sp.add_argument("target", choices=["working", "done", "blocked", "dead"])
    sp.set_defaults(func=_cmd_wait_status)

    sp = sub.add_parser("wait-output", help="block until pane text matches a pattern")
    sp.add_argument("name")
    sp.add_argument("--match", required=True, help="regex (default) or substring (--text)")
    sp.add_argument("--text", action="store_true", help="treat --match as a literal substring")
    sp.set_defaults(func=_cmd_wait_output)

    sp = sub.add_parser("whoami", help="self-identify from inside a spawned pane")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=_cmd_whoami)

    sp = sub.add_parser("list", help="enumerate tracked agents")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=_cmd_list)

    _build_wf_parser(sub)
    return p


def _build_wf_parser(sub) -> None:
    wf = sub.add_parser("wf", help="workflow layer: role / ask / kv / transcript / inbox")
    wsub = wf.add_subparsers(dest="wf_cmd", required=True)

    role = wsub.add_parser("role", help="get/set an agent's role")
    rsub = role.add_subparsers(dest="role_cmd", required=True)
    rset = rsub.add_parser("set", help="set an agent's role")
    rset.add_argument("name")
    rset.add_argument("role", help="role text; @file or - for stdin")
    rset.set_defaults(func=_wf_role_set)
    rget = rsub.add_parser("get", help="print an agent's role (rc=1 if none)")
    rget.add_argument("name")
    rget.set_defaults(func=_wf_role_get)

    a = wsub.add_parser("ask", help="role-aware ask: prepend role, then ask")
    a.add_argument("name")
    a.add_argument("prompt", help="prompt text; @file or - for stdin")
    a.set_defaults(func=_wf_ask)

    put = wsub.add_parser("put", help="(kv) write current value for a key")
    put.add_argument("key")
    put.add_argument("value", help="value text; @file or - for stdin")
    put.set_defaults(func=_wf_put)

    get = wsub.add_parser("get", help="(kv) read current value for a key")
    get.add_argument("key")
    get.set_defaults(func=_wf_get)

    log = wsub.add_parser("log", help="(transcript) append-only shared history")
    lsub = log.add_subparsers(dest="log_cmd", required=True)
    la = lsub.add_parser("append", help="append an entry to a topic")
    la.add_argument("topic")
    la.add_argument("content", help="entry text; @file or - for stdin")
    la.add_argument("--from", default=None, dest="frm", help="author name")
    la.set_defaults(func=_wf_log)
    lt = lsub.add_parser("tail", help="read entries from a topic")
    lt.add_argument("topic")
    lt.add_argument("--n", type=int, default=None, help="last N entries")
    lt.add_argument("--json", action="store_true")
    lt.set_defaults(func=_wf_log)

    enq = wsub.add_parser("enqueue", help="(actor) write a message to an agent's inbox")
    enq.add_argument("target")
    enq.add_argument("content", help="message text; @file or - for stdin")
    enq.add_argument("--sender", default=None, help="sender name (orchestrator if omitted)")
    enq.add_argument("--replies-to", default=None, dest="replies_to", help="msg_id this replies to")
    enq.add_argument("--json", action="store_true")
    enq.set_defaults(func=_wf_enqueue)

    deq = wsub.add_parser("dequeue", help="(actor) atomically take the oldest inbox message")
    deq.add_argument("agent")
    deq.add_argument("--json", action="store_true")
    deq.set_defaults(func=_wf_dequeue)

    ibx = wsub.add_parser("inbox", help="(actor) peek or clear an agent's inbox")
    ibx.add_argument("agent")
    ibx.add_argument("--clear", action="store_true")
    ibx.add_argument("--json", action="store_true")
    ibx.set_defaults(func=_wf_inbox)


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

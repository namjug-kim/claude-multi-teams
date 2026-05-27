"""``cmt`` CLI entry point. Dispatch only — no business logic here."""

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
from cmt.ops import send as send_op
from cmt.ops import spawn as spawn_op
from cmt.ops import status as status_op
from cmt.ops import wait_output as wait_output_op
from cmt.ops import wait_status as wait_status_op
from cmt.ops import whoami as whoami_op


def _read_prompt(p: str) -> str:
    if p == "-":
        return sys.stdin.read()
    if p.startswith("@"):
        return Path(p[1:]).read_text()
    return p


def _cmd_spawn(args) -> int:
    s = spawn_op.spawn(agent=args.agent, name=args.name, cwd=args.cwd, replace=args.replace)
    print(f"spawned {s.name} (agent={s.agent}, pane={s.pane_id})")
    return 0


def _cmd_ask(args) -> int:
    reply = ask_op.ask(args.name, _read_prompt(args.prompt))
    sys.stdout.write(reply)
    if not reply.endswith("\n"):
        sys.stdout.write("\n")
    return 0


def _cmd_kill(args) -> int:
    if args.all:
        kill_op.kill_all()
    else:
        if not args.name:
            print("error: name required (or pass --all)", file=sys.stderr)
            return 2
        kill_op.kill(args.name)
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


def _cmd_last_reply(args) -> int:
    reply = last_reply_op.last_reply(args.name)
    sys.stdout.write(reply)
    if reply and not reply.endswith("\n"):
        sys.stdout.write("\n")
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


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cmt", description="claude-multi-teams")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("spawn", help="create a pane and start an agent")
    sp.add_argument("agent", choices=["claude", "codex", "agy"])
    sp.add_argument("name")
    sp.add_argument("--cwd", default=None)
    sp.add_argument("--replace", action="store_true")
    sp.set_defaults(func=_cmd_spawn)

    sp = sub.add_parser("ask", help="send a prompt, block until done, print reply")
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

    return p


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

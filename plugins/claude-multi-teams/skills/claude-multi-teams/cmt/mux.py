"""Thin wrappers around the host multiplexer's CLI.

Two backends, dispatched at runtime per call:

- **real tmux**  — when ``$TMUX`` is empty or points at a non-cmux server.
  We shell out to ``tmux``; the server is inherited from ``$TMUX``.
- **cmux native** — when ``$TMUX`` points at the cmux ``claude-teams`` fake
  tmux path (``/tmp/cmux-claude-teams/…``). The ``tmux`` shim on PATH can
  spawn panes and send keys but its split-window outputs are *shim-only*
  pseudo-panes that don't show up in cmux's UI, and its ``paste-buffer``
  doesn't deliver bracketed paste to the receiving TUI. We bypass the shim
  for everything and call ``cmux`` directly. The created panes ARE real
  cmux surfaces (visible in the sidebar).

State files store the mux-native pane id as a string. Real tmux uses
``%<UUID>`` or ``%<N>``; cmux uses ``surface:<N>``. Each backend's ops
read/write whichever format their CLI accepts.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
from typing import Literal

CaptureMode = Literal["visible", "full", "wrapped"]


# ---------------------------------------------------------------------------
# Backend dispatch
# ---------------------------------------------------------------------------


def _use_cmux_native() -> bool:
    """True when we're inside cmux ``claude-teams`` and should bypass the
    tmux shim. Detected by either:

    - ``$TMUX`` starting with the cmux-claude-teams fake path (the outer
      shell our user starts cmt from has this set), OR
    - ``$CMUX_SOCKET_PATH`` is set (panes that cmux itself spawned —
      including the ones cmt creates for sibling agents — inherit this
      from cmux's daemon env but do NOT inherit ``$TMUX``).

    Without the second check, a sibling agent invoking cmt back from its
    own Bash tool would fall through to the tmux path and try to find
    cmux-shaped ``surface:N`` ids via ``tmux list-panes`` — which fails,
    surfacing as a false "pane is dead".
    """
    if os.environ.get("TMUX", "").startswith("/tmp/cmux-claude-teams"):
        return True
    if os.environ.get("CMUX_SOCKET_PATH"):
        return True
    return False


# ---------------------------------------------------------------------------
# tmux backend
# ---------------------------------------------------------------------------


def _tmux(*args: str, check: bool = True, capture: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["tmux", *args],
        check=check,
        capture_output=capture,
        text=True,
    )


def _tmux_split_pane(parent_pane: str, cwd: str, cmd: str, env_vars: dict[str, str]) -> str:
    if env_vars:
        prefix = " ".join(f"{k}={shlex.quote(v)}" for k, v in env_vars.items())
        cmd = f"{prefix} exec {cmd}"
    res = _tmux("split-window", "-h", "-t", parent_pane, "-c", cwd,
                "-P", "-F", "#{pane_id}", cmd)
    return res.stdout.strip()


def _tmux_paste_bracketed(pane: str, text: str) -> None:
    # Per-pane named buffer, not the shared default buffer. With the default
    # buffer, two concurrent asks race: A's set-buffer is clobbered by B's
    # before A's paste-buffer fires, so A's pane receives B's text. A named
    # buffer per pane removes the shared state. `-d` drops the buffer after
    # pasting so it doesn't accumulate.
    buf = "cmt-" + re.sub(r"[^A-Za-z0-9_-]", "_", pane)
    _tmux("set-buffer", "-b", buf, "--", text)
    _tmux("paste-buffer", "-b", buf, "-d", "-p", "-t", pane)


def _tmux_send_keys(pane: str, keys: tuple[str, ...]) -> None:
    _tmux("send-keys", "-t", pane, *keys)


def _tmux_capture(pane: str, mode: CaptureMode) -> str:
    args = ["capture-pane", "-p", "-t", pane]
    if mode == "full":
        args.extend(["-S", "-", "-E", "-"])
    elif mode == "wrapped":
        args.extend(["-S", "-", "-E", "-", "-J"])
    return _tmux(*args).stdout


def _tmux_kill_pane(pane: str) -> None:
    _tmux("kill-pane", "-t", pane, check=False)


def _tmux_pane_alive(pane: str) -> bool:
    res = _tmux("list-panes", "-a", "-F", "#{pane_id}", check=False)
    if res.returncode != 0:
        return False
    return pane in res.stdout.split()


def _tmux_list_panes() -> list[str]:
    res = _tmux("list-panes", "-a", "-F", "#{pane_id}", check=False)
    if res.returncode != 0:
        return []
    return [p for p in res.stdout.split() if p]


# ---------------------------------------------------------------------------
# cmux backend
# ---------------------------------------------------------------------------


_CMUX_LOCK_PATH = "/tmp/cmt-cmux.lock"


def _cmux(*args: str, check: bool = True, capture: bool = True,
          stdout=None) -> subprocess.CompletedProcess:
    """Run a ``cmux`` CLI command.

    Concurrent invocations of the cmux CLI from sibling cmt processes
    (parallel asks across multiple agents) race against shared state and
    fail intermittently. We serialize them with a host-wide fcntl lock on
    ``/tmp/cmt-cmux.lock``. The lock is per-call (held only for the
    subprocess), so it doesn't block long-running cmux operations on
    unrelated panes."""
    import fcntl
    kwargs: dict = {"check": check, "text": True}
    if stdout is not None:
        kwargs["stdout"] = stdout
        kwargs["stderr"] = subprocess.PIPE
    elif capture:
        kwargs["capture_output"] = True
    lock_fd = os.open(_CMUX_LOCK_PATH, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        return subprocess.run(["cmux", *args], **kwargs)
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)


_CMUX_SURFACE_RE = re.compile(r"^surface:\d+$")


def _is_cmux_surface(pane: str) -> bool:
    """A cmt-created cmux pane id is always ``surface:<N>`` (parsed from
    ``new-pane`` output). Require that exact shape before passing ``pane`` to
    any cmux command whose ``--surface`` falls back to the *focused* surface
    (the user's main tab) when the value is empty or unresolvable. An empty,
    malformed (``surface:``, ``surface:abc``), or cross-backend (``%id``) value
    must never reach those commands."""
    return bool(_CMUX_SURFACE_RE.match(pane))


def _cmux_split_pane(parent_pane: str, cwd: str, cmd: str, env_vars: dict[str, str]) -> str:
    """Create a new cmux pane and run ``cmd`` in it via the new pane's shell.

    cmux's ``new-pane`` always spawns the user's default shell (no --command
    flag). We send the command via ``cmux send`` (typed into the shell) + a
    final Enter via ``cmux send-key``. ``exec`` replaces the shell with the
    agent so the pane's foreground process becomes the agent directly.

    ``parent_pane`` is ignored; cmux defaults to ``$CMUX_WORKSPACE_ID``.
    ``cwd`` is folded into the command (``cd && …``) since new-pane has
    no --cwd flag either.
    """
    res = _cmux("new-pane", "--direction", "right")
    # output format: "OK surface:58 pane:53 workspace:1\n"
    surface_ref = next(tok for tok in res.stdout.split() if tok.startswith("surface:"))

    prefix_parts = [f"cd {shlex.quote(cwd)} &&"]
    if env_vars:
        prefix_parts.append(" ".join(f"{k}={shlex.quote(v)}" for k, v in env_vars.items()))
    prefix_parts.append("exec")
    full_cmd = " ".join(prefix_parts) + " " + cmd
    _cmux("send", "--surface", surface_ref, full_cmd, stdout=subprocess.DEVNULL)
    _cmux("send-key", "--surface", surface_ref, "Enter", stdout=subprocess.DEVNULL)
    return surface_ref


def _cmux_paste_bracketed(pane: str, text: str) -> None:
    # Same focused-surface fallback hazard as close-surface (see
    # _cmux_kill_pane): paste-buffer on an unresolvable --surface lands the
    # text on the user's main tab. Never paste to a non-surface id.
    if not _is_cmux_surface(pane):
        return
    buf_name = f"cmt-{pane.replace(':', '-')}"
    _cmux("set-buffer", "--name", buf_name, "--", text, stdout=subprocess.DEVNULL)
    _cmux("paste-buffer", "--name", buf_name, "--surface", pane, stdout=subprocess.DEVNULL)


# tmux uses "Enter" / "C-u" / "Escape"; cmux uses "enter" / "ctrl+u" / "esc".
# Map the tmux spellings we ship in CLI surface to cmux's vocabulary. Literal
# single characters and unrecognized names pass through as-is.
_TMUX_TO_CMUX_KEY = {
    "Enter": "enter",
    "Tab": "tab",
    "Space": "space",
    "Escape": "esc", "Esc": "esc",
    "Up": "up", "Down": "down", "Left": "left", "Right": "right",
    "BSpace": "backspace", "Backspace": "backspace",
    "Delete": "delete", "Home": "home", "End": "end",
    "PageUp": "pageup", "PageDown": "pagedown",
}


def _tmux_key_to_cmux(key: str) -> str:
    if key in _TMUX_TO_CMUX_KEY:
        return _TMUX_TO_CMUX_KEY[key]
    # tmux modifier syntax — C-u → ctrl+u, M-u → alt+u, S-u → shift+u
    if len(key) >= 3 and key[1] == "-" and key[0] in ("C", "M", "S"):
        mod = {"C": "ctrl", "M": "alt", "S": "shift"}[key[0]]
        rest = key[2:]
        return f"{mod}+{rest.lower() if len(rest) == 1 else rest}"
    return key


def _cmux_send_keys(pane: str, keys: tuple[str, ...]) -> None:
    # Same focused-surface fallback hazard as close-surface (see
    # _cmux_kill_pane): send/send-key on an unresolvable --surface lands the
    # keys on the user's main tab. Never send to a non-surface id.
    if not _is_cmux_surface(pane):
        return
    # cmux send-key takes one *named* key per call (enter, up, ctrl+c, …) and
    # rejects literal characters ("Unknown key"). Route single printable chars
    # (e.g. a menu digit "2") through `cmux send` (text input); everything else
    # is a named key. tmux's send-keys handles both, so only cmux needs this.
    for k in keys:
        if len(k) == 1 and k.isprintable():
            _cmux("send", "--surface", pane, k, stdout=subprocess.DEVNULL)
        else:
            _cmux("send-key", "--surface", pane, _tmux_key_to_cmux(k),
                  stdout=subprocess.DEVNULL)


def _cmux_capture(pane: str, mode: CaptureMode) -> str:
    # Fail closed on a non-surface id: capture-pane with an empty --surface
    # falls back to the focused surface, so `cmt capture`/`modal` on a stale id
    # would read the user's main tab instead of erroring. Return no screen.
    if not _is_cmux_surface(pane):
        return ""
    args = ["capture-pane", "--surface", pane]
    if mode in ("full", "wrapped"):
        args.append("--scrollback")
    res = _cmux(*args)
    return res.stdout


def _cmux_kill_pane(pane: str) -> None:
    # `close-surface` defaults to the focused surface ($CMUX_SURFACE_ID — the
    # user's main tab) when it can't resolve --surface. A stale or
    # cross-backend id (empty, or a tmux "%id" from a state file written under
    # the other backend) would trip that fallback and close the wrong pane, so
    # only call it for a real cmux surface ref.
    if not _is_cmux_surface(pane):
        return
    _cmux("close-surface", "--surface", pane, check=False, stdout=subprocess.DEVNULL)


def _cmux_pane_alive(pane: str) -> bool:
    # A non-surface id (empty, or a tmux "%id" from stale/cross-backend state)
    # is never a live cmux surface. Reject it without calling capture-pane,
    # which could fall back to the focused surface and falsely report alive.
    if not _is_cmux_surface(pane):
        return False
    # `capture-pane` on a missing surface errors. A 0-exit capture means the
    # surface exists and is a terminal.
    res = _cmux("capture-pane", "--surface", pane, "--lines", "1",
                check=False, capture=False, stdout=subprocess.DEVNULL)
    return res.returncode == 0


def _cmux_current_pane() -> str | None:
    """The ref of the currently *selected* (focused) cmux surface, or None.

    cmux doesn't expose this pane's own ref to its process (``$CMUX_SURFACE_ID``
    is a UUID, not the ``surface:N`` ref cmt persists), so we read the selected
    surface from ``list-pane-surfaces``. When cmt is driven interactively this
    is the orchestrator pane — the one we must never close."""
    import json

    res = _cmux("list-pane-surfaces", "--json", check=False)
    if res.returncode != 0:
        return None
    try:
        data = json.loads(res.stdout)
    except json.JSONDecodeError:
        return None
    for s in data.get("surfaces", []):
        if s.get("selected"):
            return s.get("ref")
    return None


def _cmux_list_panes() -> list[str]:
    """Best-effort list of cmux terminal surfaces in the current workspace,
    returned as ``surface:N`` refs."""
    res = _cmux("list-pane-surfaces", check=False)
    if res.returncode != 0:
        return []
    out: list[str] = []
    for line in res.stdout.splitlines():
        for tok in line.split():
            if tok.startswith("surface:"):
                out.append(tok)
                break
    return out


# ---------------------------------------------------------------------------
# Public dispatch
# ---------------------------------------------------------------------------


def split_pane(parent_pane: str, cwd: str, cmd: str, env_vars: dict[str, str]) -> str:
    """Spawn a pane running ``cmd`` with ``env_vars`` injected. Returns
    the pane id (mux-native; ``%<…>`` for tmux, ``surface:<N>`` for cmux)."""
    if _use_cmux_native():
        return _cmux_split_pane(parent_pane, cwd, cmd, env_vars)
    return _tmux_split_pane(parent_pane, cwd, cmd, env_vars)


def paste_bracketed(pane: str, text: str) -> None:
    """Deliver ``text`` to the pane as a bracketed paste."""
    if _use_cmux_native():
        _cmux_paste_bracketed(pane, text)
        return
    _tmux_paste_bracketed(pane, text)


def send_text(pane: str, text: str) -> None:
    """Paste ``text`` then press Enter."""
    paste_bracketed(pane, text)
    send_keys(pane, "Enter")


def send_keys(pane: str, *keys: str) -> None:
    """Forward key names (``Enter``, ``Down``, ``Tab``, ``Escape``, …) or
    literal strings to the pane."""
    if _use_cmux_native():
        _cmux_send_keys(pane, keys)
        return
    _tmux_send_keys(pane, keys)


def capture(pane: str, mode: CaptureMode = "full") -> str:
    """Return the rendered pane text. ``visible``/``full``/``wrapped`` —
    ``wrapped`` joins soft-wrapped lines (tmux ``-J``)."""
    if _use_cmux_native():
        return _cmux_capture(pane, mode)
    return _tmux_capture(pane, mode)


def kill_pane(pane: str) -> None:
    """Destroy the pane. Silent on already-dead pane."""
    if _use_cmux_native():
        _cmux_kill_pane(pane)
        return
    _tmux_kill_pane(pane)


def pane_alive(pane: str) -> bool:
    if _use_cmux_native():
        return _cmux_pane_alive(pane)
    return _tmux_pane_alive(pane)


def list_panes() -> list[str]:
    if _use_cmux_native():
        return _cmux_list_panes()
    return _tmux_list_panes()


def current_pane() -> str | None:
    """The pane cmt is running in (tmux ``$TMUX_PANE``) or the focused cmux
    surface ref. Used by ``kill`` to refuse closing the orchestrator's own
    pane — a stale/recycled ``surface:N`` ref can otherwise point here."""
    if _use_cmux_native():
        return _cmux_current_pane()
    return os.environ.get("TMUX_PANE") or None

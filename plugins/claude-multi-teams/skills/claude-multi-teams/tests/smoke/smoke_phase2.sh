#!/usr/bin/env bash
# Smoke phase-2: exercises send / keys / capture / status / wait-status /
# wait-output / last-reply / whoami / list against real claude in real tmux.
set -euo pipefail

SOCK=/tmp/cmt-p2-$$.sock
STATE_DIR=/tmp/cmt-p2-state-$$
mkdir -p "$STATE_DIR"

SKILL_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
CMT="$SKILL_DIR/bin/cmt"

# Inside cmux claude-teams, `tmux` on PATH is the shim. We need the real tmux
# binary to host a separate test server (matches conftest.py unit-test setup).
TMUX_BIN=/opt/homebrew/bin/tmux
[[ -x "$TMUX_BIN" ]] || TMUX_BIN=$(command -v tmux)

cleanup() {
  "$CMT" kill --all 2>/dev/null || true
  "$TMUX_BIN" -S "$SOCK" kill-server 2>/dev/null || true
  rm -rf "$STATE_DIR"
  rm -f "$SOCK"
}
trap cleanup EXIT

unset CMUX_SOCKET_PATH
# Strip the cmux tmux shim from PATH so cmt's own tmux subprocess calls
# resolve to real tmux.
SHIM_DIR="$HOME/.cmuxterm/claude-teams-bin"
NEWPATH="/opt/homebrew/bin"
IFS=: read -r -a _parts <<< "$PATH"
for p in "${_parts[@]}"; do
  [[ "$p" == "$SHIM_DIR" || "$p" == "/opt/homebrew/bin" ]] && continue
  NEWPATH="$NEWPATH:$p"
done
export PATH="$NEWPATH"

"$TMUX_BIN" -S "$SOCK" new-session -d -s smoke -x 200 -y 60 bash
ROOT=$("$TMUX_BIN" -S "$SOCK" list-panes -F '#{pane_id}')
export TMUX="$SOCK,0,0" TMUX_PANE="$ROOT" CMT_STATE_DIR="$STATE_DIR"

echo "== spawn =="
"$CMT" spawn claude alice

echo "== list =="
"$CMT" list

echo "== status (just after spawn, before any ask) =="
"$CMT" status alice

echo "== wait-output for claude prompt prefix =="
"$CMT" wait-output alice --text --match "▌"

echo "== ask =="
REPLY=$("$CMT" ask alice "reply with exactly the word: pong")
echo "REPLY='$REPLY'"
echo "$REPLY" | grep -qi pong || { echo "FAIL: no pong"; exit 1; }

echo "== last-reply =="
LR=$("$CMT" last-reply alice)
echo "LAST='$LR'"
echo "$LR" | grep -qi pong || { echo "FAIL: last-reply mismatch"; exit 1; }

echo "== status (after ask) =="
"$CMT" status alice

echo "== wait-status done =="
"$CMT" wait-status alice done

echo "== capture (full, last 5 lines) =="
"$CMT" capture alice | tail -5

echo "== send / keys (no-op safety test — send a comment) =="
"$CMT" send alice "# noop"
sleep 0.3
"$CMT" keys alice Escape

echo "== whoami inside the alice pane =="
AGENT_ID=$("$CMT" list --json | python3 -c "import sys,json; print(json.load(sys.stdin)[0]['agent_id'])")
CMT_AGENT_ID="$AGENT_ID" "$CMT" whoami

echo "== kill --all =="
"$CMT" kill --all

echo "== list (should be empty) =="
"$CMT" list

echo "SMOKE PHASE-2 OK"

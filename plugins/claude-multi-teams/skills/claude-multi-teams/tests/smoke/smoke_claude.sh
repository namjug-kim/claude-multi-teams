#!/usr/bin/env bash
# Smoke test: real claude end-to-end via cmt spawn / ask / kill.
#
# Runs against a freshly-started real tmux server (so the tmux native paste
# path is exercised, not the cmux bypass — that branch is tested separately
# by launching from inside `cmux claude-teams`).
set -euo pipefail

# Use short /tmp paths — Unix socket name limit is 104 bytes on macOS.
SOCK=/tmp/cmt-smoke-$$.sock
STATE_DIR=/tmp/cmt-smoke-state-$$
mkdir -p "$STATE_DIR"

SKILL_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
CMT="$SKILL_DIR/bin/cmt"

# Use real tmux directly. Inside cmux claude-teams, the `tmux` on PATH is the
# cmux shim, which cannot host a separate real-tmux test server. We need
# brew's tmux binary explicitly. Fall back to PATH lookup if not present.
TMUX_BIN=/opt/homebrew/bin/tmux
[[ -x "$TMUX_BIN" ]] || TMUX_BIN=$(command -v tmux)

cleanup() {
  "$CMT" kill alice 2>/dev/null || true
  "$TMUX_BIN" -S "$SOCK" kill-server 2>/dev/null || true
  rm -rf "$STATE_DIR"
  rm -f "$SOCK"
}
trap cleanup EXIT

# Force the real-tmux paste path (we are inside cmux right now, but the
# smoke test runs against the real-tmux server we spawn below).
unset CMUX_SOCKET_PATH
# Strip the cmux tmux shim from PATH so cmt's own ``tmux`` subprocess calls
# resolve to real homebrew tmux (matches the conftest.py unit-test setup).
SHIM_DIR="$HOME/.cmuxterm/claude-teams-bin"
NEWPATH="/opt/homebrew/bin"
IFS=: read -r -a _parts <<< "$PATH"
for p in "${_parts[@]}"; do
  [[ "$p" == "$SHIM_DIR" || "$p" == "/opt/homebrew/bin" ]] && continue
  NEWPATH="$NEWPATH:$p"
done
export PATH="$NEWPATH"

# Start the test server (separate from any tmux/cmux the user is in).
"$TMUX_BIN" -S "$SOCK" new-session -d -s smoke -x 200 -y 60 bash
ROOT=$("$TMUX_BIN" -S "$SOCK" list-panes -F '#{pane_id}')
echo "smoke: tmux server up at $SOCK, root pane $ROOT"

# Point cmt at the test server / state dir.
export TMUX="$SOCK,0,0"
export TMUX_PANE="$ROOT"
export CMT_STATE_DIR="$STATE_DIR"

echo "smoke: cmt spawn claude alice"
"$CMT" spawn claude alice
ALICE_PANE=$(python3 -c "
import sys; sys.path.insert(0, '$SKILL_DIR')
from cmt import state
print(state.load('alice').pane_id)
")
echo "smoke: alice spawned in pane $ALICE_PANE"

# Claude needs a few seconds to render TUI + reach prompt-ready.
sleep 5
echo "smoke: alice screen tail (+5s):"
"$TMUX_BIN" -S "$SOCK" capture-pane -t "$ALICE_PANE" -p -S - -E - | tail -10
echo "---"

echo "smoke: cmt ask alice 'reply with exactly the word: pong'"
REPLY=$("$CMT" ask alice "reply with exactly the word: pong")
echo "smoke: REPLY='$REPLY'"

echo "smoke: cmt kill alice"
"$CMT" kill alice

if echo "$REPLY" | grep -qi pong; then
  echo "SMOKE OK"
  exit 0
fi
echo "SMOKE FAIL: expected 'pong' in reply, got '$REPLY'"
exit 1

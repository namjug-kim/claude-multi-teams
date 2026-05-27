#!/usr/bin/env bash
# Smoke test under cmux claude-teams. Verifies the cmux-native backend:
# spawn creates a real cmux surface (visible in `cmux tree`), ask round-trips,
# and `cmt whoami` invoked from inside the spawned agent's Bash tool resolves
# correctly via the propagated CMT_AGENT_ID + CMT_STATE_DIR env.
#
# Requires: running inside `cmux claude-teams` (so $TMUX starts with the
# fake "/tmp/cmux-claude-teams/" path). Falls back to skip otherwise.
set -euo pipefail

if [[ "${TMUX:-}" != /tmp/cmux-claude-teams/* ]]; then
  echo "smoke_cmux: not inside cmux claude-teams (TMUX=${TMUX:-unset}); skipping"
  exit 0
fi

SKILL_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
CMT="$SKILL_DIR/bin/cmt"
STATE_DIR=/tmp/cmt-smoke-cmux-$$
mkdir -p "$STATE_DIR"
export CMT_STATE_DIR="$STATE_DIR"

cleanup() {
  "$CMT" kill --all 2>/dev/null || true
  rm -rf "$STATE_DIR"
}
trap cleanup EXIT

echo "== spawn (surface should appear in cmux tree) =="
"$CMT" spawn claude alice
sleep 5

echo "== list =="
"$CMT" list

echo "== status =="
"$CMT" status alice

echo "== wait-output for claude prompt prefix =="
"$CMT" wait-output alice --text --match "▌"

echo "== ask =="
REPLY=$("$CMT" ask alice "Reply with exactly one word: APRICOT")
echo "REPLY='$REPLY'"
echo "$REPLY" | grep -qi apricot || { echo "FAIL: no apricot"; exit 1; }

echo "== last-reply =="
"$CMT" last-reply alice | grep -qi apricot || { echo "FAIL: last-reply mismatch"; exit 1; }

echo "== wait-status done =="
"$CMT" wait-status alice done

echo "== capture (last 5 lines) =="
"$CMT" capture alice | tail -5

echo "== whoami via Bash tool inside alice =="
EXPECTED_ID=$(python3 -c "import json; print(json.load(open('$STATE_DIR/agents/alice.json'))['agent_id'])")
REPLY=$("$CMT" ask alice "Use the Bash tool to run this and show ONLY its first stdout line: $CMT whoami")
echo "WHOAMI: $REPLY"
echo "$REPLY" | grep -q "id=$EXPECTED_ID" || { echo "FAIL: whoami did not return alice's id"; exit 1; }

echo "== send + keys (post-whoami; just confirm primitives don't error) =="
"$CMT" send alice "# noop"
sleep 0.3
"$CMT" keys alice Escape
"$CMT" keys alice C-u
"$CMT" keys alice Enter

echo "== kill =="
"$CMT" kill alice
"$CMT" list
echo "SMOKE_CMUX OK"

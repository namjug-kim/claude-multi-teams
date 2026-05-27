#!/usr/bin/env bash
# Smoke test for real codex agent under cmux claude-teams. Mirrors smoke_cmux.sh
# for claude. Verifies:
#   - codex spawn with bypass flags
#   - post_spawn_warmup dismisses the Trust-folder modal (if it appears) and
#     waits for the OpenAI Codex banner
#   - rollout file is discovered on first ask
#   - status/last-reply/wait-* work through the codex strategy
#   - whoami via codex's shell tool (codex runs in YOLO mode under these
#     flags, so it can shell out without approval)
#
# Requires: running inside `cmux claude-teams` AND real codex binary on PATH.
set -euo pipefail

if [[ "${TMUX:-}" != /tmp/cmux-claude-teams/* ]]; then
  echo "smoke_codex: not inside cmux claude-teams (TMUX=${TMUX:-unset}); skipping"
  exit 0
fi
if ! command -v codex >/dev/null 2>&1; then
  echo "smoke_codex: codex binary not found; skipping"
  exit 0
fi

SKILL_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
CMT="$SKILL_DIR/bin/cmt"
STATE_DIR=/tmp/cmt-smoke-codex-$$
mkdir -p "$STATE_DIR"
export CMT_STATE_DIR="$STATE_DIR"

cleanup() {
  "$CMT" kill --all 2>/dev/null || true
  rm -rf "$STATE_DIR"
}
trap cleanup EXIT

echo "== spawn codex bob (Trust modal handled, banner waited) =="
"$CMT" spawn codex bob

echo "== list =="
"$CMT" list

echo "== status (pre-first-ask: session_file is None → done) =="
"$CMT" status bob

echo "== ask (first turn — resolves rollout file) =="
REPLY=$("$CMT" ask bob "Reply with exactly one word: KIWI")
echo "REPLY='$REPLY'"
echo "$REPLY" | grep -qi kiwi || { echo "FAIL: no kiwi"; exit 1; }

echo "== status (post-ask: done) =="
"$CMT" status bob

echo "== last-reply =="
"$CMT" last-reply bob | grep -qi kiwi || { echo "FAIL: last-reply mismatch"; exit 1; }

echo "== wait-status done =="
"$CMT" wait-status bob done

echo "== capture (last 5 lines) =="
"$CMT" capture bob | tail -5

echo "== second turn (same rollout file, new baseline) =="
REPLY=$("$CMT" ask bob "Reply with exactly one word: MANGO")
echo "$REPLY" | grep -qi mango || { echo "FAIL: no mango"; exit 1; }

echo "== whoami via codex shell tool =="
EXPECTED_ID=$(python3 -c "import json; print(json.load(open('$STATE_DIR/agents/bob.json'))['agent_id'])")
REPLY=$("$CMT" ask bob "Run this command in the shell and show ONLY its first stdout line: $CMT whoami")
echo "WHOAMI: $REPLY"
echo "$REPLY" | grep -q "id=$EXPECTED_ID" || { echo "FAIL: whoami did not return bob's id"; exit 1; }

echo "== send + keys (post-whoami; just confirm primitives don't error) =="
"$CMT" send bob "# noop"
sleep 0.3
"$CMT" keys bob Escape

echo "== kill + final list =="
"$CMT" kill bob
"$CMT" list
echo "SMOKE_CODEX OK"

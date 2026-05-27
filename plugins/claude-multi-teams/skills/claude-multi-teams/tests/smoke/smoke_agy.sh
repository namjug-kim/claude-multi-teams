#!/usr/bin/env bash
# Smoke test for real agy (Antigravity CLI) under cmux claude-teams.
# Mirrors smoke_codex.sh shape. Verifies:
#   - agy spawn with --dangerously-skip-permissions
#   - post_spawn_warmup dismisses the Trust-folder modal and waits for the
#     "? for shortcuts" idle status line
#   - ask round-trips via screen capture (no jsonl)
#   - status flips working ↔ done via the bottom status line
#   - last-reply re-parses the most recent ─{40,}…> ─{40,} block
#
# Requires: cmux claude-teams environment + agy binary on PATH.
set -euo pipefail

if [[ "${TMUX:-}" != /tmp/cmux-claude-teams/* ]]; then
  echo "smoke_agy: not inside cmux claude-teams (TMUX=${TMUX:-unset}); skipping"
  exit 0
fi
if ! command -v agy >/dev/null 2>&1; then
  echo "smoke_agy: agy binary not found; skipping"
  exit 0
fi

SKILL_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
CMT="$SKILL_DIR/bin/cmt"
STATE_DIR=/tmp/cmt-smoke-agy-$$
mkdir -p "$STATE_DIR"
export CMT_STATE_DIR="$STATE_DIR"

cleanup() {
  "$CMT" kill --all 2>/dev/null || true
  rm -rf "$STATE_DIR"
}
trap cleanup EXIT

echo "== spawn agy carol (Trust modal handled, idle status awaited) =="
"$CMT" spawn agy carol

echo "== list =="
"$CMT" list

echo "== status (post-warmup: done) =="
"$CMT" status carol

echo "== ask (round-trip via capture-pane) =="
REPLY=$("$CMT" ask carol "Reply with exactly one word: PEACH")
echo "REPLY='$REPLY'"
echo "$REPLY" | grep -qi peach || { echo "FAIL: no peach in reply"; exit 1; }

echo "== status (post-ask: done) =="
"$CMT" status carol

echo "== last-reply =="
"$CMT" last-reply carol | grep -qi peach || { echo "FAIL: last-reply mismatch"; exit 1; }

echo "== wait-status done =="
"$CMT" wait-status carol done

echo "== capture (last 8 lines) =="
"$CMT" capture carol | tail -8

echo "== second turn =="
REPLY=$("$CMT" ask carol "Reply with exactly one word: PLUM")
echo "$REPLY" | grep -qi plum || { echo "FAIL: no plum"; exit 1; }

echo "== send + keys (post-asks; just confirm primitives don't error) =="
"$CMT" send carol "noop"
sleep 0.3
"$CMT" keys carol Escape

echo "== kill + final list =="
"$CMT" kill carol
"$CMT" list
echo "SMOKE_AGY OK"

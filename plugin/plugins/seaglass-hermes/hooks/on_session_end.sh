#!/bin/bash
# Hermes on_session_end hook for Seaglass.
#
# Reads stdin JSON ({session_id, ...}) and calls `seaglass session end` so the
# API can flip `sessions.ended_at`. Best-effort: empty id, missing CLI, or any
# CLI error is silent (the TTL sweep is the safety net). Same CLI
# call as the Claude Code SessionEnd hook — only the shim name differs.
set -uo pipefail

SESSION_ID="$(cat 2>/dev/null | python3 -c '
import json, sys
try:
    data = json.load(sys.stdin)
except Exception:
    data = {}
print(data.get("session_id") or "")
' 2>/dev/null || true)"

if [[ -z "$SESSION_ID" ]] || ! command -v seaglass >/dev/null 2>&1; then
    exit 0
fi

seaglass session end --client-session-id "$SESSION_ID" >/dev/null 2>&1 || true
exit 0

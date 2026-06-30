#!/bin/bash
# Stop / PreCompact hook for the seaglass plugin.
#
# Incrementally uploads the session transcript: reads stdin JSON for
# {session_id, transcript_path}, no-ops unless the SessionStart hook
# exported SEAGLASS_TRANSCRIPT_CAPTURE=on, and hands the offset-cached
# sync to `seaglass session upload-transcript`. Best-effort and
# time-boxed — a slow or failing upload must never block the session;
# the next Stop catches up (server-confirmed offsets make this safe).
set -uo pipefail

if [[ "${SEAGLASS_TRANSCRIPT_CAPTURE:-off}" != "on" ]]; then
    exit 0
fi

INPUT_JSON="$(cat 2>/dev/null || true)"
read -r SESSION_ID TRANSCRIPT_PATH < <(printf '%s' "$INPUT_JSON" | python3 -c '
import json, sys
try:
    data = json.load(sys.stdin)
except Exception:
    data = {}
print(data.get("session_id") or "-", data.get("transcript_path") or "-")
' 2>/dev/null || echo "- -")

if [[ "$SESSION_ID" == "-" || "$TRANSCRIPT_PATH" == "-" || ! -f "$TRANSCRIPT_PATH" ]]; then
    exit 0
fi
if ! command -v seaglass >/dev/null 2>&1; then
    exit 0
fi

timeout 15 seaglass session upload-transcript \
    --path "$TRANSCRIPT_PATH" \
    --client-session-id "$SESSION_ID" >/dev/null 2>&1 || true
exit 0

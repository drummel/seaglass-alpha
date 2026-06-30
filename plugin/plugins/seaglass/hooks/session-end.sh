#!/bin/bash
# SessionEnd hook for the seaglass plugin.
# See docs/adr/0007-plugin-hooks-for-claude-code.md and (transcripts)
# docs/adr/0055-incremental-transcript-upload-via-plugin-hooks.md.
#
# Reads stdin JSON ({session_id, reason, transcript_path, ...}), flushes +
# finalizes the session transcript when capture is on, then calls
# `seaglass session end --client-session-id "$session_id"` so the API can
# flip `sessions.ended_at`. Best-effort: empty id, missing CLI, or any
# CLI error is silent. The TTL sweep (ADR-0008) is the safety net.
set -uo pipefail

INPUT_JSON="$(cat 2>/dev/null || true)"
SESSION_ID="$(printf '%s' "$INPUT_JSON" | python3 -c '
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

# Final transcript flush + finalize (ADR-0055). Silent on any failure —
# the server-side sweep finalizes whatever this misses.
if [[ "${SEAGLASS_TRANSCRIPT_CAPTURE:-off}" == "on" ]]; then
    read -r REASON TRANSCRIPT_PATH < <(printf '%s' "$INPUT_JSON" | python3 -c '
import json, sys
try:
    data = json.load(sys.stdin)
except Exception:
    data = {}
print(data.get("reason") or "other", data.get("transcript_path") or "-")
' 2>/dev/null || echo "other -")
    FLUSH_ARGS=(--client-session-id "$SESSION_ID" --reason "$REASON")
    [[ "$TRANSCRIPT_PATH" != "-" && -f "$TRANSCRIPT_PATH" ]] && FLUSH_ARGS+=(--path "$TRANSCRIPT_PATH")
    timeout 15 seaglass session finalize-transcript "${FLUSH_ARGS[@]}" >/dev/null 2>&1 || true
fi

seaglass session end --client-session-id "$SESSION_ID" >/dev/null 2>&1 || true
exit 0

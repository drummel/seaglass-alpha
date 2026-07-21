#!/bin/bash
# Stop / PreCompact hook for the seaglass plugin. Host-neutral.
#
# Incrementally uploads the session transcript. Reads the transcript-capture
# opt-in from the session env (Claude fast path) or per-session state (cross-host,
# written by session-start), and no-ops unless it is on. Reads {session_id,
# transcript_path} from stdin. Best-effort and time-boxed: a slow or failing
# upload must never block the session; the next Stop catches up (server-confirmed
# offsets make this safe).
set -uo pipefail
. "${BASH_SOURCE[0]%/*}/lib/runtime.sh"

INPUT_JSON="$(cat 2>/dev/null || true)"
SESSION_ID="$(sg_json_field "$INPUT_JSON" session_id)"
TRANSCRIPT_PATH="$(sg_json_field "$INPUT_JSON" transcript_path)"

CAPTURE="${SEAGLASS_TRANSCRIPT_CAPTURE:-}"
[[ -n "$CAPTURE" ]] || CAPTURE="$(sg_state_get "$SESSION_ID" capture)"
if [[ "${CAPTURE:-off}" != "on" ]]; then
    exit 0
fi

if [[ -z "$SESSION_ID" || -z "$TRANSCRIPT_PATH" || ! -f "$TRANSCRIPT_PATH" ]]; then
    exit 0
fi
if ! command -v seaglass >/dev/null 2>&1; then
    exit 0
fi

timeout 15 seaglass session upload-transcript \
    --path "$TRANSCRIPT_PATH" \
    --client-session-id "$SESSION_ID" >/dev/null 2>&1 || true
exit 0

#!/bin/bash
# SessionEnd hook for the seaglass plugin. Claude Code, Codex (which reads the
# same hooks.json), and Cursor (whose hooks file passes `cursor` as the first
# argument).
#
# Codex's Stop is turn-scope (it fires after every assistant response), so it
# is never mapped to `session end`; Codex's own SessionEnd event runs this hook.
#
# On every host this hook flushes + finalizes the transcript when capture is
# on (never on Cursor, where session-start leaves it off), closes the
# agent_sessions row, then clears per-session state. Best-effort: empty id,
# missing CLI, or any CLI error is silent; the TTL sweep is the net.
set -uo pipefail
SG_HOOK_HOST="${1:-}"
. "${BASH_SOURCE[0]%/*}/lib/runtime.sh"

INPUT_JSON="$(cat 2>/dev/null || true)"
SESSION_ID="$(sg_session_id "$INPUT_JSON")"

if [[ -z "$SESSION_ID" ]] || ! command -v seaglass >/dev/null 2>&1; then
    sg_state_clear "$SESSION_ID"
    exit 0
fi

# Final transcript flush + finalize. Silent on any failure — the server-side
# sweep finalizes whatever this misses.
CAPTURE="${SEAGLASS_TRANSCRIPT_CAPTURE:-}"
[[ -n "$CAPTURE" ]] || CAPTURE="$(sg_state_get "$SESSION_ID" capture)"
if [[ "${CAPTURE:-off}" == "on" ]]; then
    REASON="$(sg_json_field "$INPUT_JSON" reason)"
    [[ -n "$REASON" ]] || REASON="other"
    TRANSCRIPT_PATH="$(sg_json_field "$INPUT_JSON" transcript_path)"
    FLUSH_ARGS=(--client-session-id "$SESSION_ID" --reason "$REASON")
    [[ -n "$TRANSCRIPT_PATH" && -f "$TRANSCRIPT_PATH" ]] && FLUSH_ARGS+=(--path "$TRANSCRIPT_PATH")
    sg_with_timeout 15 seaglass session finalize-transcript "${FLUSH_ARGS[@]}" >/dev/null 2>&1 || true
fi

seaglass session end --client-session-id "$SESSION_ID" >/dev/null 2>&1 || true
sg_state_clear "$SESSION_ID"
exit 0

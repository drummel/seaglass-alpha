#!/bin/bash
# SessionStart hook for the seaglass plugin.
#
# Reads stdin JSON ({session_id, source, ...}), writes
# SEAGLASS_CLIENT_SESSION_ID into $CLAUDE_ENV_FILE so the rest of the
# session (CLI + stdio shim) attributes writes to one `sessions` row,
# and emits the user's seaglass://profile markdown as additionalContext.
# Degrades to a one-line nudge if seaglass is missing, unauthed, or
# returns nothing — never blocks the session.
set -uo pipefail

# Emit a SessionStart hook decision wrapping the given additionalContext.
emit() {
    python3 -c '
import json, sys
print(json.dumps({"hookSpecificOutput": {
    "hookEventName": "SessionStart",
    "additionalContext": sys.argv[1],
}}))
' "$1"
}

INPUT_JSON="$(cat 2>/dev/null || true)"
SESSION_ID="$(printf '%s' "$INPUT_JSON" | python3 -c '
import json, sys
try:
    data = json.load(sys.stdin)
except Exception:
    data = {}
print(data.get("session_id") or "")
' 2>/dev/null || true)"

# Pin all this chat'\''s writes to one `sessions` row server-side. The
# `seaglass` stdio shim forwards SEAGLASS_CLIENT_SESSION_ID as the
# x-seaglass-client-session header; the API branches on it.
if [[ -n "$SESSION_ID" && -n "${CLAUDE_ENV_FILE:-}" ]]; then
    printf 'export SEAGLASS_CLIENT_SESSION_ID=%s\n' "$SESSION_ID" >> "$CLAUDE_ENV_FILE"
fi

# Transcript capture: resolve the user's opt-in once and pin
# it into the session env so the per-turn Stop/PreCompact hooks can no-op
# without a network round trip. Default off on any failure.
if [[ -n "${CLAUDE_ENV_FILE:-}" ]] && command -v seaglass >/dev/null 2>&1; then
    CAPTURE="$(timeout 10 seaglass session transcript-config 2>/dev/null || echo off)"
    [[ "$CAPTURE" == "on" ]] || CAPTURE="off"
    printf 'export SEAGLASS_TRANSCRIPT_CAPTURE=%s\n' "$CAPTURE" >> "$CLAUDE_ENV_FILE"
fi

if ! command -v seaglass >/dev/null 2>&1; then
    emit "The Seaglass plugin is installed but the \`seaglass\` CLI is not on PATH. Tell the user to run \`uv tool install seaglass\` (or \`pipx install seaglass\`) and restart this session."
    exit 0
fi

if ! seaglass auth status >/dev/null 2>&1; then
    emit "Seaglass is not authenticated. Tell the user to run \`seaglass auth login\` once in a terminal, approve in the browser, then restart this session. The token caches at ~/.config/seaglass/token."
    exit 0
fi

PROFILE="$(seaglass me 2>/dev/null || true)"
if [[ -z "$PROFILE" ]]; then
    emit "Seaglass returned no profile content. The user can run \`seaglass auth status\` to check token / deployment, then \`seaglass me\` to verify."
    exit 0
fi

# Resume briefing: append a digest of this agent's previous
# session so the conversation starts with continuity. Best-effort and
# deterministic (no LLM); empty when there's no prior session worth
# summarizing, in which case we emit the profile alone.
BRIEFING="$(timeout 10 seaglass session briefing 2>/dev/null || true)"
if [[ -n "$BRIEFING" ]]; then
    emit "$PROFILE

$BRIEFING"
    exit 0
fi

emit "$PROFILE"
exit 0

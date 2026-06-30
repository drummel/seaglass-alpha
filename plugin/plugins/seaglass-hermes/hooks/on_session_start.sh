#!/bin/bash
# Hermes on_session_start hook for Seaglass.
#
# Hermes exposes a DIFFERENT four-hook contract from Claude Code
# (pre_llm_call / post_llm_call / on_session_start / on_session_end).
# The logic stays in the `seaglass` CLI; only this thin shim varies. Confirm
# Hermes' exact hook stdin/stdout contract against live docs at build time.
#
# Reads stdin JSON ({session_id, ...}), pins the chat to one `sessions` row via
# SEAGLASS_CLIENT_SESSION_ID, and prints the user's profile markdown on stdout
# for Hermes to inject as context. Degrades to a silent no-op if `seaglass` is
# missing, unauthed, or returns nothing — never blocks the session.
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

if [[ -n "$SESSION_ID" ]]; then
    export SEAGLASS_CLIENT_SESSION_ID="$SESSION_ID"
fi

command -v seaglass >/dev/null 2>&1 || exit 0
seaglass auth status >/dev/null 2>&1 || exit 0
seaglass me 2>/dev/null || true
exit 0

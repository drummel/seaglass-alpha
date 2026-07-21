#!/bin/bash
# SessionStart hook for the seaglass plugin. Host-neutral: runs under both
# Claude Code (CLAUDE_ENV_FILE / CLAUDE_PLUGIN_ROOT) and ChatGPT/Codex
# (PLUGIN_ROOT / PLUGIN_DATA).
#
# Persists per-session state under the plugin data dir, pins CLI/stdio write
# attribution on Claude, and emits the user's profile + resume briefing as
# model-visible SessionStart context. Degrades to a one-line nudge if seaglass
# is missing, unauthed, or returns nothing, and never blocks the session.
set -uo pipefail
. "${BASH_SOURCE[0]%/*}/lib/runtime.sh"

# Emit SessionStart context in the host's native shape.
emit() {
    local ctx="$1"
    if sg_is_claude_host; then
        # Claude Code's documented SessionStart output contract.
        python3 -c 'import json,sys; print(json.dumps({"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":sys.argv[1]}}))' "$ctx"
    else
        # Codex also accepts model-visible SessionStart context; its exact
        # envelope is unverified against the live docs, so emit the shared
        # additionalContext shape and adjust this branch once confirmed.
        python3 -c 'import json,sys; print(json.dumps({"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":sys.argv[1]}}))' "$ctx"
    fi
}

INPUT_JSON="$(cat 2>/dev/null || true)"
SESSION_ID="$(sg_json_field "$INPUT_JSON" session_id)"

# Pin all this chat's writes to one agent_sessions row server-side. On Claude,
# the writable CLAUDE_ENV_FILE carries SEAGLASS_CLIENT_SESSION_ID to the CLI +
# stdio shim (forwarded as the x-seaglass-client-session header; the API
# branches on it). Codex has no writable env file, so per-write CLI attribution
# there is deferred (the MCP connector carries session identity server-side);
# the id still lands in session state for the transcript hooks.
sg_state_set "$SESSION_ID" client-session "$SESSION_ID"
if [[ -n "$SESSION_ID" ]] && sg_is_claude_host; then
    printf 'export SEAGLASS_CLIENT_SESSION_ID=%s\n' "$SESSION_ID" >>"$CLAUDE_ENV_FILE"
fi

# Resolve the transcript-capture opt-in once and pin it into per-session state
# so the per-turn Stop/PreCompact hooks no-op without a network round trip.
# Default off on any failure. On Claude, also mirror to CLAUDE_ENV_FILE (the
# original fast path); the state file is the cross-host source of truth.
if command -v seaglass >/dev/null 2>&1; then
    CAPTURE="$(timeout 10 seaglass session transcript-config 2>/dev/null || echo off)"
    [[ "$CAPTURE" == "on" ]] || CAPTURE="off"
    sg_state_set "$SESSION_ID" capture "$CAPTURE"
    if sg_is_claude_host; then
        printf 'export SEAGLASS_TRANSCRIPT_CAPTURE=%s\n' "$CAPTURE" >>"$CLAUDE_ENV_FILE"
    fi
fi

if ! command -v seaglass >/dev/null 2>&1; then
    emit "The Seaglass plugin is installed but the \`seaglass\` CLI is not on PATH. Tell the user to run \`curl -fsSL https://raw.githubusercontent.com/drummel/seaglass-alpha/main/cli/install.sh | bash\` and restart this session. (On the remote connector, profile and preferences still arrive over MCP; the CLI adds transcript capture and the resume briefing.)"
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

# Resume briefing: append a digest of this agent's previous session so the
# conversation starts with continuity. Best-effort and deterministic (no LLM);
# empty when there's no prior session worth summarizing, in which case we emit
# the profile alone.
BRIEFING="$(timeout 10 seaglass session briefing 2>/dev/null || true)"
if [[ -n "$BRIEFING" ]]; then
    emit "$PROFILE

$BRIEFING"
    exit 0
fi

emit "$PROFILE"
exit 0

#!/bin/bash
# SessionStart hook for the seaglass plugin. Host-neutral: runs under both
# Claude Code (CLAUDE_ENV_FILE / CLAUDE_PLUGIN_ROOT) and ChatGPT/Codex
# (PLUGIN_ROOT / PLUGIN_DATA).
#
# Persists per-session state under the plugin data dir, pins CLI/stdio write
# attribution on Claude, and emits the user's profile + resume briefing as
# model-visible SessionStart context. When the CLI is missing or unauthed it
# degrades to instructing the agent to load the same context over MCP (it is an
# authenticated MCP client; this hook is not), and never blocks the session.
set -uo pipefail
. "${BASH_SOURCE[0]%/*}/lib/runtime.sh"

# The model does not reliably know the current date and will otherwise
# fabricate one (anchoring to its training era), corrupting event_time on
# writes and scope_hints windows on time-scoped reads. Every emission leads
# with it, the degraded paths included: an empty profile still leaves a
# working, authenticated CLI that can write with a fabricated date.
DATELINE="Today's date is $(date -u +%Y-%m-%d) (UTC). Use it to resolve any relative time the user mentions (\"last week\", \"yesterday\", \"in April\"); never guess the date."

# Emit SessionStart context in the host's native shape, always led by the dateline.
emit() {
    local ctx="$DATELINE

$1"
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
    CAPTURE="$(sg_with_timeout 10 seaglass session transcript-config 2>/dev/null || echo off)"
    [[ "$CAPTURE" == "on" ]] || CAPTURE="off"
    sg_state_set "$SESSION_ID" capture "$CAPTURE"
    if sg_is_claude_host; then
        printf 'export SEAGLASS_TRANSCRIPT_CAPTURE=%s\n' "$CAPTURE" >>"$CLAUDE_ENV_FILE"
    fi
fi

# The installer URL is filled in per distribution channel at publish time; an
# unpublished (source) copy still holds the placeholder, so fall back to prose.
INSTALL_URL="https://raw.githubusercontent.com/drummel/seaglass-alpha/main/cli/install.sh"
# The whole "run ..." fragment is built here so the emit below does not have to
# know whether it got a command (backticked) or prose (not).
INSTALL_HINT="run \`curl -fsSL ${INSTALL_URL} | bash\`"
[[ "$INSTALL_URL" == *"{{"* ]] && INSTALL_HINT="run the Seaglass CLI installer for this deployment"

# No CLI: do not dead-end on an install nudge. This hook cannot speak MCP
# itself (a shell process has no connection and no access to the host's OAuth
# token), but the agent reading this text is an authenticated MCP client, so
# hand it the read. Covers the hedge in mcp/guidance.py, whose fallback order
# assumes "most MCP hosts auto-load resources at init" -- where that does not
# hold, this makes the read explicit. The CLI stays the power-up for the two
# things MCP cannot do here: transcript capture and session close.
if ! command -v seaglass >/dev/null 2>&1; then
    emit "Load the user's Seaglass context now, before your first reply: read the \`seaglass://profile\` resource, and call \`get_started\` for account, library, and anything outstanding. Follow the behavioral rules the profile carries.

If those tools are not available, Seaglass is not connected to this client -- tell the user to add the connector and approve it in the browser.

The \`seaglass\` CLI is not on PATH. Memory reads and writes work without it over the connector; it adds transcript capture and the resume briefing. Mention it only if the user asks, or wants those: ${INSTALL_HINT}."
    exit 0
fi

# CLI present but unauthed. The connector is a separate credential and may well
# be working, so take the same MCP path rather than blocking on a CLI login the
# user may not need.
if ! seaglass auth status >/dev/null 2>&1; then
    emit "Load the user's Seaglass context now, before your first reply: read the \`seaglass://profile\` resource, and call \`get_started\` for account, library, and anything outstanding.

If those tools are not available, Seaglass is not connected to this client -- tell the user to add the connector and approve it in the browser.

The \`seaglass\` CLI is installed but not authenticated, so transcript capture and the resume briefing are off. To enable them the user runs \`seaglass auth login\` once in a terminal and restarts this session; the token caches at ~/.config/seaglass/token. Mention it only if they ask, or want those."
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
BRIEFING="$(sg_with_timeout 10 seaglass session briefing 2>/dev/null || true)"
if [[ -n "$BRIEFING" ]]; then
    emit "$PROFILE

$BRIEFING"
    exit 0
fi

emit "$PROFILE"
exit 0

#!/bin/bash
# SessionStart hook for the seaglass plugin. Host-neutral: runs under both
# Claude Code (CLAUDE_ENV_FILE / CLAUDE_PLUGIN_ROOT) and ChatGPT/Codex
# (PLUGIN_ROOT / PLUGIN_DATA).
#
# Persists per-session state under the plugin data dir, pins CLI/stdio write
# attribution on Claude, and states the session's transport as model-visible
# SessionStart context: a signed-in CLI means CLI mode (the transport line, the
# profile and the resume briefing); anything else means the Seaglass tools, with a
# pointer to start_session and, once ever, the CLI install offer. It
# never blocks the session.
set -uo pipefail
. "${BASH_SOURCE[0]%/*}/lib/runtime.sh"

# Emit SessionStart context in the host's native shape. It states only what this
# hook alone knows (which transport is live, the one-time CLI offer, which call
# opens the session); the date, the core rules and the preferences reach the
# agent from the server, so each rule keeps one home and none is restated here.
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
# The env file reaches the agent's later commands, not this hook, so its own CLI
# calls below need the id too: without it `seaglass session start` marked a
# throwaway server session, and every write in the chat read as unstarted.
if [[ -n "$SESSION_ID" ]]; then
    export SEAGLASS_CLIENT_SESSION_ID="$SESSION_ID"
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

# MCP mode: the Seaglass tools are the path, and start_session is the first
# call of every session: it returns who the user is, the preferences and custom instructions, the core
# and the map of their libraries. The last sentence is there because recorded
# replies opened by summarizing the profile back to the user, and one repeated a
# private figure while doing it. "As you would have without the call" is there
# because an agent-mode run read the profile, then took the user's stated fact
# as background and captured nothing (2026-09-23).
ORIENT="Seaglass is on its tools in this session. Call its \`start_session\` tool before anything else, without announcing it: it returns who the user is, their preferences and custom instructions, the rules for using Seaglass, and a map of the libraries and collections you can reach. Take it in quietly, then do what the user's message calls for, as you would have without the call: it is context for you, not news for them."

# No CLI: offer it once, ever, and record that the offer was made in the
# plugin's data directory, which the host keeps across sessions. The transport
# is detected here, on the machine, and stated to the agent rather than guessed.
if ! command -v seaglass >/dev/null 2>&1; then
    if sg_flag_get cli-offer-made; then
        emit "$ORIENT"
        exit 0
    fi
    sg_flag_set cli-offer-made
    emit "$ORIENT

The \`seaglass\` CLI is not installed here. It adds transcript capture and the resume briefing, and it drives the same memory from a shell for less context per call. Offer it once, only if the work makes it relevant: ${INSTALL_HINT}, then \`seaglass auth login\`. This is the only time it is mentioned."
    exit 0
fi

# CLI present but unauthed. The connector is a separate credential and may well
# be working, so stay on the tools rather than block on a CLI sign-in.
if ! seaglass auth status >/dev/null 2>&1; then
    emit "$ORIENT

The \`seaglass\` CLI is installed but not signed in, so transcript capture and the resume briefing are off. If the user wants them, offer once to run \`seaglass auth login\` for them: it opens a browser and waits for their approval, and the token then caches at ~/.config/seaglass/token."
    exit 0
fi

# CLI mode: a signed-in CLI is the transport for this session.
TRANSPORT="The \`seaglass\` CLI is signed in here, so it is the transport for this session: run the Seaglass operations as \`seaglass\` commands, as the \`seaglass-cli\` skill spells them."

# The CLI's start_session: the profile, the preferences and any setup step, and
# the server records that this session started.
PROFILE="$(sg_with_timeout 10 seaglass session start 2>/dev/null || true)"
if [[ -z "$PROFILE" ]]; then
    emit "$TRANSPORT

Seaglass returned no profile content. The user can run \`seaglass auth status\` to check token / deployment, then \`seaglass session start\` to verify."
    exit 0
fi
PROFILE_LEAD="Your Seaglass session, started for you with \`seaglass session start\` (run it again only for a refresh):"

# Resume briefing: append a digest of this agent's previous session so the
# conversation starts with continuity. Best-effort and deterministic (no LLM);
# empty when there's no prior session worth summarizing, in which case we emit
# the profile alone.
BRIEFING="$(sg_with_timeout 10 seaglass session briefing 2>/dev/null || true)"
if [[ -n "$BRIEFING" ]]; then
    emit "$TRANSPORT

$PROFILE_LEAD

$PROFILE

$BRIEFING"
    exit 0
fi

emit "$TRANSPORT

$PROFILE_LEAD

$PROFILE"
exit 0

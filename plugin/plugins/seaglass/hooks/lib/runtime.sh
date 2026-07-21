#!/bin/bash
# Host-neutral runtime helpers shared by the Seaglass session hooks
# (session-start.sh / transcript-flush.sh / session-end.sh). Sourced, not run.
#
# Works under both Claude Code (CLAUDE_PLUGIN_ROOT / CLAUDE_ENV_FILE) and
# ChatGPT/Codex (PLUGIN_ROOT / PLUGIN_DATA, with CLAUDE_* aliases set for
# compatibility).

# Per-session state directory. Prefer the plugin's writable data dir
# (PLUGIN_DATA on Codex, CLAUDE_PLUGIN_DATA as its alias); fall back to a
# stable config path so the hooks work even if neither is set.
sg_state_dir() {
    local base="${PLUGIN_DATA:-${CLAUDE_PLUGIN_DATA:-$HOME/.config/seaglass/plugin-state}}"
    printf '%s/sessions' "$base"
}

# Persist one key/value for a session (one file per key). No-op on empty id.
sg_state_set() {
    local session_id="$1" key="$2" value="$3" dir
    [[ -n "$session_id" ]] || return 0
    dir="$(sg_state_dir)"
    mkdir -p "$dir" 2>/dev/null || return 0
    printf '%s\n' "$value" >"$dir/$session_id.$key" 2>/dev/null || return 0
}

# Read a session key back; prints the value (empty if absent). Trailing newline
# stripped so callers can string-compare.
sg_state_get() {
    local session_id="$1" key="$2" f
    [[ -n "$session_id" ]] || return 0
    f="$(sg_state_dir)/$session_id.$key"
    [[ -f "$f" ]] || return 0
    tr -d '\n' <"$f" 2>/dev/null || true
}

# Best-effort cleanup of a session's state files (call from SessionEnd).
sg_state_clear() {
    local session_id="$1" dir
    [[ -n "$session_id" ]] || return 0
    dir="$(sg_state_dir)"
    rm -f "$dir/$session_id".* 2>/dev/null || true
}

# True on the Claude host. Claude Code uniquely exposes CLAUDE_ENV_FILE (a
# writable env file); Codex sets the CLAUDE_PLUGIN_ROOT/DATA aliases but not
# CLAUDE_ENV_FILE, so this reliably discriminates the host.
sg_is_claude_host() {
    [[ -n "${CLAUDE_ENV_FILE:-}" ]]
}

# Parse a string field from a hook's stdin JSON.
# Usage: sg_json_field "$INPUT_JSON" session_id
sg_json_field() {
    printf '%s' "$1" | python3 -c '
import json, sys
try:
    data = json.load(sys.stdin)
except Exception:
    data = {}
print(data.get(sys.argv[1]) or "")
' "$2" 2>/dev/null || true
}

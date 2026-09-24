#!/bin/bash
# Host-neutral runtime helpers shared by the Seaglass session hooks
# (session-start.sh / transcript-flush.sh / session-end.sh). Sourced, not run.
#
# Works under Claude Code (CLAUDE_PLUGIN_ROOT / CLAUDE_ENV_FILE), ChatGPT/Codex
# (PLUGIN_ROOT / PLUGIN_DATA, with CLAUDE_* aliases set for compatibility), and
# Cursor, which names itself with a `cursor` argument in its hooks file because
# it documents no variable a script could tell it apart by.

# The host a script was started by, from its first argument ("cursor"), set by
# each hook before it sources this file.
SG_HOOK_HOST="${SG_HOOK_HOST:-}"

# The plugin's writable data dir, kept across sessions (PLUGIN_DATA on Codex,
# CLAUDE_PLUGIN_DATA as its alias); fall back to a stable config path so the
# hooks work even if neither is set.
sg_data_dir() {
    printf '%s' "${PLUGIN_DATA:-${CLAUDE_PLUGIN_DATA:-$HOME/.config/seaglass/plugin-state}}"
}

# Per-session state directory.
sg_state_dir() {
    printf '%s/sessions' "$(sg_data_dir)"
}

# A plugin-wide flag that outlives the session (e.g. a one-time offer was made).
sg_flag_set() {
    local dir
    dir="$(sg_data_dir)/flags"
    mkdir -p "$dir" 2>/dev/null || return 0
    : >"$dir/$1" 2>/dev/null || return 0
}

# True when the flag was set by an earlier session.
sg_flag_get() {
    [[ -f "$(sg_data_dir)/flags/$1" ]]
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

# True on the Cursor host.
sg_is_cursor_host() {
    [[ "$SG_HOOK_HOST" == "cursor" ]]
}

# True on the Claude host. Claude Code uniquely exposes CLAUDE_ENV_FILE (a
# writable env file); Codex sets the CLAUDE_PLUGIN_ROOT/DATA aliases but not
# CLAUDE_ENV_FILE, so this reliably discriminates the host.
sg_is_claude_host() {
    [[ -n "${CLAUDE_ENV_FILE:-}" ]]
}

# The chat's id from a hook's stdin JSON: `session_id`, or on Cursor the
# `conversation_id` it also sends, whichever is present.
# Usage: sg_session_id "$INPUT_JSON"
sg_session_id() {
    local id
    id="$(sg_json_field "$1" session_id)"
    [[ -n "$id" ]] || id="$(sg_json_field "$1" conversation_id)"
    printf '%s' "$id"
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

# Run a command under a wall-clock limit where the host can enforce one.
# GNU coreutils `timeout` is on every Linux box; stock macOS has neither it
# nor Homebrew's `gtimeout` unless the user installed coreutils. Falling back
# to running the command unbounded keeps the hook working there: the CLI
# calls it wraps are short and have their own network timeouts, and the
# alternative (every call failing) silently turned off transcript capture and
# the resume briefing for every Mac user.
# Usage: sg_with_timeout <seconds> <command> [args...]
sg_with_timeout() {
    local secs="$1"
    shift
    if command -v timeout >/dev/null 2>&1; then
        timeout "$secs" "$@"
    elif command -v gtimeout >/dev/null 2>&1; then
        gtimeout "$secs" "$@"
    else
        "$@"
    fi
}

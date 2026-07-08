# Seaglass — Hermes plugin

> **Status: experimental.** This plugin is **not** published to the Seaglass
> marketplace and the Hermes hook contract is **unverified** — confirm the exact
> stdin/stdout contract against the live Hermes docs before relying on it (see
> the note below). Treat everything here as a docs-grade sketch, not a shipped
> integration.

A native [Hermes](https://github.com/nousresearch/hermes-agent) plugin that
overlays **cross-tool, user-level memory** on top of Hermes' own learning. The
MCP connector reaches Seaglass via `seaglass bridge`; a four-hook adapter wires
Seaglass into Hermes' session lifecycle.

> **Hooks differ per platform.** Hermes' contract (`pre_llm_call` /
> `post_llm_call` / `on_session_start` / `on_session_end`) is *not* Claude
> Code's (`SessionStart` / `SessionEnd` / `PreToolUse` / `PostToolUse`). The
> logic stays in the `seaglass` CLI — only the thin shims in `hooks/` vary.
> **Confirm the exact hook stdin/stdout contract against the live
> Hermes docs at build time** — the shims here follow our docs-grade tear-down.

## What the hooks do

| Hook | Shim | Behavior |
|---|---|---|
| `on_session_start` | `hooks/on_session_start.sh` | Pin the chat to one `sessions` row and print `seaglass me` (the profile) for Hermes to inject as context. |
| `on_session_end` | `hooks/on_session_end.sh` | `seaglass session end` so the API flips `sessions.ended_at`. |
| `pre_llm_call` | `hooks/pre_llm_call.sh` | Reserved no-op (context injection happens at session start). |
| `post_llm_call` | `hooks/post_llm_call.sh` | Reserved no-op (capture is agent-driven, not hook-forced). |

Every shim degrades to a silent no-op when `seaglass` is missing, unauthed, or
returns nothing — it never blocks a session.

## Install

1. Install the CLI with `curl -fsSL https://raw.githubusercontent.com/drummel/seaglass-alpha/main/cli/install.sh | bash`, then
   `seaglass auth login` once.
2. Drop this directory into Hermes' plugins path and enable the `seaglass`
   plugin (registers the MCP server + the four hooks from `hermes-plugin.json`).

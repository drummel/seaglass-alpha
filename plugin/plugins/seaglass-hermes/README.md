# Seaglass — Hermes plugin

> **Status: experimental, and now known not to work.** This plugin is **not**
> published to the Seaglass marketplace. Its hook contract was carried for a
> while as *unverified*; it has since been **verified against
> [`NousResearch/hermes-agent`](https://github.com/NousResearch/hermes-agent) at
> v0.21.3 (2026-09-17) and is wrong**. Hermes would not load this plugin, and
> its hooks would never fire. Nothing here has been changed yet — the files are
> left as-is so the rewrite is a deliberate piece of work rather than a
> drive-by. **Read [What is actually wrong](#what-is-actually-wrong-verified)
> below before touching anything in this directory.**

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

## What is actually wrong (verified)

All four hook **names** below are real Hermes hooks — Hermes has 38 valid hook
names and these are four of them. The names are not the problem. The mechanism
is, in four separate ways:

1. **`hermes-plugin.json` is not a manifest Hermes reads.** The string appears
   nowhere in the Hermes source. A directory plugin needs a **`plugin.yaml`**
   plus an `__init__.py` exposing a synchronous `register(ctx)`. The only JSON
   manifest Hermes understands is the portable Agent Plugins v1 `plugin.json`,
   whose field set is closed and carries no hooks. A pip-installed plugin
   registers through the **`hermes_agent.plugins` entry-point group** and has
   its manifest synthesized from distribution metadata instead.
2. **A `hooks` key is silently inert.** `hooks` *is* in Hermes'
   known-manifest-field list, so it raises no "unknown field" warning, but the
   manifest parser never reads it. The field Hermes parses is `provides_hooks`,
   and even that is advisory: it feeds `hermes plugins list` and
   `hermes plugins doctor`, and registers nothing.
3. **Plugin hooks are Python callables**, registered at runtime with
   `ctx.register_hook(name, callback)` from inside `register(ctx)`. Shell hooks
   are real in Hermes, with a stdin/stdout JSON contract much like the one these
   shims assume — but they are declared by the **operator** in
   `~/.hermes/config.yaml` under a top-level `hooks:` block. A plugin cannot
   ship them.
4. **`mcp_servers` is not a plugin manifest key.** MCP servers come from
   operator config, from a portable package's separate `mcp.json`, or from
   `ctx.call_mcp()` against an operator-managed allowlist.

**The deeper problem is the injection design, not the packaging.**
`on_session_start`'s return value is **ignored**. `pre_llm_call` is the only
hook whose return value matters, and what it returns is injected into the
**current turn's user message** — never the system prompt, deliberately, to
preserve the prompt cache. The sanctioned system-prompt route is not a hook at
all: `ctx.register_system_prompt_section(id, content, position=…)`. So the table
below is backwards: the session-start shim cannot inject anything, and the
`pre_llm_call` shim it marks as a reserved no-op is the one that could.

**Before rewriting, decide which seat we want.** Hermes has a separate
**`hermes_agent.memory_providers`** entry point whose interface
(`initialize`, `prefetch`, a non-blocking `sync_turn`, `on_session_end(messages)`,
plus `get_tool_schemas` / `handle_tool_call` for its own tools) is much closer to
what Seaglass is than a hook plugin. The cost is exclusivity: only one external
memory provider can be active at a time, so it would be Seaglass *or* Mnemosyne,
not both. Note also that `on_session_end` exists in **both** worlds with
different signatures — as a plugin hook taking
`(session_id, completed, interrupted, model, platform)` and as a provider method
taking `(messages)`.

## What the hooks do

> The table below describes the **current, non-working** shims. It is kept as a
> record of intent, not as a description of behavior. See above.

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

> **These install steps do not work as written.** Hermes will not discover a
> directory plugin without a `plugin.yaml`, and will not read hooks or MCP
> servers out of `hermes-plugin.json`. Left in place as the record of intent
> until the rewrite; see [What is actually wrong](#what-is-actually-wrong-verified).

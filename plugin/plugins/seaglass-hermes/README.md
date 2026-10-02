# Seaglass for Hermes

A [Hermes](https://github.com/NousResearch/hermes-agent) plugin that brings your
Seaglass memory into every Hermes session. It sits alongside whatever memory
provider Hermes already runs (built-in, Honcho, Mem0) rather than replacing it.

Verified against Hermes v0.21.4, and installed live on v0.21.5.

## Install

Two commands. The plugin and the connector are separate because a Hermes
plugin cannot declare an MCP server.

1. **Connect Seaglass's memory tools** (browser sign-in, no CLI needed):

   ```bash
   hermes mcp add seaglass --url https://api-stg.seaglassai.com/mcp --auth oauth
   ```

2. **Install and enable the plugin:**

   ```bash
   hermes plugins install drummel/seaglass-alpha/plugin/plugins/seaglass-hermes --enable
   ```

Start a new Hermes session. Update later with `hermes plugins update seaglass-hermes`.

## What it does

| Hermes surface | What Seaglass does there |
|---|---|
| System prompt section `seaglass.orientation` | A short fixed note: Seaglass is connected, and the agent calls the Seaglass `start_session` tool before anything else (and again after Hermes compacts the context), without announcing it. That call loads your profile, preferences, custom instructions, the rules for using Seaglass, and what your other recent chats with this agent captured. |

The plugin opens and closes no Seaglass session of its own: the connector's
`start_session` opens the one your memory writes land on.

The plugin runs no `seaglass` CLI and registers no hooks.

## Not supported on Hermes yet

- **Transcript capture.** The Claude Code plugin uploads the session transcript
  file. Hermes keeps its transcript in its own database, not a file the CLI can
  read, so there is nothing to upload yet.
- **Per-turn recall.** Nothing is injected after the first turn. The agent searches
  Seaglass with the connector's `search` tool when it needs to.

## Troubleshooting

- `hermes plugins list` should show `seaglass-hermes` as enabled.
- `hermes mcp list` should show the Seaglass server under the name you added it
  as: `seaglass` in step 1, or the name the Seaglass Connect page used (outside
  production it adds the environment, as in `seaglass-<environment>`). If its tools time out,
  run `hermes mcp login <that name>` to redo the browser sign-in.

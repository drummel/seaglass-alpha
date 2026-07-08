# Seaglass (alpha)

Seaglass is a memory layer for people and teams of humans and AI agents. It captures and recalls context about people, projects, and topics across conversations, so the right memory flows back into whatever agent you are using.

This repository is the installable surface: the plugins, the `seaglass` CLI, and the marketplace manifest. The server runs elsewhere.

## Connect in under a minute

Add the Seaglass connector URL (`<server>/mcp`) as a custom connector in your client, then approve the connection in the browser. That is the whole setup. It works in claude.ai, Claude Desktop, Cowork, Cursor, and Claude Code, and a connector added once reaches the web, desktop, and mobile.

For this alpha, the hosted server is `https://seaglass-api-stg.onrender.com`, so the connector URL is:

```
https://seaglass-api-stg.onrender.com/mcp
```

The Connections page in the Seaglass web app has a one-click "Add to Claude" button and copyable recipes for every client, so you rarely need to type the URL by hand.

Once connected, ask your agent "What do you know about me?" to confirm it can read from your library.

## Optional power-up: the `seaglass` CLI

The connector is all most people need. The `seaglass` CLI is an optional add-on for token-cheap, shell-capable clients like Claude Code: it drives the same backend over `bash` instead of injecting a JSON tool schema into every turn, which lowers per-turn cost. It is not required to use Seaglass.

If you want it, install the prebuilt binary (no toolchain required):

```bash
# Downloads the right binary for your OS/arch from this repo's Releases and verifies the checksum:
curl -fsSL https://raw.githubusercontent.com/drummel/seaglass-alpha/main/cli/install.sh | bash
seaglass auth login   # opens the browser, caches a token
```

See [`cli/README.md`](cli/README.md) for the full command surface and [`plugin/README.md`](plugin/README.md) for the plugins (capture skill plus session lifecycle hooks) that build on top of it.

## What is in this repo

| Path | What |
|---|---|
| `cli/` | The `seaglass` command-line client. |
| `plugin/` | The Claude plugins: capture skill, session hooks, and CLI transport. |
| `.claude-plugin/marketplace.json` | The plugin marketplace manifest. |

This is an install-only mirror. The API, web app, and internal docs live in the main Seaglass repository.

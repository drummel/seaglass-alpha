# Seaglass Memory Plugin

Connects Claude to the Seaglass personal memory layer. Once installed, Claude automatically captures and recalls context about people, projects, and topics across conversations.

One plugin, `seaglass`, does the whole job. It bundles:

- **The remote memory connector** — the plugin declares Seaglass's hosted MCP endpoint (`<server>/mcp`), and the host runs its own browser sign-in for it. No local process, no token to copy. This is the full agent-facing tool surface: starting a session (`start_session`, the first call of every session, which returns the user's profile, preferences and any setup step), reading (`search`), writing (`store_memory`, `store_document`), retiring/reclassifying (`update_memory`), reconsolidating (`reconsolidate_memory`), authoring and editing wiki pages (`create_page`, `edit_page`/`edit_section`, `append_section`, `revert_page`, `move_page`, `get_page_history`), and tracing back through past sessions (`transcript_search`, `transcript_read`).
- **The capture skill** (`seaglass-memory`) — teaches Claude when and how to read and write memories from conversation signals, how to author wiki pages in the house voice, how to correct what memory holds, and how to handle private content.
- **The CLI skill** (`seaglass-cli`): it maps the same operations onto the `seaglass` CLI for shell-capable clients (the token-cheap path; see [Tools / commands](#tools--commands)). It loads when the session's transport is the CLI, or when the agent has a shell and no Seaglass tools.
- **A `/seaglass:status` command** — reports whether this client is actually connected to Seaglass and, if not, the one step that connects it.
- **Session lifecycle hooks** (Claude Code, and any host that runs command hooks) — `SessionStart` states before the first turn whether the CLI or the tools are this session's transport: on the tools it tells the agent to call `start_session` first, and with a signed-in CLI it runs `seaglass session start` and injects what it prints (the profile and any setup step); `SessionEnd` closes the `sessions` row server-side. Hosts that ignore hooks fall back to the `/recall` and `/checkpoint` skills.

The hooks shell out to the `seaglass` CLI, so the CLI is the plugin's second, optional prerequisite: without it the connector still works and the profile still arrives over MCP, but there is no automatic profile injection, transcript capture, or resume briefing.

**Just want the connector?** You do not need the plugin at all. Add your Seaglass server's connector URL (`<server>/mcp`) as a custom connector in claude.ai, Claude Desktop, Cowork, Cursor, or Claude Code, approve in the browser, and `search` works. The Connections page in the Seaglass web app has one-click buttons and copyable recipes for every client.

A second, **experimental** plugin (`plugin/plugins/seaglass-hermes/`) targets the [Hermes](https://github.com/nousresearch/hermes-agent) agent. It is intentionally **not** published to the marketplace — its hook contract is unverified — so `marketplace.json` lists only `seaglass`. See its README before relying on it.

## Prerequisites

The connector needs nothing installed. For the hooks and the CLI path:

1. **Install the `seaglass` CLI** (one-time):

   ```bash
   curl -fsSL https://raw.githubusercontent.com/drummel/seaglass-alpha/main/cli/install.sh | bash   # installs the prebuilt binary
   ```

2. **Authenticate the CLI**:

   ```bash
   seaglass auth login
   ```

   This opens the Seaglass admin UI in your browser, asks you to approve the connection, and stores a bearer token at `~/.config/seaglass/token`. The hooks and every `seaglass` command pick it up from there. This is a separate credential from the connector's browser sign-in: the connector authorizes the host, the CLI token authorizes the binary.

   For a non-default deployment, set `SEAGLASS_URL` before logging in:

   ```bash
   export SEAGLASS_URL="https://your-seaglass-instance.example.com"
   seaglass auth login
   ```

## Install in Claude Code

```bash
# 1. Add the marketplace
/plugin marketplace add drummel/seaglass-alpha

# 2. Install the plugin (connector + skills + hooks)
/plugin install seaglass@seaglass-memory

# 3. Authorize the connector
/mcp            # pick seaglass, choose Authenticate, approve in the browser
```

That's it. The connector is authorized once per machine and the tools load on the next turn; the hooks use whatever token `seaglass auth login` cached. Rotate the CLI token by re-running `seaglass auth login`; no client config change needed.

### Local development install

If you're working from a local clone instead of the GitHub repo:

```bash
/plugin marketplace add /path/to/seaglass
/plugin install seaglass@seaglass-memory
```

An unpublished checkout still holds the `https://api-stg.seaglassai.com` placeholder in `.mcp.json`, so its connector points nowhere. Against a dev API, add the connector by hand instead:

```bash
claude mcp add --transport http seaglass http://localhost:8008/mcp
# or the stdio bridge, which follows SEAGLASS_URL and the cached CLI token:
claude mcp add --transport stdio seaglass -- seaglass bridge
```

### Upgrading from the `seaglass-cli` plugin

The marketplace used to ship a second plugin, `seaglass-cli`, that taught the CLI path on its own. That teaching now lives inside `seaglass`, as its `seaglass-cli` skill, so one install covers both. If you installed it:

```bash
claude plugin uninstall seaglass-cli@seaglass-memory
/plugin install seaglass@seaglass-memory
```

Older installs under the pre-rename names (`seaglass-memory@seaglass-memory-plugin`, `seaglass-memory-cli@seaglass-memory-plugin`) uninstall the same way.

### Uninstall

```bash
claude plugin uninstall seaglass@seaglass-memory
```

## Install in Claude Desktop, claude.ai, and Cowork

### Plugin (recommended on paid plans)

Open **Customize**, then **Plugins**, click **+** under Personal plugins, choose **Add marketplace** and enter the marketplace's GitHub repository (`drummel/seaglass-alpha`), then install `seaglass`. The bundled connector prompts for its browser sign-in as part of the install. Skills load on the web, in the Desktop Chat tab, and in Cowork; command hooks run only where the host runs them (Cowork today), so the chat surfaces use `/recall` and `/checkpoint` instead.

### Remote connector (no plugin)

Add your Seaglass server as a custom connector: **Customize**, **Connectors**, **Add custom connector**, paste `<server>/mcp`, and approve in the browser. The "Add to Claude" button on the Connections page prefills this for you. A connector added once reaches claude.ai, Desktop, Cowork, and mobile. No CLI, no local process. (The old one-click `.mcpb` bundle has been removed; the connector replaces it.)

### Manual JSON config (stdio fallback)

Use this only if you specifically need a local stdio server — for example local development against a dev API, or a host without remote-connector support. `seaglass bridge` is dev tooling, not the primary install path.

Claude Desktop uses a JSON config file to register MCP servers. Open your config file:

- **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

Add the `seaglass` entry under `mcpServers`:

```json
{
  "mcpServers": {
    "seaglass": {
      "command": "seaglass",
      "args": ["bridge"]
    }
  }
}
```

`seaglass bridge` is a local transport adapter (stdio MCP ↔ HTTP MCP) that proxies frames to the Seaglass API using the token cached by `seaglass auth login`. No URL or token lives in this config — change either with `seaglass auth login` (or `export SEAGLASS_URL=…` before launching Claude Desktop) and the server picks them up on next restart. `seaglass mcp` still works as a backward-compatible alias.

Restart Claude Desktop to pick up the change. To uninstall, remove the `seaglass` entry from `mcpServers` and restart.

## Install in ChatGPT / Codex

The same plugin installs on ChatGPT/Codex from its plugin surface. One repo ships both manifests: Codex reads `.codex-plugin/plugin.json`, Claude reads `.claude-plugin/plugin.json`, and both share the `skills/` and `hooks/` directories. Both manifests declare the same remote connector (`.codex-plugin/mcp.json` and `.mcp.json` are kept equal by a test).

> The exact Codex install command, manifest keys, and hook-config validation are docs-grade and should be confirmed against the live [Codex plugin docs](https://developers.openai.com/codex/plugins) and [hooks docs](https://developers.openai.com/codex/hooks) at install time.

1. Add the Seaglass marketplace / plugin in the Codex plugin surface and install the `seaglass` plugin.
2. **Trust the hooks.** Installing a plugin does not trust its executable hooks. Open `/hooks`, review the Seaglass session hooks, and trust them, otherwise they stay skipped.
3. **Authenticate the connector** the first time a memory tool is used: run `codex mcp login seaglass` (or click Authenticate) and approve in the browser. The token is managed by Codex; no token lives in any config file.

Hooks fire on Codex's `SessionStart`, `SessionEnd`, `Stop`, and `PreCompact` — both manifests point at the same `hooks/hooks.json`, which declares all four. A session that dies without its `SessionEnd` hook running is finalized by the server-side TTL sweep as a backstop. Install the CLI (`curl -fsSL https://raw.githubusercontent.com/drummel/seaglass-alpha/main/cli/install.sh | bash`) and authenticate it (`seaglass auth login`) for the hooks and the shell path, exactly as on Claude Code.

### Degraded mode

If the connector is unauthenticated, the skill tells the agent which sign-in to name. If the CLI is missing or unauthenticated, the session hooks degrade to a one-line nudge and never block the session, on every host.

## Verifying the connection

Once installed, ask Claude:

> What do you know about me?

If the connection is working, Claude will read from your Seaglass instance. `/seaglass:status` gives the same answer in one line. If it fails, re-authorize the connector in the host (`/mcp` in Claude Code; Customize, Connectors elsewhere). For the CLI side:

```bash
seaglass auth status   # show where the active token comes from + which URL
seaglass whoami        # round-trip an MCP initialize through the cached token
```

If `seaglass whoami` works but the hooks report the CLI missing, the most common cause is that the GUI client launched before `seaglass` was on PATH — restart the client.

## Automation / CI

For CI and other non-interactive contexts where `seaglass auth login` isn't viable, you can still mint a long-lived token from the admin UI's Connections page and inject it via `SEAGLASS_TOKEN`. The env var still wins over the cached file, so a CI runner exporting it gets the same behavior as an interactive shell that ran `seaglass auth login`. An agent that already has the MCP tools but no CLI token can call `cli_handoff` and redeem the code it returns with `seaglass auth redeem <code>`, no browser needed.

## Tools / commands

The connector and the CLI drive the same backend over the same operations. The connector surfaces them as JSON-RPC tools; the CLI surfaces them as `seaglass` subcommands, taught by the `seaglass-cli` skill. The agent-facing surface is the same set either way:

| MCP tool | CLI command | What |
|---|---|---|
| `start_session` | `seaglass session start` | Start a session: the profile, the preferences and any setup step |
| `search` | `seaglass search` | Read — recall synthesized knowledge |
| `store_memory` | `seaglass memory store` | Write a memory |
| `store_document` | `seaglass document store` | Write a document |
| `update_memory` | `seaglass memory update` | Retract / supersede / reclassify / redact a memory |
| `reconsolidate_memory` | `seaglass reconsolidate` | Diagnose + resolve memory confusion |
| `create_page` | `seaglass page create` | Register a wiki page |
| `edit_page` / `edit_section` | `seaglass page edit` | Author / revise a page (whole or one section) |
| `append_section` | `seaglass page append` | Add a new section to a page |
| `revert_page` | `seaglass page revert` | Roll a page back to an earlier version |
| `get_page_history` | `seaglass page history` | Read a page's edit history |
| `move_page` | `seaglass page move` | Rename / move a page to a new typed slug |
| `send_seaglass_product_feedback` | `seaglass send-product-feedback` | Send feedback about Seaglass itself |

**MCP/agent-only — no CLI command, by design:** the transcript-recall tools
(`transcript_search`, `transcript_read`) and the source-connector tools
(`list_source_connections`, `list_available_documents`, `import_source_document`,
`resync_source_document`). Connecting a source and curating its available
documents happen on the web; the agent imports from that shelf.

### Nested wiki sub-pages

Every operation that accepts a page reference also accepts a **typed
slug** like `projects/seaglass/competitors` or
`projects/seaglass/data-model/schema`. Slugs are lowercase kebab-case;
the first segment is the page type (`people` / `projects` / `topics` are
the seeded suggestions, but each library defines its own)
and is inherited by every descendant — within `projects/seaglass`, every
sub-page is part of that project.

**Parents must already exist.** Creating `projects/seaglass/competitors`
requires `projects/seaglass` to already be a page; Seaglass never
auto-creates ancestors. Reach for a sub-page when a page outgrows
itself: create the parent first, then add the child with
`create_page` (or implicitly via `store_memory` / `store_document`
when their `primary_page` is a slug pointing at the new sub-page).

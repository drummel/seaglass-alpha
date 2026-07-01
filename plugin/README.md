# Seaglass Memory Plugin

Connects Claude to the Seaglass personal memory layer. Once installed, Claude automatically captures and recalls context about people, projects, and topics across conversations.

This marketplace ships **two plugins** that share the same backend — pick one (or both):

| Plugin | Transport | Best for |
|---|---|---|
| `seaglass` | Local `seaglass` stdio shim → API | Default. Works in Claude Code, Claude Desktop, Cowork, OpenClaw — any MCP-capable client. |
| `seaglass-cli` | `seaglass` CLI over `bash` | Token-cheap alternative for shell-capable clients (Claude Code). Same backend, lower per-turn cost. |

Both plugins require the `seaglass` CLI on PATH — the CLI is the single auth boundary.

A third, **experimental** plugin (`plugin/plugins/seaglass-hermes/`) targets the [Hermes](https://github.com/nousresearch/hermes-agent) agent. It is intentionally **not** published to the marketplace — its hook contract is unverified — so `marketplace.json` lists only the two plugins above. See its README before relying on it.

The MCP plugin provides:

- **MCP server connection** — the full agent-facing tool surface: reading (`search`), writing (`store_memory`, `store_document`), flagging (`flag_memory`), reconsolidating (`reconsolidate_memory`), authoring and editing wiki pages (`create_page`, `edit_page`/`edit_section`, `append_section`, `revert_page`, `move_page`, `get_page_history`), and tracing back through past sessions (`transcript_search`, `transcript_read`). See the parity table under [Tools / commands](#tools--commands).
- **Capture skill** — teaches Claude when and how to read/write memories based on conversation signals.
- **Session lifecycle hooks** (Claude Code only) — `SessionStart` injects the user's profile + behavior instructions before the first turn; `SessionEnd` closes the `sessions` row server-side. Non-Code clients ignore the hooks and fall back to the `/recall` / `/checkpoint` skills.

The CLI plugin provides:

- **Capture skill only** — teaches Claude to drive the same backend through the `seaglass` CLI subcommands (see the parity table under [Tools / commands](#tools--commands)).
- **Same session lifecycle hooks** as the MCP plugin (Claude Code only).

## Prerequisites

1. **Install the `seaglass` CLI** (one-time):

   ```bash
   uv tool install ./cli            # or: pipx install ./cli
   ```

2. **Authenticate**:

   ```bash
   seaglass auth login
   ```

   This opens the Seaglass admin UI in your browser, asks you to approve the connection, and stores a bearer token at `~/.config/seaglass/token`. Every MCP-capable client below picks it up from there — no env vars, no token copy-pasting.

   For a non-default deployment, set `SEAGLASS_URL` before logging in:

   ```bash
   export SEAGLASS_URL="https://your-seaglass-instance.example.com"
   seaglass auth login
   ```

## Install in Claude Code — MCP plugin (default)

```bash
# 1. Add the marketplace
/plugin marketplace add drummel/seaglass-alpha

# 2. Install the MCP plugin (enables skill + MCP server automatically)
/plugin install seaglass@seaglass-memory
```

That's it. The MCP server connects on the next session start, using whatever token `seaglass auth login` cached. Rotate tokens by re-running `seaglass auth login`; no client config change needed.

## Install in Claude Code — CLI plugin (alternative)

```bash
# 1. Add the marketplace + install the CLI skill
/plugin marketplace add drummel/seaglass-alpha
/plugin install seaglass-cli@seaglass-memory
```

The skill loads `seaglass` commands instead of MCP tools — same backend, no
JSON schema injected into the system prompt. See `cli/README.md` for the
full command surface.

### Local development install

If you're working from a local clone instead of the GitHub repo:

```bash
/plugin marketplace add /path/to/seaglass
# then install whichever plugin you want:
/plugin install seaglass@seaglass-memory       # MCP
/plugin install seaglass-cli@seaglass-memory   # CLI
```

### Upgrading from the old plugin names

The marketplace and plugins were renamed. If you installed before the rename:

```bash
claude plugin uninstall seaglass-memory@seaglass-memory-plugin
claude plugin uninstall seaglass-memory-cli@seaglass-memory-plugin
# then reinstall under the new names (see above)
```

### Uninstall

```bash
claude plugin uninstall seaglass@seaglass-memory
claude plugin uninstall seaglass-cli@seaglass-memory
```

## Install in Claude Desktop

### One-click bundle (.mcpb)

The fastest path: download **`seaglass.mcpb`** from your Seaglass server at
`<server>/v1/connect/seaglass.mcpb` (the "Add to Claude Desktop" button on the
Connections page) and double-click it — Claude Desktop installs the connector,
which runs `seaglass bridge`. Requires the `seaglass` CLI on PATH and a one-time
`seaglass auth login`.

### Manual JSON config

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

Restart Claude Desktop to pick up the change.

### Uninstall

Remove the `seaglass` entry from `mcpServers` in the config file and restart Claude Desktop.

## Verifying the connection

Once installed, ask Claude:

> What do you know about me?

If the connection is working, Claude will read from your Seaglass instance. If it fails:

```bash
seaglass auth status   # show where the active token comes from + which URL
seaglass whoami        # round-trip an MCP initialize through the cached token
```

If `seaglass whoami` works but Claude Desktop / Code can't reach Seaglass, the most common cause is that the GUI client launched before `seaglass` was on PATH — restart the client.

## Automation / CI

For CI and other non-interactive contexts where `seaglass auth login` isn't viable, you can still mint a long-lived token from the admin UI's Connections page and inject it via `SEAGLASS_TOKEN`. The env var still wins over the cached file, so a CI runner exporting it gets the same behavior as an interactive shell that ran `seaglass auth login`.

## Tools / commands

Both plugins drive the same backend over the same operations. The MCP plugin
surfaces them as JSON-RPC tools; the CLI plugin surfaces them as `seaglass`
subcommands. The agent-facing surface is the same set either way:

| MCP tool | CLI command | What |
|---|---|---|
| `search` | `seaglass search` | Read — recall synthesized knowledge |
| `store_memory` | `seaglass memory store` | Write a memory |
| `store_document` | `seaglass document store` | Write a document |
| `flag_memory` | `seaglass flag` | Flag / redact a memory |
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

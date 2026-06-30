# `seaglass` — Seaglass CLI

Thin command-line client for the Seaglass personal memory layer. Talks to the
same `/mcp` JSON-RPC endpoint that Claude Code, Claude Desktop, Cowork, and
OpenClaw use, so the auth / session / tool surfaces are identical to the MCP
plugin.

This exists for two reasons:

1. **Developer velocity.** Capture, replay, and audit memories without
   spinning up an MCP client.
2. **Token-cheap agent integration.** Pair with the
   [`seaglass-cli`](../plugin/plugins/seaglass-cli) plugin to teach Claude
   Code (or any shell-capable agent) to drive Seaglass over `bash` instead
   of MCP. See `docs/cli-vs-mcp.md` for the cost story.

The CLI uses only the Python 3.11+ standard library — no third-party
dependencies, ~150 ms cold start.

## Install

```bash
# Recommended (uv): installs to ~/.local/bin/seaglass
uv tool install ./cli

# Or pipx
pipx install ./cli

# Or pip into a venv
pip install ./cli
```

After install, `seaglass --version` should print `seaglass 0.3.0`.

> **Upgrading from `sg`?** The binary was renamed in [ADR-0001](../docs/adr/0001-cli-binary-name-seaglass.md).
> Run `uv tool uninstall seaglass-cli && uv tool install ./cli` (or the pipx
> equivalent) to drop the old `sg` shim and pick up `seaglass`.

## Configure

```bash
# Browser-link auth: opens the admin UI, you click Approve, token is cached.
# Pass --url to log in to a specific server and pin it for later commands.
seaglass auth login --url https://your-seaglass.example.com
```

The token is written to `~/.config/seaglass/token` and the URL pin to
`~/.config/seaglass/config.json`; both are picked up automatically by every
subsequent `seaglass` invocation. `seaglass auth status` shows the active URL
and where it came from; `seaglass whoami` confirms the token works.

The server URL resolves through three layers, most-specific first:

1. `SEAGLASS_URL` (env) — for CI / automation / one-off overrides.
2. `~/.config/seaglass/config.json` — the pin from `seaglass auth login --url`.
3. the baked default (the hosted server in a published build; `http://localhost:8008` in-repo).

For CI / non-interactive contexts you can still mint a token from the admin
UI's Connections page and inject it via `SEAGLASS_TOKEN`; the env var wins
over the cached file (same precedence as `SEAGLASS_URL`).

## Commands

```text
# auth & diagnostics
seaglass auth login   [--url URL] [--no-browser] [--client-name NAME] [--json]
seaglass auth logout  [--json]
seaglass auth status  [--json]
seaglass whoami [--json]
seaglass tools  [--json]
seaglass update                # self-update to the latest release
seaglass bridge                # stdio MCP transport bridge for MCP clients (alias: `mcp`)
seaglass install <client>      # write per-client connector config + guidance

# read
seaglass search <query> [--type T] [--limit N] [--include-private] [--json]

# capture
seaglass memory store --page NAME --content TEXT [--type T] [--sensitivity S]
                      [--link-people NAME ...] [--source-kind K] [--json]
seaglass document store --title T [--file PATH | --content TEXT | --stdin] [--page E]
                        [--source-kind K] [--sensitivity S] [--json]
seaglass annotate <page> --content TEXT [--sensitivity S] [--json]

# curate
seaglass flag <target_id> --action {flag_incorrect|flag_outdated|flag_sensitive|flag_private|redact}
                          [--reason R] [--json]
seaglass reconsolidate <query> [--kind {split|merge|reassign} --details-json '{...}'
                                | --resolution-json '{...}'] [--json]

# wiki pages
seaglass page create [--slug S | --parent P --title T | --type T --title T] [--json]
seaglass page edit <page> [--section H] [--content TEXT | --content-file F | --stdin] [--json]
seaglass page append <page> --section H [--content TEXT | --stdin] [--json]
seaglass page history <page> [--limit N] [--json]
seaglass page revert <page> --to-version N [--json]
seaglass page move <page> <to> [--title T] [--edit-summary S] [--json]

# profile (read-only from the CLI; writes live in the admin web UI)
seaglass me [--json]
seaglass profile [show] [--render] [--json]
seaglass profile set <key> <value> [--json]
seaglass profile instructions [--print | --set TEXT | --stdin] [--json]
seaglass profile agents [--json]
seaglass profile agent <agent> [set <key> <value> | inherit <key> | instructions] [--json]

# session lifecycle
seaglass session end [--client-session-id ID] [--json]
seaglass session upload-transcript [--file F] [--client-session-id ID] [--json]
seaglass session finalize-transcript [--reason R] [--json]
seaglass session transcript-config [--json]
seaglass session briefing [--json]

# Seaglass itself
seaglass send-product-feedback --kind {bug|feature} --body TEXT [--json]
```

Every subcommand has its own `--help` describing flags + examples.

## Examples

```bash
# Read
seaglass search "what do I know about Sarah?"
seaglass search "Sarah Chen" --type people --json | jq '.page'

# Write a memory (interactive content)
seaglass memory store --page "Sarah Chen" --type people \
  --content "Sarah is leading the Q3 launch."

# Capture a meeting note from a file
seaglass document store --file ./standup-2026-04-30.md \
  --page "Q3 launch" --type projects \
  --link-people "Sarah Chen" --link-people "Tom"

# Write into a nested wiki sub-page via its full typed slug. The parent
# ("projects/seaglass") must already exist — Seaglass never auto-creates
# ancestors, so register the parent first if it doesn't.
seaglass memory store --page "projects/seaglass/competitors" \
  --content "Memex shipped a similar 'auto-organize pages' release."

# Flag something the user just corrected
seaglass flag memory_01HXABC... --action flag_incorrect --reason "wrong manager"

# Diagnose two-people-one-name confusion
seaglass reconsolidate "I think there are two Steves"

# Pipe stdin
echo "Tom missed three deadlines this quarter." \
  | seaglass memory store --page Tom --type people --stdin --sensitivity sensitive
```

For a longer cookbook organized by workflow — sensitivity handling,
documents, scripting patterns with `jq`, exit-code branching — see
[`docs/cli-cookbook.md`](../docs/cli-cookbook.md).

## Output

Default output is short and human-readable. `--json` returns the raw service
response (the same shape the MCP tool would return). Errors go to stderr.

## Exit codes

| code | meaning |
|---|---|
| 0 | success |
| 1 | generic failure |
| 2 | argparse usage error |
| 3 | not found (`search` returned `no_match`) |
| 4 | resolution required (ambiguous page reference) |
| 5 | auth failure (token missing, revoked, or invalid) |

## How it works

`seaglass` POSTs JSON-RPC payloads to `${SEAGLASS_URL}/mcp` with the bearer
token cached by `seaglass auth login`. Most subcommands wrap a single MCP tool
call — a few representative ones:

| subcommand | MCP tool |
|---|---|
| `seaglass search` | `search` |
| `seaglass memory store` | `store_memory` |
| `seaglass document store` | `store_document` |
| `seaglass flag` | `flag_memory` |
| `seaglass reconsolidate` | `reconsolidate_memory` |
| `seaglass page create` | `create_page` |
| `seaglass page edit` | `edit_page` / `edit_section` |
| `seaglass page move` | `move_page` |
| `seaglass send-product-feedback` | `send_seaglass_product_feedback` |

The exceptions are the surfaces that aren't MCP tools at all: `auth`,
`install`, `update`, and the `session` / transcript commands speak to REST
endpoints, and `me` / `profile` read the `seaglass://profile` resource (profile
*writes* live only in the admin web UI, ADR-0006). `tests/test_parity.py`
guards the CLI↔MCP tool mapping against drift.

Server-side: same auth, same session bookkeeping, same service-layer code
paths as the MCP plugin. The CLI is purely a client-side surface.

The Mcp-Session-Id header is cached in `~/.cache/seaglass/session` so
captures issued from the same shell get coherent provenance.

`seaglass bridge` (aliased as `seaglass mcp` for backward compatibility) is a
stdio MCP transport bridge — JSON-RPC frames on stdin, responses on stdout —
that points at the same `/mcp` endpoint with the same cached token. It's what
`.mcp.json` and Claude Desktop's `claude_desktop_config.json` invoke, so plugins
inherit `seaglass auth login`'s token without ever needing the env variable.
See `plugin/README.md` for the client configuration.

## Development

```bash
cd cli
uv sync                                              # installs pytest + ruff
uv run pytest                                        # runs the suite (sub-second)
uv run pytest --cov=seaglass --cov-report=term-missing  # ≥95% line/branch
uv run ruff check .
uv run ruff format --check .
```

CI runs the same gate (≥95% line/branch coverage) on any change under `cli/`.

The test suite mocks `urllib.request.urlopen` at the boundary, so it
exercises real argparse parsing, real JSON-RPC framing, and real output
formatters. There's no live API dependency. Tests live in `tests/`:

| file | covers |
|---|---|
| `tests/conftest.py` | shared `fake_urlopen`, env, and session-file fixtures |
| `tests/test_client.py` | config, RPC framing, error → exit-code mapping, session-id cache |
| `tests/test_formatters.py` | every `mode` of the search response, every write-path result shape |
| `tests/test_cli.py` | each subcommand end-to-end via `main([...])`, plus `--help`, `--version`, KeyboardInterrupt, and `python -m seaglass` |
| `tests/test_auth.py` | browser-link login/logout/status, token-file precedence, polling loop |
| `tests/test_mcp_shim.py` | `seaglass bridge` stdio transport: frame round-trip, session-id propagation, auth-failure framing |
| `tests/test_parity.py` | CLI↔MCP tool coverage guard (drift trips the build) |
| `tests/test_docs_lint.py` | scans `README.md` + `cli.py` for stale ID prefixes and outdated command-count claims |

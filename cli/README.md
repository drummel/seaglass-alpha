# `seaglass` — Seaglass CLI

Thin command-line client for the Seaglass memory layer, written in Go. It talks
to the same `/mcp` JSON-RPC endpoint that Claude Code, Claude Desktop, Cowork,
and OpenClaw use, so the auth / session / tool surfaces are identical to the MCP
plugin.

This exists for two reasons:

1. **Developer velocity.** Capture, replay, and audit memories without spinning
   up an MCP client.
2. **Token-cheap agent integration.** Pair with the
   [`seaglass-cli`](../plugin/plugins/seaglass-cli) plugin to teach Claude Code
   (or any shell-capable agent) to drive Seaglass over `bash` instead of MCP.

The CLI is a single static binary (CGO disabled), so it has no runtime
dependency, a sub-10ms cold start, and one Linux build runs on both glibc and
musl (Alpine).

## Install

```bash
# One-line installer (detects OS/arch, verifies checksum, installs to ~/.local/bin):
curl -fsSL https://raw.githubusercontent.com/drummel/seaglass-alpha/main/cli/install.sh | bash

# Or download a binary from the GitHub Releases page and put it on your PATH.
# Or, once the tap is live: brew install seaglass-ai/tap/seaglass
```

Pin a version with `SEAGLASS_VERSION=1.2.3`, or an install dir with
`SEAGLASS_INSTALL_DIR=…`. After install, `seaglass --version` prints the version.

## Configure

```bash
# Browser-link auth: opens the admin UI, you click Approve, token is cached.
# Pass --url to log in to a specific server and pin it for later commands.
seaglass auth login --url https://your-seaglass.example.com
```

The token is written to `~/.config/seaglass/token` and the URL pin to
`~/.config/seaglass/config.json`. The server URL resolves through three layers,
most-specific first: `SEAGLASS_URL` (env) > the `auth login --url` pin > the
baked default (the hosted server in a published build; `http://localhost:8008`
in-repo). For CI, inject a token via `SEAGLASS_TOKEN`.

Run `seaglass --help`, or `seaglass <command> --help`, for the full surface:
`auth`, `search`, `memory`, `document`, `annotate`, `page`, `profile`,
`session`, `reconsolidate`, `install`, `bridge`, `whoami`, `tools`, `onboard`,
`update`, and `send-product-feedback`.

## Exit codes

| code | meaning |
|---|---|
| 0 | success |
| 1 | generic failure |
| 2 | usage error |
| 3 | not found (`search` returned `no_match`) |
| 4 | resolution required (ambiguous page reference) |
| 5 | auth failure (token missing, revoked, or invalid) |

## How it works

`seaglass` POSTs JSON-RPC payloads to `${SEAGLASS_URL}/mcp` with the cached
bearer token. Most subcommands wrap a single MCP tool call; `auth`, `install`,
`update`, and the `session` / transcript commands speak to REST endpoints, and
`me` / `profile` read the `seaglass://profile` resource (profile *writes* live
only in the admin web UI).

`seaglass bridge` (aliased `seaglass mcp`) is a stdio MCP transport bridge —
JSON-RPC frames on stdin, responses on stdout — pointed at the same `/mcp`
endpoint with the same cached token, so `.mcp.json` and Claude Desktop configs
inherit `seaglass auth login`'s token without an env var.

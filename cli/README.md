# `seaglass` — Seaglass CLI

Thin command-line client for the Seaglass memory layer, written in Go. It talks
to the same `/mcp` JSON-RPC endpoint that Claude Code, Claude Desktop, Cowork,
and OpenClaw use, so the auth / session / tool surfaces are identical to the MCP
plugin.

This exists for two reasons:

1. **Developer velocity.** Capture, replay, and audit memories without spinning
   up an MCP client.
2. **Token-cheap agent integration.** The [`seaglass`](../plugin/plugins/seaglass)
   plugin's skill carries a CLI reference that teaches Claude Code (or any
   shell-capable agent) to drive Seaglass over `bash` instead of MCP, and its
   session hooks shell out to this binary.

The CLI is a single static binary (CGO disabled), so it has no runtime
dependency, a sub-10ms cold start, and one Linux build runs on both glibc and
musl (Alpine).

## Install

```bash
# One-line installer (detects OS/arch, verifies checksum, installs to ~/.local/bin):
curl -fsSL https://raw.githubusercontent.com/drummel/seaglass-alpha/main/cli/install.sh | bash

# Or download a binary from the GitHub Releases page and put it on your PATH:
#   https://github.com/drummel/seaglass-alpha/releases
```

Pin a version with `SEAGLASS_VERSION=1.2.3`, or an install dir with
`SEAGLASS_INSTALL_DIR=…`. After install, `seaglass --version` prints the version.

## Configure

```bash
# Browser-link auth: opens the admin UI, you click Approve, token is cached.
# Pass --url to log in to a specific server and pin it for later commands.
seaglass auth login --url https://your-seaglass.example.com

# No browser (an agent with the Seaglass MCP tools): the cli_handoff tool
# returns a single-use code.
seaglass auth redeem <code>
```

The token is written to `~/.config/seaglass/token` and the URL pin to
`~/.config/seaglass/config.json`. The server URL resolves through three layers,
most-specific first: `SEAGLASS_URL` (env) > the `auth login --url` pin > the
baked default (the hosted server in a published build; `http://localhost:8008`
in-repo). For CI, inject a token via `SEAGLASS_TOKEN`; while it is set it
overrides the saved token, and `auth login` / `auth redeem` say so.

Run `seaglass --help`, or `seaglass <cmd> --help`, for the full surface
(each command's help marks its required flags and lists every flag's allowed
values and default):
`auth`, `search`, `memory`, `document`, `annotate`, `page`, `profile`,
`session`, `reconsolidate`, `install`, `bridge`, `whoami`, `tools`, `update`,
`me`, and `send-product-feedback`. `seaglass session start` is the first call
of a session: it calls the server's `start_session` tool and prints the profile
and any setup step (the plugin's `SessionStart` hook runs it when the CLI is
signed in).

## Exit codes

| code | meaning | what to do |
|---|---|---|
| 0 | success | continue |
| 1 | generic failure (a changed command will not fix it) | read stderr; investigate |
| 2 | usage error: the command line is wrong (a flag missing, unknown, or with a bad value; a `--type` to add; a heading the page lacks; a library you cannot use), and stderr names the fix | fix the command as stderr says (`seaglass <cmd> --help`), rerun once |
| 3 | not found (`search` returned `no_match`, or a named page or resource does not exist) | tell the user honestly |
| 4 | resolution required (ambiguous page reference) | ask the user the clarification question |
| 5 | auth failure (token missing, revoked, or invalid) | With the Seaglass MCP tools connected: call the cli_handoff tool, then run `seaglass auth redeem <code>` with the code it returns. Without them: run `seaglass auth login`, which opens a browser for the user to approve. Then rerun the failed command once. A set `SEAGLASS_TOKEN` overrides the saved token. |

## How it works

`seaglass` POSTs JSON-RPC payloads to `${SEAGLASS_URL}/mcp` with the cached
bearer token. Most subcommands wrap a single MCP tool call; `auth`, `install`,
`update`, and the `session` / transcript commands speak to REST endpoints (all
but `session start`, which calls the `start_session` tool), and
`me` / `profile` read the `seaglass://profile` resource (profile *writes* live
only in the admin web UI).

`seaglass bridge` (aliased `seaglass mcp`) is a stdio MCP transport bridge —
JSON-RPC frames on stdin, responses on stdout — pointed at the same `/mcp`
endpoint with the same cached token, so `.mcp.json` and Claude Desktop configs
inherit `seaglass auth login`'s token without an env var.

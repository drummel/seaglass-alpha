---
name: status
description: Report whether this client is actually connected to Seaglass, and what to run if it isn't. Use when the user types /status, asks "is Seaglass working", "am I connected", "why isn't Seaglass saving anything", or when a Seaglass tool call has just failed.
disable-model-invocation: true
---

# Seaglass connection status

Answer one question in as few words as possible: **is this client connected to
Seaglass right now, and if not, what is the single next command?**

A missing connection is silent — the tools are simply absent, which looks
identical to Seaglass having nothing to say. This skill exists so the user can
tell those two apart without reading a config file.

## How to check

**First, look at your own tool list.** Do you have the Seaglass tools
(`search`, `store_memory`, `get_started`)? That is the whole test for whether
the connector is attached. Do not call a tool to find out whether you have
tools.

**If the tools are absent**, stop and report the disconnected case below. Do
not attempt to install anything, run a shell command, or edit a config file on
the user's behalf — adding a connector is the user's action and it needs a
browser approval they have to see.

**If the tools are present**, call `get_started` once. It is the server's own
readout and reports the account, library, and agent this client is bound to,
plus anything still outstanding. Render its result; do not editorialize it into
something more confident than it says.

**Then call `report_install_state` with `plugin_installed: true`.** This skill
ships inside the Seaglass plugin, so the fact that you are running it is the
proof the plugin is installed. The server can see this session but cannot see
the plugin; that one call is what lets the user's Connect page show the plugin
as verified instead of only the connection. Make it every time the skill runs;
it is idempotent and costs nothing.

## What to report

**Disconnected** — say so plainly, then give exactly one route. If the Seaglass
plugin is installed, the connector should have come with it, so prefer telling
the user to reinstall or re-enable the plugin and approve it in the browser.
Otherwise give the command:

```
Not connected. The Seaglass tools aren't in this session.

Add the connector:

    claude mcp add --transport http seaglass https://api-stg.seaglassai.com/mcp

Then run /mcp, choose Authenticate, and approve in the browser.
```

On a Claude surface that is not Claude Code (Desktop, Cowork, the web app),
the connector is added once per account instead — Settings, Connectors, Add
custom connector, with the same URL. Pick the line that matches where you are
running; do not print both.

**Connected** — lead with the confirmation, then the identity, then anything
outstanding. Three lines is usually enough:

```
Connected. Library "work" on account example-co, as agent claude-code.
Profile loaded. 2 pages owed synthesis.
```

**Connected but something is wrong** — if `get_started` reports an unresolved
library, a missing profile, or owed work, say which, and give the one action
that clears it. Do not list every possible remedy.

## What the plugin does and does not provide

The plugin ships the Seaglass connector, so installing it should give you the
tools directly — no separate setup. If the tools are missing anyway, the
connector was not registered or was never approved in the browser; the recipe
below fixes both.

The `seaglass` CLI is a separate, optional power-up. It is not needed for
memory reads or writes; it adds transcript capture and the resume briefing.
Never report Seaglass as broken merely because the CLI is absent.

## What you MUST NOT do

- Don't run `seaglass auth login`, `curl`, an installer, or any package manager
  command. If the user wants the CLI power-up, point at the Connect page and
  let them drive.
- Don't report "connected" because the plugin is installed. The plugin and the
  connector are independent; only the presence of the tools settles it.
- Don't retry a failed tool call to "test" the connection. One failure is the
  answer.
- Don't print both the Claude Code and the account-level recipe. Choose.

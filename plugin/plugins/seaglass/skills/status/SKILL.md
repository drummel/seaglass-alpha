---
name: status
description: Report whether this client is actually connected to Seaglass, and what to run if it isn't. Use when the user types /status, asks "is Seaglass working", "am I connected", or "why isn't Seaglass saving anything".
disable-model-invocation: true
---

# Seaglass connection status

Answer one question in as few words as possible: **is this client connected to
Seaglass right now, and if not, what is the single next step?**

A missing connection is silent: the tools are simply absent, which looks
identical to Seaglass having nothing to say. This skill exists so the user can
tell those two apart without reading a config file.

## How to check

**First, look at your own tool list.** Do you have the Seaglass tools
(`search`, `store_memory`, `start_session`)? That is the whole test for whether
the connector is attached. Do not call a tool to find out whether you have
tools.

**If the tools are absent**, stop and report the disconnected case below. Adding
a connector is the user's action, and it needs a browser approval they have to
see.

**If the tools are present**, read the setup state from this session's
`start_session` result, calling it now if the session has not made it yet. It
reports whether setup is complete and, if not, the next setup step. Render what it says; do not
editorialize it into something more confident than it says.

**Then call `report_install_state` with `plugin_installed: true`.** This skill
ships inside the Seaglass plugin, so the fact that you are running it is the
proof the plugin is installed. The server can see this session but cannot see
the plugin; that one call is what lets the user's Connect page show the plugin
as verified instead of only the connection. Make it every time the skill runs;
it is idempotent and costs nothing.

## What to report

**Disconnected**: say so plainly, then give the one step for this client from
the `seaglass-memory` skill's "If the Seaglass tools aren't available" section,
which is the one home of the reconnect recipe (load that skill if it is not in
context):

```
Not connected. The Seaglass tools aren't in this session.

<the one reconnect step for this client, from that section>
```

**Connected**: lead with the confirmation, then the setup state. One or two
lines is usually enough:

```
Connected to Seaglass. Setup is complete.
```

**Connected, setup unfinished**: name the one step `start_session` returned, and
do it the way its result says to. Do not list every possible remedy.

## What the plugin does and does not provide

The plugin ships the Seaglass connector, so installing it should give you the
tools directly, with no separate setup. If the tools are missing anyway, the
connector was not registered or was never approved in the browser; the
reconnect recipe fixes both.

The `seaglass` CLI is a separate, optional power-up. It is not needed for
memory reads or writes; it adds transcript capture and the resume briefing.
Never report Seaglass as broken merely because the CLI is absent. If the CLI is
installed but not signed in and the user wants it, offer once to run
`seaglass auth login` for them (it opens a browser and waits for their
approval), and run it on yes.

## What you MUST NOT do

- Don't run an installer, `curl`, or a package manager command from this skill.
- Don't report "connected" because the plugin is installed. The plugin and the
  connector are independent; only the presence of the tools settles it.
- Don't retry a failed tool call to "test" the connection. One failure is the
  answer.

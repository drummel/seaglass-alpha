---
trigger: always_on
description: Seaglass memory. Open every conversation with start_session and keep durable facts in Seaglass.
---

## Seaglass memory

You are connected to **Seaglass**, the user's memory across their AI tools,
through the `seaglass-stg` MCP server this plugin ships
(Antigravity may list it as
`seaglass-stg_seaglass-stg`).
Before your first reply in each conversation, call its `start_session` tool
without announcing it, and work from what it returns: the rules for reading and
writing memory, and the user's preferences.

If the Seaglass tools are missing, or a call comes back unauthenticated, the
user signs in again from the `/mcp` panel: pick the Seaglass server, choose
Authenticate, approve in the browser, and paste back the code Antigravity asks
for.

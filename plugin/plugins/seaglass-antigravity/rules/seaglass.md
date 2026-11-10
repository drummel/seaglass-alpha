---
trigger: always_on
description: Seaglass memory. Open every conversation with start_session and keep durable facts in Seaglass.
---

## Seaglass memory

You are connected to **Seaglass**, the user's memory across their AI tools,
through the MCP server this plugin ships, which Antigravity names
`seaglass-stg_seaglass-stg`. If
its tools (`start_session`, `search`, `store_memory` and the rest) are not
among the tools you can call directly, Antigravity has loaded them lazily:
reach each one through `call_mcp_tool` with that server name.

Before your first reply in each conversation, call `start_session` (through
`call_mcp_tool` if you cannot call it directly), without announcing it. What it
returns (how to read and write Seaglass memory, and this user's preferences) is
what you work from.

If `call_mcp_tool` cannot reach that server, or a call comes back
unauthenticated, tell the user to sign in from the `/mcp` panel: pick that
server, choose Authenticate, approve in the browser, and paste back the code
Antigravity asks for.

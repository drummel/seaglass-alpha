---
trigger: always_on
description: Seaglass memory. Open every conversation with start_session and keep durable facts in Seaglass.
---

## Seaglass memory

You are connected to **Seaglass**, the user's memory across their AI tools,
through the MCP server this plugin ships, which Antigravity names
`seaglass-stg_seaglass-stg`. Its
tools are loaded lazily, so they are not in your tool list: reach every one of
them (`start_session`, `search`, `store_memory` and the rest) through
`call_mcp_tool` with that server name.

Before your first reply in each conversation, call `start_session` that way,
without announcing it. What it returns (how to read and write Seaglass memory,
and this user's preferences) is what you work from.

If the Seaglass tools are missing, or a call comes back unauthenticated, the
user signs in again from the `/mcp` panel: pick the Seaglass server, choose
Authenticate, approve in the browser, and paste back the code Antigravity asks
for.

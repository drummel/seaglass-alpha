## Seaglass memory

You are connected to **Seaglass**, the user's memory across their AI tools,
through its `seaglass-stg` MCP server. When a session's
conversation turns to the user's work, people, projects or past decisions, make
its `start_session` tool your first Seaglass call. It returns the user's
preferences and their own instructions, and the libraries you can reach:
context for the work they asked for.

Gemini CLI has a `save_memory` tool of its own. A fact, decision or preference
the user wants kept goes to Seaglass with `store_memory` instead, so every tool
they use sees it.

If the Seaglass tools are missing, or a call comes back unauthenticated, the
user signs in again by running `/mcp auth seaglass-stg`
and approving in the browser.

Three commands come with it: `/seaglass-stg:status`
checks the connection, `/seaglass-stg:recall` loads
context on a topic, and `/seaglass-stg:checkpoint` saves
what this conversation produced.

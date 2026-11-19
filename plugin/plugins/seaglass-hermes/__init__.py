"""Seaglass for Hermes.

A general Hermes plugin. Hermes reaches Seaglass through the MCP connector, which
the operator adds with ``hermes mcp add`` (a plugin cannot declare an MCP server),
so the connector's ``start_session`` tool is what opens the Seaglass session: it
returns the profile, the preferences, the core rules, what this agent's other
recent chats captured and any setup step, on the same session the agent's writes
land on. The plugin adds one thing:

* ``seaglass.orientation`` system-prompt section: a short, fixed note that Seaglass
  is connected and that ``start_session`` is the first call. It calls nothing, so
  the re-render Hermes does after a context compaction costs nothing.

Nothing here raises into Hermes, and nothing here needs the ``seaglass`` CLI.
"""

from __future__ import annotations

from typing import Any

SECTION_ID = "seaglass.orientation"

# Filled per distribution channel at publish; an unpublished checkout keeps the braces.
API_URL = "https://api-stg.seaglassai.com"


def _connect_hint() -> str:
    if "{{" in API_URL:
        add = "`hermes mcp add` with `--auth oauth`"
    else:
        add = f"`hermes mcp add seaglass --url {API_URL}/mcp --auth oauth`"
    return (
        f"tell the user to add it with {add}, or, if `hermes mcp list` already shows a "
        "Seaglass server, to sign it in again with `hermes mcp login <its name>`."
    )


def orientation() -> str:
    return (
        "Seaglass memory is connected to this Hermes through its MCP tools. At the "
        "start of a conversation that touches the user's work, people, projects or "
        "past decisions, call the Seaglass `start_session` tool before any other "
        "Seaglass call, and again if its result is no longer in context (after a "
        "compaction): it returns who the user is, their preferences and their own "
        "instructions, and any setup step. Then do what the user's message calls "
        "for, with what it returns as context for that work.\n\n"
        f"If no Seaglass tools are available, Seaglass is not connected: {_connect_hint()}"
    )


def register(ctx: Any) -> None:
    ctx.register_system_prompt_section(SECTION_ID, orientation())

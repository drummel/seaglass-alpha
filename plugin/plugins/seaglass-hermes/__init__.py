"""Seaglass for Hermes.

A general Hermes plugin. Hermes reaches Seaglass through the MCP connector, which
the operator adds with ``hermes mcp add`` (a plugin cannot declare an MCP server),
so the connector's ``start_session`` tool is what opens the Seaglass session: it
returns the profile, the preferences, the core rules and any setup step, on the
same session the agent's writes land on. The plugin adds two things:

* ``seaglass.orientation`` system-prompt section: a short, fixed note that Seaglass
  is connected and that ``start_session`` is the first call. It calls nothing, so
  the re-render Hermes does after a context compaction costs nothing.
* ``pre_llm_call`` on a conversation's first turn: the resume briefing from a
  signed-in ``seaglass`` CLI (``seaglass session briefing``), appended to that
  turn's user message. Skipped for subagents, whose first turn is a delegated task.

Nothing here raises into Hermes; without a signed-in CLI the first turn adds nothing.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from typing import Any

logger = logging.getLogger(__name__)

SECTION_ID = "seaglass.orientation"
CLI_TIMEOUT_SECONDS = 10

# Filled per distribution channel at publish; an unpublished checkout keeps the braces.
API_URL = "https://api-stg.seaglassai.com"

# The CLI reads these to pin a call to a chat. The briefing is per agent, not per
# chat, and a Hermes started from a Claude Code shell would otherwise inherit the
# Claude session's pin.
_INHERITED_SESSION_PINS = ("SEAGLASS_CLIENT_SESSION_ID", "CLAUDE_SESSION_ID")


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
        "Seaglass memory is connected to this Hermes through its MCP tools. Call the "
        "Seaglass `start_session` tool before anything else in this conversation, and "
        "again if its result is no longer in context (after a compaction), without "
        "announcing it: it returns who the user is, their preferences and custom "
        "instructions, the rules for using Seaglass, and any setup step. Take it in "
        "quietly, then do what the user's message calls for.\n\n"
        f"If no Seaglass tools are available, Seaglass is not connected: {_connect_hint()}"
    )


def _run_cli(args: list[str]) -> subprocess.CompletedProcess[str] | None:
    """Run ``seaglass <args>``; None when the CLI is missing, slow, or fails to start."""
    binary = shutil.which("seaglass")
    if binary is None:
        return None
    env = {k: v for k, v in os.environ.items() if k not in _INHERITED_SESSION_PINS}
    try:
        return subprocess.run(  # noqa: S603
            [binary, *args],
            capture_output=True,
            text=True,
            env=env,
            timeout=CLI_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.debug("seaglass %s failed: %s", " ".join(args), exc)
        return None


def first_turn_briefing(
    is_first_turn: bool = False,
    platform: str = "",
    parent_session_id: str = "",
    **_: Any,
) -> dict[str, str] | None:
    """``pre_llm_call``: on a conversation's first turn, append the resume briefing."""
    if not is_first_turn or parent_session_id or platform == "subagent":
        return None
    status = _run_cli(["auth", "status"])
    if status is None or status.returncode != 0:
        return None
    briefing = _run_cli(["session", "briefing"])
    if briefing is None or briefing.returncode != 0 or not briefing.stdout.strip():
        return None
    return {"context": briefing.stdout.strip()}


def register(ctx: Any) -> None:
    ctx.register_system_prompt_section(SECTION_ID, orientation())
    ctx.register_hook("pre_llm_call", first_turn_briefing)

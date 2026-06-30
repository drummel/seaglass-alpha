"""`seaglass install <client>` — write per-client connector config + a managed
guidance block, idempotently (ADR-0028 P1, ADR-0030).

Two file shapes:
  * Comment-bearing files (markdown AGENTS.md / .cursor rules, TOML config.toml)
    get a sentinel-delimited managed block via :mod:`seaglass.managed_block`.
  * JSON (.cursor/mcp.json) is merged structurally — set ``mcpServers.seaglass``,
    preserve every other server.

All functions take explicit paths so they're trivially testable; the CLI command
resolves the conventional locations.
"""

from __future__ import annotations

import json
from pathlib import Path

from seaglass import managed_block as mb

# The canonical capture/recall guidance compiled into AGENTS.md / .cursor rules.
# Kept short so it fits comfortably alongside the user's own instructions; the
# full house voice ships in the SKILL.md / system-guidance prompt.
MANAGED_GUIDANCE = """\
## Seaglass memory

You are connected to **Seaglass**, a persistent memory layer that syncs context
across the user's AI tools. Use it so work in one tool shows up in the others.

- **Read before assuming.** When the user names a person, project, topic, or
  past decision, search Seaglass first (`search` tool, or `seaglass search`).
- **Capture durable facts.** Decisions, preferences, corrections, and stable
  facts about people/projects are worth saving (`store_memory` / `seaglass
  memory store`). Skip small talk and transient task state.
- **Respect sensitivity.** Content wrapped in `<private>...</private>` is stored
  private; never echo private content into another tool's context.
- Pass **names**, not IDs, for page references; only pass an ID once resolved.
"""


def _default_base_url() -> str:
    """The base URL written into a connector recipe when none is passed explicitly.

    Delegates to the CLI's layered resolver (SEAGLASS_URL env > config.json pin >
    baked default) so `seaglass install` targets the same host the rest of the CLI
    talks to — a `seaglass auth login --url` pin reaches the generated config.
    """
    from seaglass.client import resolve_base_url

    return resolve_base_url()[0]


def _write_if_changed(path: Path, new_text: str, old_text: str) -> bool:
    if new_text == old_text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(new_text, encoding="utf-8")
    return True


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def upsert_markdown(path: Path, body: str) -> bool:
    """Upsert the managed guidance block into a markdown file. Returns changed."""
    old = _read(path)
    new, _changed = mb.upsert(old, body, style=mb.HTML)
    return _write_if_changed(path, new, old)


def _codex_toml_body(*, remote: bool, base_url: str, token_env: str) -> str:
    if remote:
        url = base_url.rstrip("/") + "/mcp"
        return f'[mcp_servers.seaglass]\nurl = "{url}"\nbearer_token_env_var = "{token_env}"\n'
    return '[mcp_servers.seaglass]\ncommand = "seaglass"\nargs = ["bridge"]\n'


def upsert_codex_config(
    path: Path, *, remote: bool = False, base_url: str = "", token_env: str = "SEAGLASS_TOKEN"
) -> bool:
    """Upsert the ``[mcp_servers.seaglass]`` table into Codex config.toml."""
    body = _codex_toml_body(
        remote=remote, base_url=base_url or _default_base_url(), token_env=token_env
    )
    old = _read(path)
    new, _changed = mb.upsert(old, body, style=mb.HASH)
    return _write_if_changed(path, new, old)


def _cursor_server(*, remote: bool, base_url: str) -> dict:
    if remote:
        return {"type": "streamable-http", "url": base_url.rstrip("/") + "/mcp"}
    return {"command": "seaglass", "args": ["bridge"]}


def merge_cursor_mcp_json(path: Path, *, remote: bool = False, base_url: str = "") -> bool:
    """Structurally merge ``mcpServers.seaglass`` into .cursor/mcp.json.

    Preserves every other server and key. Returns whether the file changed.
    """
    old = _read(path)
    try:
        data = json.loads(old) if old.strip() else {}
    except json.JSONDecodeError as e:
        raise ValueError(f"{path} is not valid JSON: {e}") from e
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    servers = data.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        raise ValueError(f"{path}: 'mcpServers' must be an object")
    servers["seaglass"] = _cursor_server(remote=remote, base_url=base_url or _default_base_url())
    new = json.dumps(data, indent=2) + "\n"
    return _write_if_changed(path, new, old)


def install_codex(
    *, config_path: Path, agents_path: Path, remote: bool = False, base_url: str = ""
) -> list[str]:
    """Install the Codex recipe. Returns human-readable status lines."""
    msgs: list[str] = []
    changed_cfg = upsert_codex_config(config_path, remote=remote, base_url=base_url)
    msgs.append(
        f"{'wrote' if changed_cfg else 'unchanged'}: {config_path} ([mcp_servers.seaglass])"
    )
    changed_md = upsert_markdown(agents_path, MANAGED_GUIDANCE)
    msgs.append(f"{'wrote' if changed_md else 'unchanged'}: {agents_path} (managed guidance block)")
    if remote:
        msgs.append(
            "note: remote MCP in Codex needs `experimental_use_rmcp_client = true` under "
            "[features] in config.toml, and SEAGLASS_TOKEN exported."
        )
    return msgs


def install_cursor(
    *, mcp_json_path: Path, rules_path: Path, remote: bool = False, base_url: str = ""
) -> list[str]:
    """Install the Cursor recipe. Returns human-readable status lines."""
    msgs: list[str] = []
    changed_json = merge_cursor_mcp_json(mcp_json_path, remote=remote, base_url=base_url)
    msgs.append(
        f"{'wrote' if changed_json else 'unchanged'}: {mcp_json_path} (mcpServers.seaglass)"
    )
    # .cursor/rules/seaglass.mdc is Seaglass-owned: the whole file is one block.
    changed_rules = upsert_markdown(rules_path, MANAGED_GUIDANCE)
    msgs.append(
        f"{'wrote' if changed_rules else 'unchanged'}: {rules_path} (managed guidance block)"
    )
    return msgs

"""`seaglass` — Seaglass CLI.

A thin client over the same `/mcp` JSON-RPC surface the plugin clients use.
The command groups:

    auth (login/logout/status)  — browser-link auth, token cache
    search                      — search & read memories, documents, pages
    memory / document           — store_memory / store_document
    annotate                    — attach an annotation memory to a page
    flag                        — flag_memory (incorrect/outdated/private/redact)
    reconsolidate               — reconsolidate_memory (split/merge/reassign)
    page (create/edit/append/history/revert/move) — wiki page operations
    profile / me                — read profile + behavioral preferences
    session (end/transcript/briefing) — session lifecycle + transcript upload
    bridge                      — stdio MCP transport bridge (alias: `mcp`)
    install                     — write per-client connector config
    send-product-feedback       — file a Seaglass bug/feature report
    whoami / tools / update     — diagnostics, tool list, self-update
    --version                   — print the CLI version (flag, not a subcommand)

Conventions (follow docs/building-skills-with-clis.md):
- `--json` on every data-returning command (default is human-readable).
- Errors on stderr, data on stdout.
- Documented exit codes: 0 ok, 1 generic, 3 not found, 4 resolution required, 5 auth.
- Stdin input via `-` or `--stdin` for `memory store` and `document store`.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as _dt
import json
import os
import re
import sys
import time
import webbrowser
from dataclasses import replace
from pathlib import Path
from typing import Any

from seaglass import __version__
from seaglass.client import (
    CONFIG_FILE,
    EXIT_AUTH,
    EXIT_GENERIC,
    EXIT_OK,
    TOKEN_FILE,
    CliError,
    _admin_request,
    call_tool,
    clear_token_file,
    end_session,
    fetch_latest_version,
    initialize,
    is_outdated,
    list_tools,
    load_config,
    maybe_notify_update,
    poll_device_link,
    read_resource,
    resolve_base_url,
    resolve_handle,
    session_briefing,
    start_device_link,
    stderr,
    transcript_append,
    transcript_config,
    transcript_finalize,
    upload_document,
    write_config_url,
    write_token_file,
)

# Page types are library-defined data now (ADR-0024); the CLI can't enumerate
# them, so `--type` is a free kebab-case token validated server-side against the
# library's registry. `people`/`projects`/`topics` are the seeded suggestions.
_TYPE_HELP = (
    "page type — a kebab-case token defined in the library "
    "(e.g. people / projects / topics, or any type the library defines)"
)
_FLAG_ACTIONS = (
    "flag_incorrect",
    "flag_outdated",
    "flag_sensitive",
    "flag_private",
    "redact",
)
_MEMORY_SOURCE_KINDS = ("conversation", "user_upload", "web_page", "derived", "paste")
_DOCUMENT_SOURCE_KINDS = (
    "user_upload",
    "web_page",
    "conversation_extract",
    "derived",
    "paste",
)


# ---------- output helpers ----------


def _emit(value: Any, *, as_json: bool) -> None:
    """Print a tool result either as JSON or a short human-readable summary."""
    if as_json:
        print(json.dumps(value, indent=2, sort_keys=True, default=str))
        return
    print(_humanize(value))


def _humanize(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return _humanize_dict(value)
    return json.dumps(value, indent=2, default=str)


def _format_annotations(annotations: list[Any]) -> list[str]:
    """Render annotation memories under a header for page/document/memory modes."""
    lines: list[str] = []
    if not annotations:
        return lines
    lines.append("")
    lines.append(f"annotations ({len(annotations)}):")
    for a in annotations:
        if not isinstance(a, dict):
            continue
        aid = a.get("id", "?")
        body = (a.get("content") or "").strip().replace("\n", " ")
        if len(body) > 200:
            body = body[:197] + "…"
        lines.append(f"  [{aid}] {body}")
    return lines


def _file_mtime_iso(path: Path) -> str | None:
    """Return the file's mtime as a UTC ISO-8601 string, or None if unreadable."""
    try:
        stat = path.stat()
    except OSError:
        return None
    return _dt.datetime.fromtimestamp(stat.st_mtime, tz=_dt.UTC).isoformat()


def _format_move_result(d: dict[str, Any]) -> str:
    """Summarize a move_page result (old/new slug, moved sub-pages, no-op)."""
    if d.get("no_op"):
        return "move was a no-op"
    moved = d.get("moved_subpages") or 0
    tail = f" (+{moved} sub-page{'s' if moved != 1 else ''})" if moved else ""
    return f"moved page → {d.get('new_slug', '?')} (was {d.get('old_slug', '?')}){tail}"


def _format_page_edit_result(d: dict[str, Any]) -> str:
    """Summarize a page-edit result (edit_result_to_dict shape)."""
    line = f"edited page {d.get('page_id', '?')} → v{d.get('version', '?')}"
    if d.get("no_op"):
        line += " (no-op — body unchanged)"
    unresolved = d.get("unresolved_links") or []
    if unresolved:
        line += f"\n  unresolved links: {', '.join(unresolved)}"
    return line


def _format_history_result(d: dict[str, Any]) -> str:
    """Summarize a page-history result ({'entries': [...]})."""
    entries = d.get("entries") or []
    lines = [f"{len(entries)} history " + ("entry" if len(entries) == 1 else "entries")]
    for e in entries:
        if not isinstance(e, dict):
            continue
        version = e.get("version", "?")
        kind = e.get("edit_kind") or "?"
        when = e.get("edited_at") or e.get("created_at") or "?"
        lines.append(f"  - v{version}  {kind}  {when}")
    return "\n".join(lines)


def _format_feedback_result(d: dict[str, Any]) -> str:
    """Summarize a send_seaglass_product_feedback result."""
    return (
        f"filed {d.get('kind', '?')} feedback {d.get('feedback_id', '?')} ({d.get('status', '?')})"
    )


def _humanize_dict(d: dict[str, Any]) -> str:
    # Reconsolidation responses are mode-tagged but distinct from search.
    if d.get("mode") == "analysis":
        lines = ["mode: analysis", f"diagnosis: {d.get('diagnosis', '')}"]
        sub = d.get("sub_identities") or []
        if sub:
            lines.append("sub_identities:")
            for s in sub:
                lines.append(f"  - {json.dumps(s, default=str)}")
        if q := d.get("suggested_clarification_question"):
            lines.append(f"ask user: {q}")
        return "\n".join(lines)
    if d.get("mode") == "apply":
        return (
            f"applied {d.get('kind')}: "
            f"{len(d.get('pages_created') or [])} created, "
            f"{len(d.get('pages_removed') or [])} removed, "
            f"{len(d.get('memories_reassigned') or [])} memories reassigned"
        )
    # Search responses (page, document, memory, index, resolution_required, no_match).
    if "mode" in d:
        return _format_search_results(d)
    if "memory_id" in d:
        return f"stored memory {d['memory_id']} (page {d.get('primary_page_id', '-')})"
    if "document_id" in d:
        extra = " (extraction queued)" if d.get("extraction_queued") else ""
        return f"stored document {d['document_id']} (page {d.get('primary_page_id', '-')}){extra}"
    if "target_id" in d and "action" in d:
        return f"flagged {d['target_id']} as {d['action']}"
    # create_page response: success + id + slug + title + type.
    if "id" in d and "slug" in d and "title" in d and "success" in d:
        return f"created page {d['id']} ({d['slug']} — {d['title']})"
    # move_page response: distinguished by the slug pair.
    if "new_slug" in d and "old_slug" in d:
        return _format_move_result(d)
    if "feedback_id" in d:
        return _format_feedback_result(d)
    if "entries" in d:
        return _format_history_result(d)
    # page-edit / append / revert (edit_result_to_dict): page_id + version.
    if "page_id" in d and "version" in d:
        return _format_page_edit_result(d)
    return json.dumps(d, indent=2, sort_keys=True, default=str)


def _format_outline_block(outline: dict[str, Any] | None) -> list[str]:
    """Render the outline block when present. ``None`` ⇒ nothing to show."""
    if not outline:
        return []
    lines: list[str] = ["[outline]"]
    parent = outline.get("parent")
    if parent:
        label = parent.get("title") or parent.get("slug") or "?"
        lines.append(f"  parent: {label} ({parent.get('type', '?')})")
    if subpages := outline.get("subpages"):
        lines.append("  subpages:")
        for sp in subpages:
            summary = sp.get("one_line_summary") or ""
            tail = f" — {summary}" if summary else ""
            label = sp.get("title") or sp.get("slug") or "?"
            lines.append(f"    - {label} ({sp.get('type', '?')}){tail}")
    if cross_links := outline.get("cross_links"):
        lines.append("  cross-links:")
        for cl in cross_links:
            summary = cl.get("one_line_summary") or ""
            tail = f" — {summary}" if summary else ""
            label = cl.get("title") or cl.get("slug") or "?"
            lines.append(f"    - {label} ({cl.get('type', '?')}){tail}")
    if see_also := outline.get("see_also"):
        lines.append("  see also:")
        for sa in see_also:
            reason = sa.get("reason") or ""
            tail = f" — {reason}" if reason else ""
            label = sa.get("title") or sa.get("slug") or "?"
            lines.append(f"    - {label}{tail}")
    return lines if len(lines) > 1 else []


def _format_backlinks_block(items: list[dict[str, Any]] | None) -> list[str]:
    if not items:
        return []
    lines = ["[backlinks]"]
    for it in items:
        excerpt = it.get("sentence_excerpt") or ""
        tail = f"  {excerpt}" if excerpt else ""
        label = it.get("title") or it.get("slug") or "?"
        lines.append(f"  - {label}{tail}")
    return lines


def _format_recent_edits_block(items: list[dict[str, Any]] | None) -> list[str]:
    if not items:
        return []
    lines = ["[recent edits]"]
    for it in items:
        edited_at = it.get("edited_at") or "?"
        kind = it.get("edit_kind") or "?"
        lines.append(f"  - {edited_at}  {kind}")
    return lines


def _format_search_results(d: dict[str, Any]) -> str:
    """Render the search response (six modes) into a short summary."""
    lines: list[str] = []
    mode = d.get("mode")

    if mode == "page" and isinstance(ent := d.get("page"), dict):
        header_label = ent.get("title") or ent.get("slug") or "page"
        lines.append(f"== {header_label} ({ent.get('type', '?')}) ==")
        lines.append(f"id: {ent.get('id', '?')}")
        if slug := ent.get("slug"):
            lines.append(f"slug: {slug}")
        if hint := ent.get("identity_hint"):
            lines.append(f"hint: {hint}")
        if summary := ent.get("one_line_summary"):
            lines.append(summary)
        outline_lines = _format_outline_block(d.get("outline"))
        if outline_lines:
            lines.append("")
            lines.extend(outline_lines)
        if body := ent.get("synthesis_markdown"):
            lines.append("")
            lines.append(body)
        backlinks_lines = _format_backlinks_block(d.get("backlinks"))
        if backlinks_lines:
            lines.append("")
            lines.extend(backlinks_lines)
        recent_lines = _format_recent_edits_block(d.get("recent_edits"))
        if recent_lines:
            lines.append("")
            lines.extend(recent_lines)
        if writers := ent.get("writers"):
            lines.append("")
            lines.append(f"writers: {', '.join(w.get('display_name', '?') for w in writers)}")
        return "\n".join(lines).rstrip()

    if mode == "document" and isinstance(doc := d.get("document"), dict):
        lines.append(f"== {doc.get('title', 'document')} ==")
        lines.append(f"id: {doc.get('id', '?')}")
        if sma := doc.get("source_modified_at"):
            lines.append(f"source_modified_at: {sma}")
        if saa := doc.get("source_authored_at"):
            lines.append(f"source_authored_at: {saa}")
        if body := doc.get("content"):
            lines.append("")
            lines.append(body if isinstance(body, str) else json.dumps(body))
        lines.extend(_format_annotations(doc.get("annotations") or []))
        return "\n".join(lines).rstrip()

    if mode == "memory" and isinstance(mem := d.get("memory"), dict):
        lines.append(f"memory {mem.get('id', '?')}  (page {mem.get('primary_page_id', '-')})")
        if content := mem.get("content"):
            lines.append(content)
        lines.extend(_format_annotations(mem.get("annotations") or []))
        return "\n".join(lines).rstrip()

    if mode == "resolution_required":
        lines.append("[clarify_with_user]")
        if q := d.get("suggested_clarification_question"):
            lines.append(f"  -> {q}")
        for r in d.get("results") or []:
            label = r.get("title") or r.get("slug") or "?"
            kind = r.get("type", "?")
            hint = r.get("identity_hint")
            extra = f" ({hint})" if hint else ""
            lines.append(f"  {r.get('id', '?')}  {label} [{kind}]{extra}")
        return "\n".join(lines).rstrip()

    if mode == "no_match":
        return "(no match)"

    # mode == "index" (free-text cascade) or any unknown shape with results.
    action = d.get("suggested_action")
    if action and action != "use_top_candidate":
        lines.append(f"[{action}]")
        if q := d.get("suggested_clarification_question"):
            lines.append(f"  -> {q}")
    results = d.get("results") or []
    if results:
        lines.append(f"results ({len(results)}):")
        for r in results[:20]:
            rid = r.get("id", "?")
            score = r.get("score")
            score_s = f"{score:.2f}" if isinstance(score, int | float) else "-"
            preview = (r.get("preview") or r.get("text") or r.get("title") or r.get("slug") or "")[
                :80
            ]
            lines.append(f"  {score_s}  {rid}  {preview}")
    else:
        lines.append("(no results)")
    return "\n".join(lines).rstrip()


# ---------- shared helpers ----------


def _read_content(args: argparse.Namespace, field: str) -> str:
    """Resolve --content/--file/--stdin/positional into a single string."""
    explicit = getattr(args, field, None)
    if explicit == "-" or getattr(args, "stdin", False):
        return sys.stdin.read()
    if path := getattr(args, "file", None):
        return Path(path).read_text(encoding="utf-8")
    if explicit is not None:
        return explicit
    raise CliError(f"--{field} (or --stdin / --file) is required", EXIT_GENERIC)


def _build_links(args: argparse.Namespace) -> dict[str, list[str]] | None:
    links: dict[str, list[str]] = {}
    if args.link_people:
        links["people"] = list(args.link_people)
    if args.link_projects:
        links["projects"] = list(args.link_projects)
    if args.link_topics:
        links["topics"] = list(args.link_topics)
    return links or None


# ---------- command handlers ----------


def cmd_whoami(args: argparse.Namespace) -> int:
    cfg = load_config()
    if not cfg.token:
        stderr("No token found.")
        stderr(f"SEAGLASS_URL = {cfg.base_url}")
        stderr("Run `seaglass auth login` to authenticate, or set SEAGLASS_TOKEN.")
        return EXIT_GENERIC
    info = initialize(cfg)
    if args.json:
        print(json.dumps({"url": cfg.mcp_url, "server": info}, indent=2, default=str))
    else:
        server = info.get("serverInfo") or {}
        print(f"url:     {cfg.mcp_url}")
        print(f"server:  {server.get('name', '?')} {server.get('version', '?')}")
        print("auth:    ok")
    instructions = info.get("instructions")
    if isinstance(instructions, str) and instructions:
        stderr(instructions)
    return EXIT_OK


def cmd_update(args: argparse.Namespace) -> int:
    """Check whether a newer CLI exists and print how to upgrade (never auto-runs)."""
    cfg = load_config()
    latest = fetch_latest_version(cfg)
    if latest is None:
        stderr(f"Could not reach {cfg.base_url} to check for updates.")
        return EXIT_GENERIC
    outdated = is_outdated(__version__, latest)
    if args.json:
        print(json.dumps({"current": __version__, "latest": latest, "outdated": outdated}))
        return EXIT_OK
    if outdated:
        print(f"Update available: v{latest} (you have v{__version__}).")
        print("  pipx upgrade seaglass-cli   # or: uv tool upgrade seaglass-cli")
    else:
        print(f"seaglass {__version__} is up to date.")
    return EXIT_OK


def cmd_tools(args: argparse.Namespace) -> int:
    cfg = load_config()
    tools = list_tools(cfg)
    if args.json:
        print(json.dumps(tools, indent=2, default=str))
        return EXIT_OK
    for t in tools:
        print(f"{t.get('name')}\t{t.get('description', '')}")
    return EXIT_OK


def cmd_bridge(_args: argparse.Namespace) -> int:
    """`seaglass bridge` — local transport adapter, stdio MCP ↔ HTTP MCP.

    Not an MCP server. This is a one-way pipe: read newline-delimited
    JSON-RPC frames from stdin (the MCP stdio contract spoken by Claude
    Code, Claude Desktop, `claude-mcp`, …), POST each frame verbatim to
    `{SEAGLASS_URL}/mcp` with the cached bearer token, write the response
    back as a single line on stdout. Notifications (HTTP 204) produce no
    output. The remote endpoint is the real MCP server; this command only
    moves frames across the network boundary.

    Why this exists: `seaglass` owns auth. Anywhere you can run a local
    command you can speak MCP to Seaglass without ever copy-pasting a token
    or setting an env var, as long as `seaglass auth login` has been run
    once. The bridge is the engine's "client" half of the user-machine
    deployment story.

    Aliased as `seaglass mcp` for backward compatibility with existing
    plugin configs.

    Errors come back as JSON-RPC error frames on stdout (preserving the
    upstream client's contract), with a stderr log line for ops. Loop exits
    cleanly on EOF.
    """
    from seaglass.client import forward_frame

    cfg = load_config()
    # Fail-fast at startup so misconfigured plugins surface a clear error in
    # the IDE rather than getting wedged on the first tool call. The upstream
    # MCP client treats stdio servers that never respond as "still starting".
    if not cfg.token:
        stderr(
            "seaglass bridge: no token configured. "
            "Run `seaglass auth login` first, or export SEAGLASS_TOKEN."
        )
        return EXIT_AUTH

    stdin = sys.stdin.buffer
    stdout = sys.stdout.buffer

    while True:
        line = stdin.readline()
        if not line:  # EOF
            return EXIT_OK
        stripped = line.strip()
        if not stripped:
            continue

        # Sniff the request id up front so we can return a well-formed error
        # frame if the proxy raises before we get a real response.
        request_id: Any = None
        with contextlib.suppress(Exception):
            request_id = json.loads(stripped).get("id")

        try:
            response = forward_frame(cfg, stripped)
        except CliError as e:
            # Notifications (no id) — the spec says we MUST NOT respond at
            # all, so log and continue.
            if request_id is None:
                stderr(f"seaglass bridge: {e}")
                continue
            error_frame = {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32000 if e.exit_code == EXIT_AUTH else -32603,
                    "message": str(e),
                },
            }
            stdout.write((json.dumps(error_frame) + "\n").encode("utf-8"))
            stdout.flush()
            continue

        if response is None:
            # 204 — server-side notification ack. Nothing to forward.
            continue
        # The upstream returns a single JSON object; stdio expects one line.
        text = response.decode("utf-8", errors="replace").rstrip("\n")
        stdout.write((text + "\n").encode("utf-8"))
        stdout.flush()


def cmd_auth_login(args: argparse.Namespace) -> int:
    """`seaglass auth login` — browser-link auth. Mints a token on the server and saves it.

    Mirrors the OAuth 2.0 device authorization grant (RFC 8628), reduced to
    what makes sense for a single-user prototype: the CLI shows a short
    user_code and a URL; the user opens the URL in their already-logged-in
    Seaglass admin tab, clicks Approve, and the CLI's next poll receives a
    freshly-minted bearer token.

    `--url` pins the target host: it persists to ~/.config/seaglass/config.json
    (so future commands resolve there without an env var) and is authoritative
    for this login, overriding the resolved default even when SEAGLASS_URL is set.
    """
    if args.url:
        pinned = args.url.strip()
        write_config_url(pinned)
    cfg = load_config()
    if args.url:
        # The flag is an explicit instruction for *this* login — make it win over
        # whatever load_config resolved (env could otherwise shadow the new pin).
        cfg = replace(cfg, base_url=pinned)
    client_name = args.client_name or _default_client_name()
    payload = start_device_link(cfg, client_kind=args.client_kind, client_name=client_name)

    user_code = payload.get("user_code", "")
    device_code = payload.get("device_code", "")
    verification_uri_complete = payload.get("verification_uri_complete") or payload.get(
        "verification_uri", ""
    )
    interval = int(payload.get("interval") or 2)
    expires_in = int(payload.get("expires_in") or 600)

    if args.json:
        print(
            json.dumps(
                {"user_code": user_code, "verification_uri": verification_uri_complete},
                indent=2,
            )
        )
    else:
        print("To authorize this device, open:")
        print(f"  {verification_uri_complete}")
        print()
        print(f"and confirm the code:  {user_code}")
        print()
        print(f"(Waiting up to {expires_in // 60}m for approval. Ctrl-C to cancel.)")

    if not args.no_browser:
        # Best-effort; users on headless boxes can copy the URL by hand.
        with contextlib.suppress(webbrowser.Error, OSError):
            webbrowser.open(verification_uri_complete, new=2, autoraise=True)

    deadline = time.monotonic() + expires_in
    while time.monotonic() < deadline:
        time.sleep(max(1, interval))
        result = poll_device_link(cfg, device_code)
        status = result.get("status")
        if status == "pending":
            # Server may suggest a longer interval (slow_down semantics).
            if isinstance(new_int := result.get("interval"), int) and new_int > 0:
                interval = new_int
            continue
        if status == "approved":
            raw_token = result.get("raw_token")
            if not raw_token:
                stderr("approved but no token returned; retry with `seaglass auth login`.")
                return EXIT_AUTH
            write_token_file(raw_token)
            display = result.get("agent_display_name") or "seaglass-cli"
            if args.json:
                print(json.dumps({"status": "approved", "agent_display_name": display}, indent=2))
            else:
                print(f"Approved. Token saved to {TOKEN_FILE} (agent: {display}).")
                if args.url:
                    print(f"URL pinned to {pinned} (saved to {CONFIG_FILE}).")
            return EXIT_OK
        if status == "denied":
            stderr("Connection denied in the admin UI.")
            return EXIT_AUTH
        if status == "expired":
            stderr("Login request expired. Try `seaglass auth login` again.")
            return EXIT_AUTH
        if status == "unknown":
            stderr("Server lost track of this login request. Try `seaglass auth login` again.")
            return EXIT_AUTH

    stderr("Timed out waiting for approval.")
    return EXIT_AUTH


def cmd_auth_logout(args: argparse.Namespace) -> int:
    """`seaglass auth logout` — drop the locally-stored token.

    This does NOT revoke the token on the server. Use the admin UI's
    Connections page to revoke a token entry.
    """
    removed = clear_token_file()
    if args.json:
        print(json.dumps({"removed": removed, "path": str(TOKEN_FILE)}))
    elif removed:
        print(f"Removed {TOKEN_FILE}.")
    else:
        print("No local token to remove.")
    return EXIT_OK


def cmd_auth_status(args: argparse.Namespace) -> int:
    """`seaglass auth status` — show where the current token came from and where it points."""
    import os

    cfg = load_config()
    url, url_source = resolve_base_url()
    has_env = bool(os.environ.get("SEAGLASS_TOKEN"))
    file_exists = TOKEN_FILE.exists()
    source: str
    if has_env:
        source = "env (SEAGLASS_TOKEN)"
    elif file_exists:
        source = f"file ({TOKEN_FILE})"
    else:
        source = "none"
    # Human-readable label for where the URL came from (the machine value goes in
    # url_source for --json). Mirrors the layered resolver in client.resolve_base_url.
    url_source_label = {
        "env": "env (SEAGLASS_URL)",
        "config": f"config ({CONFIG_FILE})",
        "default": "default (baked)",
    }.get(url_source, url_source)
    if args.json:
        print(
            json.dumps(
                {
                    "source": source,
                    "url": url,
                    "url_source": url_source,
                    "has_token": bool(cfg.token),
                },
                indent=2,
            )
        )
    else:
        print(f"url:    {url}  (source: {url_source_label})")
        print(f"source: {source}")
        print(f"token:  {'set' if cfg.token else 'not set'}")
    return EXIT_OK


def _default_client_name() -> str:
    """Best-effort host + user descriptor so the admin UI can ID the device."""
    import getpass
    import platform

    try:
        host = platform.node() or "unknown-host"
    except Exception:
        host = "unknown-host"
    try:
        user = getpass.getuser()
    except Exception:
        user = "unknown-user"
    return f"seaglass-cli on {user}@{host}"


_VALID_INCLUDE_FLAGS = ("backlinks", "recent_edits")


def _parse_include_flags(raw: str | None) -> list[str]:
    """Comma-separated --with values, restricted to the valid set."""
    if not raw:
        return []
    out: list[str] = []
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        if token not in _VALID_INCLUDE_FLAGS:
            raise CliError(
                f"unknown --with value {token!r}; valid: {', '.join(_VALID_INCLUDE_FLAGS)}",
                EXIT_GENERIC,
            )
        out.append(token)
    return out


def cmd_search(args: argparse.Namespace) -> int:
    cfg = load_config()
    arguments: dict[str, Any] = {"query": args.query, "limit": args.limit}
    if args.type:
        arguments["type"] = args.type
    if args.include_private:
        arguments["include_private"] = True
    if args.no_body:
        arguments["body"] = False
    includes = _parse_include_flags(getattr(args, "with_", None))
    if includes:
        arguments["include"] = includes
    result = call_tool(cfg, "search", arguments)
    _emit(result, as_json=args.json)
    if isinstance(result, dict):
        mode = result.get("mode")
        if mode == "no_match":
            return 3
        if mode == "resolution_required":
            return 4
    return EXIT_OK


def cmd_memory_store(args: argparse.Namespace) -> int:
    cfg = load_config()
    content = _read_content(args, "content")
    arguments: dict[str, Any] = {
        "content": content,
        "primary_page": args.page,
        "source_type": "primary",
        "source_origin": {"kind": args.source_kind},
    }
    if args.source_ref:
        arguments["source_origin"]["ref"] = args.source_ref
    if args.type:
        arguments["primary_page_type"] = args.type
    if args.identity_hint:
        arguments["identity_hint"] = args.identity_hint
    if args.confidence is not None:
        arguments["confidence"] = args.confidence
    if args.sensitivity:
        arguments["sensitivity"] = args.sensitivity
    if args.event_time:
        arguments["event_time"] = args.event_time
    if args.capture_context:
        arguments["capture_context"] = args.capture_context
    if links := _build_links(args):
        arguments["links"] = links

    result = call_tool(cfg, "store_memory", arguments)
    _emit(result, as_json=args.json)
    return EXIT_OK


def cmd_document_store(args: argparse.Namespace) -> int:
    cfg = load_config()

    # Auto-capture file mtime as source_modified_at when --file is used and
    # the caller didn't pass an explicit value. Gives the LLM a freshness
    # signal during extraction without forcing the agent to remember to
    # set it.
    effective_source_modified_at = args.source_modified_at
    if effective_source_modified_at is None and args.file and not args.no_source_mtime:
        effective_source_modified_at = _file_mtime_iso(Path(args.file))

    # --via-upload: send the file body via POST /v1/documents/upload instead
    # of as a JSON-RPC tool argument. Same auth, same provenance handling,
    # cheaper round-trip for large files. Requires --file (we never read
    # arbitrary stdin into a multipart body — too easy to misuse).
    if args.via_upload:
        if not args.file:
            raise CliError("--via-upload requires --file", EXIT_GENERIC)
        title = args.title or Path(args.file).stem
        if not title:
            raise CliError(
                "--title is required (or pass --file so the stem can be used)",
                EXIT_GENERIC,
            )
        result = upload_document(
            cfg,
            file_path=Path(args.file),
            title=title,
            primary_page=args.page,
            primary_page_type=args.type,
            content_type=args.content_type,
            source_kind=args.source_kind,
            source_ref=args.source_ref,
            sensitivity=args.sensitivity,
            event_time=args.event_time,
            source_authored_at=args.source_authored_at,
            source_modified_at=effective_source_modified_at,
            links=_build_links(args),
        )
        _emit(result, as_json=args.json)
        return EXIT_OK

    content = _read_content(args, "content")
    title = args.title
    if not title and args.file:
        title = Path(args.file).stem
    if not title:
        raise CliError("--title is required (or pass --file so the stem can be used)", EXIT_GENERIC)

    arguments: dict[str, Any] = {
        "title": title,
        "content": content,
        "source_type": "primary",
        "source_origin": {"kind": args.source_kind},
    }
    if args.source_ref:
        arguments["source_origin"]["ref"] = args.source_ref
    if args.content_type:
        arguments["content_type"] = args.content_type
    if args.page:
        arguments["primary_page"] = args.page
    if args.type:
        arguments["primary_page_type"] = args.type
    if args.sensitivity:
        arguments["sensitivity"] = args.sensitivity
    if args.event_time:
        arguments["event_time"] = args.event_time
    if args.source_authored_at:
        arguments["source_authored_at"] = args.source_authored_at
    if effective_source_modified_at:
        arguments["source_modified_at"] = effective_source_modified_at
    if args.capture_context:
        arguments["capture_context"] = args.capture_context
    if links := _build_links(args):
        arguments["links"] = links
    if args.extract is not None:
        arguments["extract"] = args.extract

    result = call_tool(cfg, "store_document", arguments)
    _emit(result, as_json=args.json)
    return EXIT_OK


def cmd_annotate(args: argparse.Namespace) -> int:
    """Attach an annotation memory to an existing document or memory.

    Routes through `store_memory` with `source_type="annotation"`. The agent
    uses this when the user retroactively says "remember, that doc was
    really about X" or "the reason that decision was important is Y".
    """
    cfg = load_config()
    note = args.note if args.note != "-" and not args.stdin else sys.stdin.read()
    if not note or not note.strip():
        raise CliError("annotation note is required (or pass '-' / --stdin)", EXIT_GENERIC)

    target_id = args.target_id
    arguments: dict[str, Any] = {
        "content": note,
        "primary_page": args.page,
        "source_type": "annotation",
        "source_origin": {"kind": "annotation", "ref": target_id},
    }
    if args.type:
        arguments["primary_page_type"] = args.type
    if target_id.startswith("document_"):
        arguments["source_document_id"] = target_id
    elif target_id.startswith("memory_"):
        arguments["source_memory_id"] = target_id
    else:
        raise CliError(
            f"target_id must start with 'document_' or 'memory_' — got {target_id!r}",
            EXIT_GENERIC,
        )
    if args.sensitivity:
        arguments["sensitivity"] = args.sensitivity

    result = call_tool(cfg, "store_memory", arguments)
    _emit(result, as_json=args.json)
    return EXIT_OK


def cmd_flag(args: argparse.Namespace) -> int:
    cfg = load_config()
    arguments: dict[str, Any] = {"target_id": args.target_id, "action": args.action}
    if args.reason:
        arguments["reason"] = args.reason
    result = call_tool(cfg, "flag_memory", arguments)
    _emit(result, as_json=args.json)
    return EXIT_OK


def cmd_feedback(args: argparse.Namespace) -> int:
    cfg = load_config()
    body = _read_content(args, "body")
    arguments: dict[str, Any] = {"kind": args.kind, "body": body}
    if args.title:
        arguments["title"] = args.title
    if args.severity:
        arguments["severity"] = args.severity
    if args.component:
        arguments["component"] = args.component
    if args.tool_name:
        arguments["tool_name"] = args.tool_name
    result = call_tool(cfg, "send_seaglass_product_feedback", arguments)
    _emit(result, as_json=args.json)
    return EXIT_OK


def cmd_session_end(args: argparse.Namespace) -> int:
    """`seaglass session end` — close a chat row by client_session_id.

    Used by the Claude Code ``SessionEnd`` hook (and by anyone scripting
    session lifecycle directly). Resolves the client_session_id from, in
    order: ``--client-session-id`` flag, ``$SEAGLASS_CLIENT_SESSION_ID``,
    ``$CLAUDE_SESSION_ID``. Returns 0 on success regardless of whether a
    row was actually flipped — re-ending is not an error.
    """
    cfg = load_config()
    csid = (
        args.client_session_id
        or os.environ.get("SEAGLASS_CLIENT_SESSION_ID")
        or os.environ.get("CLAUDE_SESSION_ID")
    )
    if not csid:
        stderr(
            "session end: no client_session_id available. "
            "Pass --client-session-id or set SEAGLASS_CLIENT_SESSION_ID / CLAUDE_SESSION_ID."
        )
        return EXIT_GENERIC
    result = end_session(cfg, client_session_id=csid)
    _emit(result, as_json=args.json)
    return EXIT_OK


def _transcript_offset_path(client_session_id: str) -> Path:
    """Local cache of the last *server-confirmed* offset (ADR-0055).

    Purely an optimization — the server's byte_count is the source of truth
    and a missing/stale cache costs one reconciliation round trip, never
    correctness.
    """
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", client_session_id)
    return Path.home() / ".cache" / "seaglass" / "transcripts" / f"{safe}.offset"


def _read_cached_offset(client_session_id: str) -> int:
    try:
        return int(_transcript_offset_path(client_session_id).read_text().strip())
    except (OSError, ValueError):
        return 0


def _write_cached_offset(client_session_id: str, offset: int) -> None:
    path = _transcript_offset_path(client_session_id)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(offset))
    except OSError:
        pass  # best-effort cache; the server reconciles


def _complete_lines_tail(data: bytes, offset: int) -> tuple[str, int]:
    """Bytes past ``offset`` up to the last newline, decoded. Returns (text, end)."""
    tail = data[offset:]
    cut = tail.rfind(b"\n")
    if cut < 0:
        return "", offset
    tail = tail[: cut + 1]
    return tail.decode("utf-8", errors="replace"), offset + len(tail)


def _resolve_client_session_id(explicit: str | None) -> str | None:
    return (
        explicit
        or os.environ.get("SEAGLASS_CLIENT_SESSION_ID")
        or os.environ.get("CLAUDE_SESSION_ID")
    )


def cmd_session_upload_transcript(args: argparse.Namespace) -> int:
    """`seaglass session upload-transcript` — incremental transcript sync (ADR-0055).

    Sends the complete-lines tail of the JSONL past the cached offset; on a
    409 the server's byte_count wins and the send is retried once from
    there. Exit 0 on anything recoverable — this runs inside best-effort
    hooks and must never block a session.
    """
    cfg = load_config()
    csid = _resolve_client_session_id(args.client_session_id)
    if not csid:
        stderr(
            "upload-transcript: no client_session_id available. "
            "Pass --client-session-id or set SEAGLASS_CLIENT_SESSION_ID / CLAUDE_SESSION_ID."
        )
        return EXIT_GENERIC
    if not args.path:
        stderr("upload-transcript: --path <transcript.jsonl> is required.")
        return EXIT_GENERIC
    try:
        data = Path(args.path).read_bytes()
    except OSError as e:
        stderr(f"upload-transcript: cannot read {args.path}: {e}")
        return EXIT_GENERIC

    offset = min(_read_cached_offset(csid), len(data))
    for attempt in (1, 2):
        content, new_offset = _complete_lines_tail(data, offset)
        if not content:
            _emit(
                {"uploaded": False, "byte_count": offset, "reason": "no new lines"},
                as_json=args.json,
            )
            return EXIT_OK
        status, body = transcript_append(
            cfg, client_session_id=csid, byte_offset=offset, content=content
        )
        if status == 409 and attempt == 1:
            detail = body.get("detail", body)
            server_count = int(detail.get("byte_count", 0))
            offset = min(server_count, len(data))
            continue
        if status == 413:
            _write_cached_offset(csid, offset)
            stderr("upload-transcript: transcript cap reached; stopping for this session.")
            return EXIT_OK
        if status == 409:
            stderr("upload-transcript: offset mismatch persisted after reconcile; giving up.")
            return EXIT_OK
        confirmed = int(body.get("byte_count", new_offset))
        _write_cached_offset(csid, confirmed)
        _emit({"uploaded": True, **body}, as_json=args.json)
        return EXIT_OK
    return EXIT_OK


def cmd_session_finalize_transcript(args: argparse.Namespace) -> int:
    """`seaglass session finalize-transcript` — flush + mark final (SessionEnd hook)."""
    cfg = load_config()
    csid = _resolve_client_session_id(args.client_session_id)
    if not csid:
        stderr("finalize-transcript: no client_session_id available.")
        return EXIT_GENERIC
    if args.path:
        upload_args = argparse.Namespace(client_session_id=csid, path=args.path, json=False)
        cmd_session_upload_transcript(upload_args)
    result = transcript_finalize(cfg, client_session_id=csid, reason=args.reason)
    _emit(result, as_json=args.json)
    return EXIT_OK


def cmd_session_transcript_config(args: argparse.Namespace) -> int:
    """`seaglass session transcript-config` — print the effective capture setting.

    The SessionStart hook calls this once and exports
    ``SEAGLASS_TRANSCRIPT_CAPTURE`` so the per-turn upload hooks can no-op
    without a network round trip.
    """
    cfg = load_config()
    result = transcript_config(cfg)
    if args.json:
        _emit(result, as_json=True)
    else:
        print(result.get("transcript_capture", "off"))
    return EXIT_OK


def _render_briefing(b: dict[str, Any]) -> str:
    """Render the briefing payload (ADR-0067) into a compact markdown block.

    Returns "" when nothing is worth showing, so the SessionStart hook can
    skip emitting it.
    """
    if not b.get("available"):
        return ""
    lines = ["## Last session (this agent)"]
    ended = b.get("ended_at")
    if ended:
        lines.append(f"Ended: {ended}")
    excerpts = b.get("memory_excerpts") or []
    mem_count = b.get("memory_count", 0)
    if excerpts:
        lines.append("")
        lines.append(f"Captured {mem_count} memor{'y' if mem_count == 1 else 'ies'}:")
        lines.extend(f"- {e}" for e in excerpts)
        hidden = mem_count - len(excerpts)
        if hidden > 0:
            lines.append(f"- …and {hidden} more")
    private_count = b.get("private_memory_count", 0)
    if private_count:
        lines.append(
            f"_({private_count} private memor{'y' if private_count == 1 else 'ies'} "
            "withheld from this briefing.)_"
        )
    line_count = b.get("transcript_line_count")
    if line_count:
        redactions = b.get("transcript_redaction_count") or 0
        note = f"Transcript archived: {line_count} lines"
        if redactions:
            note += f", {redactions} secret(s) scrubbed"
        note += " — search it with `transcript_search`."
        lines.append("")
        lines.append(note)
    return "\n".join(lines)


def cmd_session_briefing(args: argparse.Namespace) -> int:
    """`seaglass session briefing` — render the previous session's digest (ADR-0067).

    The SessionStart hook appends this to the profile it injects, giving the
    agent continuity with what it did last time. Prints nothing when there's
    no prior session worth summarizing.
    """
    cfg = load_config()
    result = session_briefing(cfg)
    if args.json:
        _emit(result, as_json=True)
    else:
        rendered = _render_briefing(result)
        if rendered:
            print(rendered)
    return EXIT_OK


def cmd_me(args: argparse.Namespace) -> int:
    """`seaglass me` — print the user profile.

    Prints the rendered ``seaglass://profile`` resource — the same markdown
    the LLM sees at session start (identity, behavior instructions derived
    from your preferences, custom instructions, links to adjust).
    """
    cfg = load_config()
    text = read_resource(cfg, "seaglass://profile")
    if args.json:
        print(json.dumps({"markdown": text}, indent=2))
    else:
        print(text.rstrip())
    return EXIT_OK


# ----- profile subcommands -----


_PREFERENCE_KEYS = ("recall", "capture", "approval", "disclosure")
_PREFERENCE_VALUES: dict[str, tuple[str, ...]] = {
    "recall": ("reserved", "balanced", "eager"),
    "capture": ("reserved", "balanced", "eager"),
    "approval": ("never", "sensitive", "always"),
    "disclosure": ("quiet", "balanced", "verbose"),
}


def _format_effective(eff: dict[str, str]) -> str:
    parts = [f"{k}={eff[k]}" for k in _PREFERENCE_KEYS]
    return ", ".join(parts)


def _render_user_profile(data: dict[str, Any]) -> str:
    lines: list[str] = []
    syn = data.get("synthesized") or {}
    eff = data.get("effective_preferences") or {}
    raw = data.get("preferences") or {}

    lines.append("== profile (you) ==")
    md = (syn.get("markdown_content") or "").strip()
    if md:
        lines.append("")
        lines.append("## synthesized")
        lines.append(md)
    else:
        lines.append("")
        lines.append("(no synthesized profile yet)")

    lines.append("")
    lines.append("## preferences")
    for key in _PREFERENCE_KEYS:
        v_raw = raw.get(key)
        v_eff = eff.get(key)
        suffix = "" if v_raw == v_eff or v_raw is None else f"  (raw={v_raw})"
        lines.append(f"  {key}: {v_eff}{suffix}")

    inst = (data.get("instructions") or "").strip()
    if inst:
        lines.append("")
        lines.append("## custom instructions")
        lines.append(inst)

    agents = data.get("agents") or []
    if agents:
        lines.append("")
        lines.append("## integrations")
        for a in agents:
            ae = a.get("effective_preferences") or {}
            lines.append(
                f"  {a.get('agent_id', '?')}  {a.get('display_name', '?')}  "
                f"({a.get('client_kind', '?')})  → {_format_effective(ae)}"
            )
    return "\n".join(lines).rstrip()


def _render_agent_profile(data: dict[str, Any]) -> str:
    lines: list[str] = []
    syn = data.get("synthesized") or {}
    eff = data.get("effective_preferences") or {}
    raw = data.get("preferences") or {}

    lines.append(f"== profile (agent: {data.get('agent_display_name', '?')}) ==")
    lines.append(f"agent_id: {data.get('agent_id', '?')}")
    md = (syn.get("markdown_content") or "").strip()
    if md:
        lines.append("")
        lines.append("## synthesized")
        lines.append(md)
    else:
        lines.append("")
        lines.append("(no synthesized profile for this integration yet)")

    lines.append("")
    lines.append("## preferences (null = inherit from user defaults)")
    for key in _PREFERENCE_KEYS:
        v_raw = raw.get(key)
        v_eff = eff.get(key)
        label = "inherit" if v_raw is None else v_raw
        lines.append(f"  {key}: {v_eff}  (override: {label})")

    inst = (data.get("instructions") or "").strip()
    if inst:
        lines.append("")
        lines.append("## additional instructions")
        lines.append(inst)
    return "\n".join(lines).rstrip()


def _emit_data(data: Any, *, as_json: bool, renderer) -> int:
    if as_json:
        print(json.dumps(data, indent=2, default=str, sort_keys=True))
    else:
        print(renderer(data) if callable(renderer) else json.dumps(data, indent=2, default=str))
    return EXIT_OK


def _resolve_agent_id(cfg, ref: str) -> str:
    """Accept a typed ID, a slugified display name, or a partial match.

    The addressed endpoint accepts a typed ``agent_01HX...`` ID; if the user
    passed a display name, look it up from the integrations list.
    """
    if ref.startswith("agent_"):
        return ref
    handle = resolve_handle(cfg)
    agents = _admin_request(cfg, "GET", f"/v1/accounts/{handle}/profile/agents") or []
    candidates: list[dict[str, Any]] = []
    needle = ref.lower()
    for a in agents:
        dn = (a.get("display_name") or "").lower()
        if needle == dn or needle in dn.replace(" ", "-") or needle in dn:
            candidates.append(a)
    if len(candidates) == 1:
        return candidates[0]["agent_id"]
    if not candidates:
        raise CliError(f"no integration matching {ref!r}", 3)
    raise CliError(
        "ambiguous integration name — pass the agent_ id instead. Candidates: "
        + ", ".join(f"{c.get('display_name')} ({c.get('agent_id')})" for c in candidates),
        4,
    )


def _edit_in_editor(initial: str) -> str:
    """Spawn $EDITOR on a temp .md and return the new contents.

    Used by ``seaglass profile instructions`` and ``seaglass profile agent ... instructions``.
    Returns the original text if the editor is unchanged or the user aborts.
    """
    import subprocess
    import tempfile

    editor = os.environ.get("EDITOR") or os.environ.get("VISUAL") or "nano"
    with tempfile.NamedTemporaryFile(mode="w+", suffix=".md", delete=False) as tf:
        tf.write(initial)
        path = tf.name
    try:
        subprocess.call([editor, path])
        return Path(path).read_text(encoding="utf-8")
    finally:
        with contextlib.suppress(OSError):
            os.unlink(path)


def cmd_profile_show(args: argparse.Namespace) -> int:
    cfg = load_config()
    if getattr(args, "render", False):
        # `--render` prints the same markdown the LLM sees at session start.
        text = read_resource(cfg, "seaglass://profile")
        if args.json:
            print(json.dumps({"markdown": text}, indent=2))
        else:
            print(text.rstrip())
        return EXIT_OK
    handle = resolve_handle(cfg)
    data = _admin_request(cfg, "GET", f"/v1/accounts/{handle}/profile")
    return _emit_data(data, as_json=args.json, renderer=_render_user_profile)


def _deprecate_profile_write(cmd: str, admin_path: str) -> None:
    """Emit ADR-0006 deprecation warning on every profile-write subcommand.

    Profile state is web-UI only. The CLI write paths still function for
    one release so existing scripts don't break, but each invocation
    surfaces the admin URL so users migrate before the removal release.
    """
    cfg = load_config()
    admin_url = cfg.base_url.rstrip("/")
    stderr(
        f"warning: `seaglass {cmd}` is deprecated (ADR-0006). "
        f"Profile state is managed in the admin web UI: {admin_url}{admin_path}. "
        f"This subcommand will be removed in the next minor release."
    )


def cmd_profile_set(args: argparse.Namespace) -> int:
    _deprecate_profile_write("profile set", "/profile")
    cfg = load_config()
    handle = resolve_handle(cfg)
    body = {"preferences": {args.key: args.value}}
    data = _admin_request(cfg, "PATCH", f"/v1/accounts/{handle}/profile", body=body)
    return _emit_data(data, as_json=args.json, renderer=_render_user_profile)


def cmd_profile_instructions(args: argparse.Namespace) -> int:
    if not args.print:
        _deprecate_profile_write("profile instructions", "/profile")
    cfg = load_config()
    handle = resolve_handle(cfg)
    data = _admin_request(cfg, "GET", f"/v1/accounts/{handle}/profile") or {}
    current = data.get("instructions") or ""
    if args.print:
        print(current.rstrip())
        return EXIT_OK
    if args.set is not None:
        new_text = args.set
    elif args.stdin:
        new_text = sys.stdin.read()
    else:
        new_text = _edit_in_editor(current)
    new_text = new_text.rstrip() + ("\n" if new_text.strip() else "")
    if new_text.strip() == current.strip():
        stderr("(unchanged)")
        return EXIT_OK
    data = _admin_request(
        cfg, "PATCH", f"/v1/accounts/{handle}/profile", body={"instructions": new_text}
    )
    return _emit_data(data, as_json=args.json, renderer=_render_user_profile)


def cmd_profile_agents(args: argparse.Namespace) -> int:
    cfg = load_config()
    handle = resolve_handle(cfg)
    data = _admin_request(cfg, "GET", f"/v1/accounts/{handle}/profile/agents") or []
    if args.json:
        print(json.dumps(data, indent=2, default=str, sort_keys=True))
        return EXIT_OK
    if not data:
        print("(no integrations)")
        return EXIT_OK
    for a in data:
        eff = a.get("effective_preferences") or {}
        print(
            f"{a.get('agent_id')}  {a.get('display_name')}  "
            f"({a.get('client_kind')})  → {_format_effective(eff)}"
        )
    return EXIT_OK


def cmd_profile_agent_show(args: argparse.Namespace) -> int:
    cfg = load_config()
    agent_id = _resolve_agent_id(cfg, args.agent)
    handle = resolve_handle(cfg)
    data = _admin_request(cfg, "GET", f"/v1/accounts/{handle}/profile/agents/{agent_id}")
    return _emit_data(data, as_json=args.json, renderer=_render_agent_profile)


def cmd_profile_agent_set(args: argparse.Namespace) -> int:
    cfg = load_config()
    agent_id = _resolve_agent_id(cfg, args.agent)
    handle = resolve_handle(cfg)
    _deprecate_profile_write("profile agent set", f"/profile/agents/{agent_id}")
    body = {"preferences": {args.key: args.value}}
    data = _admin_request(
        cfg, "PATCH", f"/v1/accounts/{handle}/profile/agents/{agent_id}", body=body
    )
    return _emit_data(data, as_json=args.json, renderer=_render_agent_profile)


def cmd_profile_agent_inherit(args: argparse.Namespace) -> int:
    cfg = load_config()
    agent_id = _resolve_agent_id(cfg, args.agent)
    handle = resolve_handle(cfg)
    _deprecate_profile_write("profile agent inherit", f"/profile/agents/{agent_id}")
    body = {"preferences": {args.key: None}}
    data = _admin_request(
        cfg, "PATCH", f"/v1/accounts/{handle}/profile/agents/{agent_id}", body=body
    )
    return _emit_data(data, as_json=args.json, renderer=_render_agent_profile)


def cmd_profile_agent_instructions(args: argparse.Namespace) -> int:
    cfg = load_config()
    agent_id = _resolve_agent_id(cfg, args.agent)
    handle = resolve_handle(cfg)
    if not args.print:
        _deprecate_profile_write("profile agent instructions", f"/profile/agents/{agent_id}")
    data = _admin_request(cfg, "GET", f"/v1/accounts/{handle}/profile/agents/{agent_id}") or {}
    current = data.get("instructions") or ""
    if args.print:
        print(current.rstrip())
        return EXIT_OK
    if args.set is not None:
        new_text = args.set
    elif args.stdin:
        new_text = sys.stdin.read()
    else:
        new_text = _edit_in_editor(current)
    new_text = new_text.rstrip() + ("\n" if new_text.strip() else "")
    if new_text.strip() == current.strip():
        stderr("(unchanged)")
        return EXIT_OK
    data = _admin_request(
        cfg,
        "PATCH",
        f"/v1/accounts/{handle}/profile/agents/{agent_id}",
        body={"instructions": new_text},
    )
    return _emit_data(data, as_json=args.json, renderer=_render_agent_profile)


def cmd_page_create(args: argparse.Namespace) -> int:
    """`seaglass page create` — explicit wiki page creation (ADR-0011 shapes)."""
    cfg = load_config()
    arguments: dict[str, Any] = {}
    if args.slug:
        arguments["slug"] = args.slug
    if args.parent:
        arguments["parent"] = args.parent
    if args.type:
        arguments["type"] = args.type
    if args.title:
        arguments["title"] = args.title
    if args.identity_hint:
        arguments["identity_hint"] = args.identity_hint
    if not arguments:
        raise CliError(
            "page create needs --slug, or --parent+--title, or --type+--title; see --help"
        )
    result = call_tool(cfg, "create_page", arguments)
    _emit(result, as_json=args.json)
    return EXIT_OK


def _read_page_content(args: argparse.Namespace) -> str:
    """Resolve --content / --content-file / --editor / stdin into a string."""
    if getattr(args, "stdin", False) or getattr(args, "content", None) == "-":
        return sys.stdin.read()
    if path := getattr(args, "content_file", None):
        return Path(path).read_text(encoding="utf-8")
    if getattr(args, "content", None) is not None:
        return args.content
    raise CliError(
        "one of --content / --content-file / --stdin is required (or pipe via -)",
        EXIT_GENERIC,
    )


def _evidence_lists(args: argparse.Namespace) -> tuple[list[str], list[str]]:
    """Split --evidence values into memory/document buckets by ID prefix."""
    memory_ids: list[str] = []
    document_ids: list[str] = []
    for value in getattr(args, "evidence", None) or []:
        if value.startswith("memory_"):
            memory_ids.append(value)
        elif value.startswith("document_"):
            document_ids.append(value)
        else:
            raise CliError(
                f"--evidence value {value!r} must start with 'memory_' or 'document_'",
                EXIT_GENERIC,
            )
    return memory_ids, document_ids


def _fetch_page_version(cfg, page: str) -> int:
    """Read the current page version for human-friendly base_version flows."""
    result = call_tool(cfg, "search", {"query": page, "body": False})
    if not isinstance(result, dict) or result.get("mode") != "page":
        raise CliError(f"could not resolve {page!r} to a page for version lookup", EXIT_GENERIC)
    page_dict = result.get("page") or {}
    # `search` surfaces the page version inside the page payload (ADR-0005 §5).
    version = page_dict.get("version")
    if isinstance(version, int):
        return version
    return 0


def cmd_page_edit(args: argparse.Namespace) -> int:
    """`seaglass page edit` — replace page or section body with optimistic concurrency."""
    cfg = load_config()
    content = _read_page_content(args)
    memory_evidence, document_evidence = _evidence_lists(args)

    arguments: dict[str, Any] = {
        "page": args.page,
        "content": content,
        "base_version": args.base_version
        if args.base_version is not None
        else _fetch_page_version(cfg, args.page),
    }
    if args.edit_summary:
        arguments["edit_summary"] = args.edit_summary
    if memory_evidence:
        arguments["evidence_memory_ids"] = memory_evidence
    if document_evidence:
        arguments["evidence_document_ids"] = document_evidence

    if args.section:
        arguments["section"] = args.section
        result = call_tool(cfg, "edit_section", arguments)
    else:
        result = call_tool(cfg, "edit_page", arguments)
    _emit(result, as_json=args.json)
    return EXIT_OK


def cmd_page_append(args: argparse.Namespace) -> int:
    """`seaglass page append` — additive new section."""
    cfg = load_config()
    content = _read_page_content(args)
    memory_evidence, document_evidence = _evidence_lists(args)
    arguments: dict[str, Any] = {
        "page": args.page,
        "heading": args.section,
        "content": content,
    }
    if args.level:
        arguments["level"] = args.level
    if args.edit_summary:
        arguments["edit_summary"] = args.edit_summary
    if memory_evidence:
        arguments["evidence_memory_ids"] = memory_evidence
    if document_evidence:
        arguments["evidence_document_ids"] = document_evidence
    result = call_tool(cfg, "append_section", arguments)
    _emit(result, as_json=args.json)
    return EXIT_OK


def cmd_page_history(args: argparse.Namespace) -> int:
    cfg = load_config()
    result = call_tool(cfg, "get_page_history", {"page": args.page, "limit": args.limit})
    _emit(result, as_json=args.json)
    return EXIT_OK


def cmd_page_revert(args: argparse.Namespace) -> int:
    cfg = load_config()
    arguments: dict[str, Any] = {"page": args.page, "to_version": args.to_version}
    if args.edit_summary:
        arguments["edit_summary"] = args.edit_summary
    result = call_tool(cfg, "revert_page", arguments)
    _emit(result, as_json=args.json)
    return EXIT_OK


def cmd_page_move(args: argparse.Namespace) -> int:
    """`seaglass page move` — rename a page or move it under a new parent."""
    cfg = load_config()
    arguments: dict[str, Any] = {"page": args.page, "to": args.to}
    if args.title:
        arguments["title"] = args.title
    if args.edit_summary:
        arguments["edit_summary"] = args.edit_summary
    result = call_tool(cfg, "move_page", arguments)
    _emit(result, as_json=args.json)
    return EXIT_OK


def cmd_install(args: argparse.Namespace) -> int:
    """`seaglass install <client>` — write per-client connector config + guidance.

    Idempotent: re-running it is a no-op when nothing changed (ADR-0030). The
    default recipe points at the `seaglass bridge` stdio transport; `--remote`
    emits the hosted-MCP variant (URL, for use after `seaglass auth login` /
    OAuth).
    """
    from seaglass import install as _install

    root = Path(args.dir) if args.dir else Path.cwd()
    base_url = load_config().base_url
    if args.client == "codex":
        config_path = (
            Path(args.codex_config) if args.codex_config else Path.home() / ".codex" / "config.toml"
        )
        msgs = _install.install_codex(
            config_path=config_path,
            agents_path=root / "AGENTS.md",
            remote=args.remote,
            base_url=base_url,
        )
    elif args.client == "cursor":
        try:
            msgs = _install.install_cursor(
                mcp_json_path=root / ".cursor" / "mcp.json",
                rules_path=root / ".cursor" / "rules" / "seaglass.mdc",
                remote=args.remote,
                base_url=base_url,
            )
        except ValueError as e:
            raise CliError(str(e), EXIT_GENERIC) from e
    else:  # pragma: no cover - argparse choices guard this
        raise CliError(f"unknown client {args.client!r}", EXIT_GENERIC)

    if args.json:
        print(json.dumps({"client": args.client, "results": msgs}, indent=2))
    else:
        for m in msgs:
            print(m)
    return EXIT_OK


def cmd_reconsolidate(args: argparse.Namespace) -> int:
    cfg = load_config()
    arguments: dict[str, Any] = {"query": args.query}
    if args.resolution_json:
        try:
            arguments["resolution"] = json.loads(args.resolution_json)
        except json.JSONDecodeError as e:
            raise CliError(f"--resolution-json is not valid JSON: {e}", EXIT_GENERIC) from e
    elif args.kind:
        arguments["resolution"] = {"kind": args.kind}
        if args.details_json:
            try:
                arguments["resolution"]["details"] = json.loads(args.details_json)
            except json.JSONDecodeError as e:
                raise CliError(f"--details-json is not valid JSON: {e}", EXIT_GENERIC) from e
    result = call_tool(cfg, "reconsolidate_memory", arguments)
    _emit(result, as_json=args.json)
    return EXIT_OK


# ---------- argparse plumbing ----------


def _add_json_flag(p: argparse.ArgumentParser) -> None:
    p.add_argument("--json", action="store_true", help="emit raw JSON on stdout")


def _add_links(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--link-people",
        action="append",
        default=[],
        metavar="NAME",
        help="secondary person referenced (repeatable)",
    )
    p.add_argument(
        "--link-projects",
        action="append",
        default=[],
        metavar="NAME",
        help="secondary project referenced (repeatable)",
    )
    p.add_argument(
        "--link-topics",
        action="append",
        default=[],
        metavar="NAME",
        help="secondary topic referenced (repeatable)",
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="seaglass",
        description=(
            "Seaglass CLI — read and write personal memory through the same MCP "
            "endpoint Claude Code uses. Run `seaglass auth login` once to authenticate."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Exit codes: 0 ok, 1 generic, 3 not found, 4 resolution required, 5 auth.\n"
            "Run `seaglass auth login` to authenticate. Server URL resolves SEAGLASS_URL "
            "(env) > the `auth login --url` pin > the baked default; `seaglass auth status` "
            "shows the active URL and its source."
        ),
    )
    p.add_argument("--version", action="version", version=f"seaglass {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    # whoami
    sp = sub.add_parser("whoami", help="verify the cached token against the server")
    _add_json_flag(sp)
    sp.set_defaults(func=cmd_whoami)

    # tools
    sp = sub.add_parser("tools", help="list MCP tools advertised by the server")
    _add_json_flag(sp)
    sp.set_defaults(func=cmd_tools)

    # update — check the server for a newer CLI and print how to upgrade.
    sp = sub.add_parser(
        "update",
        help="check whether a newer seaglass CLI is available (prints how to upgrade)",
        description=(
            "Asks the server for the latest version and compares it to this CLI. "
            "Prints the upgrade command if you're behind — it never installs "
            "anything for you."
        ),
    )
    _add_json_flag(sp)
    sp.set_defaults(func=cmd_update)

    # bridge — local transport adapter (stdio MCP ↔ HTTP MCP).
    # Aliased as `mcp` for backward compatibility with existing plugin configs.
    sp = sub.add_parser(
        "bridge",
        aliases=["mcp"],
        help="run the stdio MCP transport bridge (used by Claude Code + Desktop plugins)",
        description=(
            "Transport adapter, not an MCP server. Reads JSON-RPC frames on "
            "stdin, forwards them to {SEAGLASS_URL}/mcp with the cached bearer "
            "token, writes responses on stdout. Run `seaglass auth login` first; "
            "this command is not meant to be invoked by humans — it's pointed "
            "at by MCP clients' stdio configuration. Aliased as `seaglass mcp` "
            "for backward compatibility."
        ),
    )
    sp.set_defaults(func=cmd_bridge)

    # auth — browser-link login, logout, status.
    auth_parser = sub.add_parser(
        "auth",
        help="authenticate the CLI via the web (seaglass auth login / logout / status)",
        description=(
            "`seaglass auth login` opens the Seaglass web app, asks you to approve the "
            "device, and stores the resulting token in ~/.config/seaglass/token. "
            "The plugin's stdio transport (`seaglass bridge`) reads from the same file, so one "
            "login authenticates Claude Code, Claude Desktop, and direct `seaglass` "
            "use. SEAGLASS_TOKEN still takes precedence (used for CI / automation)."
        ),
    )
    auth_sub = auth_parser.add_subparsers(dest="auth_command", required=True)

    sp = auth_sub.add_parser(
        "login",
        help="link this CLI to a Seaglass user via the web admin UI",
        description=(
            "Issues a short user_code, opens the verification URL in your default "
            "browser, polls until you approve, then saves the resulting token. "
            "Pass --url to log in to a specific server and pin it for later commands."
        ),
    )
    sp.add_argument(
        "--no-browser",
        action="store_true",
        help="don't try to open the URL — just print it (handy for SSH / CI).",
    )
    sp.add_argument(
        "--url",
        default=None,
        help=(
            "base URL of the Seaglass server to log in to; pins it to "
            "~/.config/seaglass/config.json for future commands (SEAGLASS_URL still wins)."
        ),
    )
    sp.add_argument(
        "--client-kind",
        default="seaglass-cli",
        help="self-declared client kind shown to the user before approval.",
    )
    sp.add_argument(
        "--client-name",
        default=None,
        help="display name for the connection (defaults to user@host).",
    )
    _add_json_flag(sp)
    sp.set_defaults(func=cmd_auth_login)

    sp = auth_sub.add_parser(
        "logout",
        help="forget the locally-stored token (does NOT revoke it server-side)",
    )
    _add_json_flag(sp)
    sp.set_defaults(func=cmd_auth_logout)

    sp = auth_sub.add_parser(
        "status",
        help="show where the active token comes from and where the CLI points.",
    )
    _add_json_flag(sp)
    sp.set_defaults(func=cmd_auth_status)

    # session — chat lifecycle commands (currently just `end`).
    session_parser = sub.add_parser(
        "session",
        help="session lifecycle (`session end` closes a chat row)",
    )
    session_sub = session_parser.add_subparsers(dest="session_cmd", required=True)
    sp = session_sub.add_parser(
        "end",
        help="close a session by client_session_id (idempotent)",
        description=(
            "Marks the matching open `sessions` row as ended. Used by the "
            "Claude Code SessionEnd hook to signal chat boundaries. Reads "
            "the id from --client-session-id, then $SEAGLASS_CLIENT_SESSION_ID, "
            "then $CLAUDE_SESSION_ID."
        ),
    )
    sp.add_argument(
        "--client-session-id",
        help="explicit client session id (overrides env vars)",
    )
    _add_json_flag(sp)
    sp.set_defaults(func=cmd_session_end)

    sp = session_sub.add_parser(
        "upload-transcript",
        # Incremental transcript upload via plugin hooks (ADR-0055).
        help="incrementally upload the session transcript",
        description=(
            "Sends the complete-lines tail of a Claude Code JSONL transcript "
            "past the last server-confirmed byte offset. Safe to call "
            "repeatedly; the server reconciles offsets. Used by the plugin "
            "Stop/PreCompact hooks and available manually when auto-capture "
            "is off."
        ),
    )
    sp.add_argument("--path", help="path to the transcript .jsonl file", required=False)
    sp.add_argument("--client-session-id", help="explicit client session id")
    _add_json_flag(sp)
    sp.set_defaults(func=cmd_session_upload_transcript)

    sp = session_sub.add_parser(
        "finalize-transcript",
        help="flush remaining lines and mark the transcript final",
    )
    sp.add_argument("--path", help="transcript .jsonl to flush before finalizing")
    sp.add_argument("--client-session-id", help="explicit client session id")
    sp.add_argument("--reason", default="other", help="end reason (SessionEnd hook passes its own)")
    _add_json_flag(sp)
    sp.set_defaults(func=cmd_session_finalize_transcript)

    sp = session_sub.add_parser(
        "transcript-config",
        help="print the effective transcript_capture setting (on/off)",
    )
    _add_json_flag(sp)
    sp.set_defaults(func=cmd_session_transcript_config)

    sp = session_sub.add_parser(
        "briefing",
        # Previous-session digest for resume context (ADR-0067).
        help="render the previous session's digest for resume context",
        description=(
            "Prints a compact markdown summary of this agent's last ended "
            "session — when it ran, the non-private memories it captured, and "
            "transcript stats if one was archived. The SessionStart hook "
            "appends it to the injected profile. Prints nothing when there's "
            "no prior session worth summarizing."
        ),
    )
    _add_json_flag(sp)
    sp.set_defaults(func=cmd_session_briefing)

    # me — read the user profile.
    sp = sub.add_parser(
        "me",
        help="read the user profile",
        description=(
            "Returns the user profile — identity, behavior instructions, and "
            "custom instructions. Call this at the start of a session to load "
            "the user's preferences."
        ),
    )
    _add_json_flag(sp)
    sp.set_defaults(func=cmd_me)

    # profile — read & edit user/agent preferences and instructions.
    prof = sub.add_parser(
        "profile",
        help="view and edit your profile + behavioral preferences",
        description=(
            "Read the rendered profile, or manage preferences for your "
            "user defaults and per-integration overrides. Same data the LLM "
            "reads from `seaglass://profile` at session start."
        ),
    )
    prof.add_argument(
        "--render",
        action="store_true",
        help="print the LLM-facing markdown (same as seaglass://profile)",
    )
    _add_json_flag(prof)
    prof.set_defaults(func=cmd_profile_show)

    prof_sub = prof.add_subparsers(dest="profile_command", required=False)

    sp = prof_sub.add_parser(
        "set",
        # Display names (Reading/Writing/Asking/Voicing) gloss the real keys.
        help="set a user-level preference (recall / capture / approval / disclosure)",
    )
    sp.add_argument("key", choices=_PREFERENCE_KEYS)
    sp.add_argument(
        "value",
        help=(
            "one of: recall/capture → reserved|balanced|eager · "
            "approval → never|sensitive|always · disclosure → quiet|balanced|verbose"
        ),
    )
    _add_json_flag(sp)
    sp.set_defaults(func=cmd_profile_set)

    sp = prof_sub.add_parser(
        "instructions",
        help="edit your custom instructions (markdown)",
        description=(
            "Open $EDITOR with your current user-level instructions and save "
            "on exit. Use --print to read, --set TEXT to set non-interactively, "
            "or --stdin to read from stdin."
        ),
    )
    sp.add_argument("--print", action="store_true", help="print current instructions and exit")
    sp.add_argument("--set", metavar="TEXT", help="set instructions non-interactively")
    sp.add_argument("--stdin", action="store_true", help="read new instructions from stdin")
    _add_json_flag(sp)
    sp.set_defaults(func=cmd_profile_instructions)

    sp = prof_sub.add_parser("agents", help="list integrations and their effective preferences")
    _add_json_flag(sp)
    sp.set_defaults(func=cmd_profile_agents)

    agent_parser = prof_sub.add_parser(
        "agent",
        help="view or edit a specific integration's profile",
        description="Pass a typed agent_ id or an unambiguous display name match.",
    )
    agent_parser.add_argument(
        "agent", help="agent_01HX... id or unambiguous display name (e.g. claude-code-laptop)"
    )
    _add_json_flag(agent_parser)
    agent_parser.set_defaults(func=cmd_profile_agent_show)
    agent_sub = agent_parser.add_subparsers(dest="agent_command", required=False)

    sp = agent_sub.add_parser(
        "set",
        help="override a preference just for this integration",
    )
    sp.add_argument("key", choices=_PREFERENCE_KEYS)
    sp.add_argument("value")
    _add_json_flag(sp)
    sp.set_defaults(func=cmd_profile_agent_set)

    sp = agent_sub.add_parser(
        "inherit",
        help="reset a preference for this integration to inherit from user defaults",
    )
    sp.add_argument("key", choices=_PREFERENCE_KEYS)
    _add_json_flag(sp)
    sp.set_defaults(func=cmd_profile_agent_inherit)

    sp = agent_sub.add_parser(
        "instructions",
        help="edit this integration's additional instructions (markdown)",
    )
    sp.add_argument("--print", action="store_true", help="print current instructions and exit")
    sp.add_argument("--set", metavar="TEXT", help="set instructions non-interactively")
    sp.add_argument("--stdin", action="store_true", help="read new instructions from stdin")
    _add_json_flag(sp)
    sp.set_defaults(func=cmd_profile_agent_instructions)

    # page — page-level operations (create / edit / append / history / revert).
    # Subsumes the old `page create`; `page` stays as a deprecated alias
    # for one release per ADR-0005.
    page_parser = sub.add_parser("page", help="wiki page operations")
    page_sub = page_parser.add_subparsers(dest="page_command", required=True)

    sp = page_sub.add_parser(
        "create",
        help="explicitly create a wiki page (people / projects / topics / custom)",
        # The three input shapes and the never-auto-create-ancestors rule are ADR-0011.
        description=(
            "Three input shapes:\n"
            "  1. --slug 'projects/seaglass/competitors' — full typed slug; "
            "the parent slug must already exist.\n"
            "  2. --parent <slug or page_id> --title 'Competitors' — nested "
            "page, type inherits from the parent.\n"
            "  3. --type projects --title 'Seaglass' — new top-level page.\n\n"
            "Pages can also be created as a side effect of store_memory / "
            "store_document; use this command when you want to register a "
            "page without writing a memory yet."
        ),
    )
    sp.add_argument("--slug", help="full typed slug (e.g. 'projects/seaglass/competitors')")
    sp.add_argument("--parent", help="existing parent slug or page_id to nest under")
    sp.add_argument("--title", help="human-readable display title")
    sp.add_argument("--type", help=f"{_TYPE_HELP} — for a new top-level page")
    sp.add_argument("--identity-hint", help="distinguishing phrase, e.g. 'Linear PM'")
    _add_json_flag(sp)
    sp.set_defaults(func=cmd_page_create)

    sp = page_sub.add_parser(
        "edit",
        help="replace a page's body (or a single ## section)",
        description=(
            "Pass --section to scope the edit to one heading; omit it to "
            "replace the whole body. Pass --base-version if you've already "
            "read the current version; the CLI fetches it for you otherwise."
        ),
    )
    sp.add_argument("page", help="page name, path, or typed ID")
    sp.add_argument("--section", help="restrict the edit to this ## heading")
    sp.add_argument("--base-version", type=int, help="optimistic-concurrency token")
    grp = sp.add_mutually_exclusive_group()
    grp.add_argument("--content", help="new markdown body (use - for stdin)")
    grp.add_argument("--content-file", help="read body from a file")
    grp.add_argument("--stdin", action="store_true", help="read body from stdin")
    sp.add_argument(
        "--evidence",
        action="append",
        metavar="ID",
        help="memory_/document_ ID that justifies the edit; repeatable",
    )
    sp.add_argument("--edit-summary", help="short note for the audit trail")
    _add_json_flag(sp)
    sp.set_defaults(func=cmd_page_edit)

    sp = page_sub.add_parser(
        "append",
        help="add a new ## section to the end of a page",
        description=(
            "Additive — no base_version needed. Fails if a section with the "
            "same heading already exists."
        ),
    )
    sp.add_argument("page", help="page name, path, or typed ID")
    sp.add_argument("--section", required=True, help="heading for the new section")
    sp.add_argument(
        "--level",
        type=int,
        choices=[2, 3],
        default=2,
        help="heading level (default 2)",
    )
    grp = sp.add_mutually_exclusive_group()
    grp.add_argument("--content", help="new section body (use - for stdin)")
    grp.add_argument("--content-file", help="read body from a file")
    grp.add_argument("--stdin", action="store_true", help="read body from stdin")
    sp.add_argument("--evidence", action="append", metavar="ID")
    sp.add_argument("--edit-summary", help="short note for the audit trail")
    _add_json_flag(sp)
    sp.set_defaults(func=cmd_page_append)

    sp = page_sub.add_parser(
        "history",
        help="recent edits for a page (newest first)",
    )
    sp.add_argument("page", help="page name, path, or typed ID")
    sp.add_argument("--limit", type=int, default=20, help="max entries (default 20, cap 100)")
    _add_json_flag(sp)
    sp.set_defaults(func=cmd_page_history)

    sp = page_sub.add_parser(
        "revert",
        help="restore a page body to a prior version (from `page history`)",
    )
    sp.add_argument("page", help="page name, path, or typed ID")
    sp.add_argument("--to-version", type=int, required=True)
    sp.add_argument("--edit-summary", help="short note for the audit trail")
    _add_json_flag(sp)
    sp.set_defaults(func=cmd_page_revert)

    sp = page_sub.add_parser(
        "move",
        help="rename a page or move it under a different parent",
        description=(
            "Address surgery: pass the page and the full new typed slug "
            "(e.g. 'projects/atlas'). The type segment (first slug segment) is "
            "immutable; a nested target's parent slug must already exist. "
            "Sub-pages move with their parent automatically, the page ID never "
            "changes, and the old address keeps redirecting until a new page "
            "occupies it. Not for identity fixes (a memory that belongs on a "
            "different page, splits, merges) — use reconsolidate for those."
        ),
    )
    sp.add_argument("page", help="page name, path, or typed ID to move")
    sp.add_argument("to", help="full new typed slug, e.g. 'projects/atlas'")
    sp.add_argument("--title", help="new display title (optional)")
    sp.add_argument("--edit-summary", help="short note for the audit trail")
    _add_json_flag(sp)
    sp.set_defaults(func=cmd_page_move)

    # search (was get_context; renamed in ADR-0005, alias kept server-side)
    sp = sub.add_parser(
        "search",
        help="search and read memories, documents, and pages",
        description=(
            "Pass a name (e.g. 'Sarah Chen'), a typed ID (e.g. 'page_01HX...'), "
            "a wiki path ('projects/seaglass/competitors'), or a free-text query. "
            "The server auto-detects the format. Page hits include an outline "
            "block (parent, subpages, cross-links, see-also) for navigation."
        ),
    )
    sp.add_argument("query", help="name, typed ID, path, or free-text query")
    sp.add_argument(
        "--type",
        # Page types are library-defined (ADR-0024).
        help=(
            "restrict results: 'document' / 'memory' filter the evidence layer; "
            "any other value is a library-defined page type and filters by slug "
            "prefix (e.g. 'projects')"
        ),
    )
    sp.add_argument("--limit", type=int, default=10, help="max results (default 10)")
    sp.add_argument(
        "--include-private",
        action="store_true",
        help="include private-sensitivity content (only when the user asked for it)",
    )
    sp.add_argument(
        "--no-body",
        action="store_true",
        help="skeleton-only — drop the page body from page hits, keep the outline",
    )
    sp.add_argument(
        "--with",
        dest="with_",
        metavar="FIELDS",
        help=("comma-separated opt-in fields (page hits only): backlinks,recent_edits"),
    )
    _add_json_flag(sp)
    sp.set_defaults(func=cmd_search)

    # memory store
    mem = sub.add_parser("memory", help="memory operations")
    mem_sub = mem.add_subparsers(dest="memory_command", required=True)
    sp = mem_sub.add_parser(
        "store",
        help="persist an atomic memory (store_memory)",
        description=(
            "Wrap private bits in <private>...</private> in --content; the server "
            "forces sensitivity=private when those tags are present."
        ),
    )
    grp = sp.add_mutually_exclusive_group()
    grp.add_argument("--content", help="memory text (use '-' for stdin)")
    grp.add_argument("--stdin", action="store_true", help="read content from stdin")
    grp.add_argument("--file", metavar="PATH", help="read content from a file")
    sp.add_argument("--page", required=True, help="primary page name or typed ID")
    sp.add_argument("--type", help=f"{_TYPE_HELP} — required when creating a new page")
    sp.add_argument("--identity-hint", help="distinguishing phrase, e.g. 'Linear PM'")
    sp.add_argument(
        "--source-kind",
        choices=_MEMORY_SOURCE_KINDS,
        default="conversation",
        help="origin of the content (default: conversation)",
    )
    sp.add_argument("--source-ref", help="optional URL or path the content came from")
    sp.add_argument(
        "--sensitivity",
        choices=["normal", "sensitive", "private"],
        help="sensitivity level (private also auto-applied if <private> tags present)",
    )
    sp.add_argument("--confidence", type=float, help="0..1, default 1.0")
    sp.add_argument("--event-time", help="ISO-8601 timestamp of the observed fact")
    sp.add_argument(
        "--capture-context",
        metavar="NOTE",
        help=(
            "ambient context the bare content alone wouldn't carry — what "
            "was being discussed, why this is being captured. Server writes "
            "a sibling annotation memory linked to the primary."
        ),
    )
    _add_links(sp)
    _add_json_flag(sp)
    sp.set_defaults(func=cmd_memory_store)

    # document store
    doc = sub.add_parser("document", help="document operations")
    doc_sub = doc.add_subparsers(dest="document_command", required=True)
    sp = doc_sub.add_parser(
        "store",
        help="persist a longer document (store_document)",
        description="Triggers async extraction. Same <private> rules as store_memory.",
    )
    sp.add_argument("--title", help="document title (defaults to file stem if --file given)")
    grp = sp.add_mutually_exclusive_group()
    grp.add_argument("--content", help="document body (use '-' for stdin)")
    grp.add_argument("--stdin", action="store_true", help="read content from stdin")
    grp.add_argument("--file", metavar="PATH", help="read body from a file")
    sp.add_argument("--page", help="primary page name or typed ID")
    sp.add_argument("--type", help=f"{_TYPE_HELP} — required when creating a new page")
    sp.add_argument(
        "--content-type",
        choices=["text/markdown", "text/plain", "text/html"],
        default="text/markdown",
    )
    sp.add_argument(
        "--source-kind",
        choices=_DOCUMENT_SOURCE_KINDS,
        default="user_upload",
        help="origin of the content (default: user_upload)",
    )
    sp.add_argument("--source-ref", help="optional URL or path the content came from")
    sp.add_argument(
        "--sensitivity",
        choices=["normal", "sensitive", "private"],
    )
    sp.add_argument("--event-time", help="ISO-8601 timestamp")
    sp.add_argument(
        "--source-authored-at",
        help="ISO-8601: when the source file/page was originally authored.",
    )
    sp.add_argument(
        "--source-modified-at",
        help=(
            "ISO-8601: when the source file/page was last modified. "
            "Auto-filled from --file mtime if not explicit; pass "
            "--no-source-mtime to skip the auto-fill."
        ),
    )
    sp.add_argument(
        "--no-source-mtime",
        action="store_true",
        help="Suppress auto-capture of --source-modified-at from file mtime.",
    )
    sp.add_argument(
        "--capture-context",
        metavar="NOTE",
        help=(
            "ambient context — what the conversation was about when this "
            "was captured, why it was saved. Server writes an annotation "
            "memory and feeds it into extraction so derived memories are "
            "richer."
        ),
    )
    sp.add_argument(
        "--via-upload",
        action="store_true",
        help=(
            "POST the file via /v1/documents/upload instead of MCP. Requires --file. "
            "Cheaper for large bodies; same auth + provenance + dedup behavior."
        ),
    )
    extract_grp = sp.add_mutually_exclusive_group()
    extract_grp.add_argument(
        "--extract",
        dest="extract",
        action="store_const",
        const=True,
        help="explicitly enqueue server-side extraction (overrides cost-mode default)",
    )
    extract_grp.add_argument(
        "--no-extract",
        dest="extract",
        action="store_const",
        const=False,
        help=(
            "skip server-side extraction (the default in agent mode); "
            "agents that want to do their own extraction should pass this"
        ),
    )
    sp.set_defaults(extract=None)
    _add_links(sp)
    _add_json_flag(sp)
    sp.set_defaults(func=cmd_document_store)

    # annotate — post-hoc context attached to an existing document or memory.
    # Routes through store_memory with source_type="annotation".
    sp = sub.add_parser(
        "annotate",
        help="attach an annotation memory to a document or memory",
        description=(
            "Use when the user retroactively adds context to something already "
            "stored: 'remember, that doc was really about X' or 'the reason "
            "that decision mattered is Y'. The annotation participates in the "
            "wiki page synthesis like any other memory."
        ),
    )
    sp.add_argument(
        "target_id",
        help="document_01HX... or memory_01HX... — the thing being annotated",
    )
    grp = sp.add_mutually_exclusive_group()
    grp.add_argument("note", nargs="?", help="annotation text (use '-' for stdin)")
    grp.add_argument("--stdin", action="store_true", help="read note from stdin")
    sp.add_argument(
        "--page",
        required=True,
        help="page the annotation is about (usually the same page as the target)",
    )
    sp.add_argument(
        "--type",
        help=f"{_TYPE_HELP} — required when creating a new page",
    )
    sp.add_argument(
        "--sensitivity",
        choices=["normal", "sensitive", "private"],
    )
    _add_json_flag(sp)
    sp.set_defaults(func=cmd_annotate)

    # flag
    sp = sub.add_parser(
        "flag",
        help="flag a memory or document (flag_memory)",
    )
    sp.add_argument("target_id", help="typed ID, e.g. memory_01HX... or document_01HX...")
    sp.add_argument("--action", required=True, choices=_FLAG_ACTIONS)
    sp.add_argument("--reason", help="optional rationale (audit trail)")
    _add_json_flag(sp)
    sp.set_defaults(func=cmd_flag)

    # send-product-feedback — report a bug / request a feature for Seaglass itself.
    sp = sub.add_parser(
        "send-product-feedback",
        help="report a bug or request a feature for Seaglass itself",
        description=(
            "Feedback about Seaglass itself — the memory tool — NOT bugs in the "
            "user's own code or projects. Only --kind and a body are required; "
            "the server attaches who/which-agent/which-session automatically."
        ),
    )
    sp.add_argument("--kind", choices=("bug", "feature", "other"), default="bug")
    sp.add_argument("--body", help="feedback text (use - for stdin)")
    sp.add_argument("--file", help="read the body from a file")
    sp.add_argument("--stdin", action="store_true", help="read the body from stdin")
    sp.add_argument("--title", help="short summary (optional; derived from body if omitted)")
    sp.add_argument("--severity", choices=("critical", "high", "medium", "low"))
    sp.add_argument("--component", help="which part of Seaglass (mcp / web / cli / synthesis)")
    sp.add_argument("--tool-name", dest="tool_name", help="the Seaglass tool you were using")
    _add_json_flag(sp)
    sp.set_defaults(func=cmd_feedback)

    # reconsolidate
    sp = sub.add_parser(
        "reconsolidate",
        help="diagnose / repair page confusion (reconsolidate_memory)",
        description=(
            "Without --kind / --resolution-json this runs analysis mode and prints "
            "the diagnosis. Pass --kind {split,merge,reassign} (with --details-json) "
            "or a full --resolution-json to apply a resolution."
        ),
    )
    sp.add_argument("query", help="page name, typed ID, or natural-language description")
    sp.add_argument("--kind", choices=["split", "merge", "reassign"], help="apply-mode resolution")
    sp.add_argument("--details-json", help="resolution.details JSON, e.g. '{\"into\": [...]}'")
    sp.add_argument(
        "--resolution-json",
        help="full resolution object as JSON (overrides --kind / --details-json)",
    )
    _add_json_flag(sp)
    sp.set_defaults(func=cmd_reconsolidate)

    # install — write a per-client connector recipe + managed guidance block.
    sp = sub.add_parser(
        "install",
        help="write connector config + guidance for a client (codex / cursor)",
        description=(
            "Idempotently writes the Seaglass MCP connector config and a managed "
            "guidance block for a target client. By default the connector uses the "
            "`seaglass bridge` stdio transport (run `seaglass auth login` first). "
            "Re-running is a no-op when nothing changed."
        ),
    )
    sp.add_argument("client", choices=["codex", "cursor"], help="which client to configure")
    sp.add_argument(
        "--dir",
        default=None,
        help="project directory for project-scoped files (default: cwd)",
    )
    sp.add_argument(
        "--remote",
        action="store_true",
        help="emit the hosted remote-MCP variant (URL) instead of the stdio bridge",
    )
    sp.add_argument(
        "--codex-config",
        default=None,
        help="path to Codex config.toml (default: ~/.codex/config.toml)",
    )
    _add_json_flag(sp)
    sp.set_defaults(func=cmd_install)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        rc = args.func(args)
    except CliError as e:
        stderr(f"error: {e}")
        if e.data is not None:
            stderr(json.dumps(e.data, indent=2, default=str))
        sys.exit(e.exit_code)
    except KeyboardInterrupt:
        stderr("interrupted")
        sys.exit(130)
    # Passive update nudge: only for interactive humans (a TTY), never for the
    # stdio bridge or in CI/pipes, and suppressible via SEAGLASS_NO_UPDATE_CHECK.
    # The bridge/plugin path gets its nudge from the server's initialize response.
    if (
        sys.stderr.isatty()
        and not os.environ.get("SEAGLASS_NO_UPDATE_CHECK")
        and getattr(args, "command", None) not in ("bridge", "mcp", "update")
    ):
        maybe_notify_update(load_config())
    sys.exit(rc if isinstance(rc, int) else EXIT_OK)

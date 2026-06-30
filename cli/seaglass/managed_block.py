"""Managed-block compiler for comment-bearing instruction/config files.

A Seaglass managed block is one sentinel-delimited region Seaglass can find,
update in place, and remove cleanly across repeated `seaglass install` runs —
without touching a byte outside it. The opening sentinel carries a format
version and a SHA-256 of the inner body, so an `upsert` is a true no-op when the
existing block already matches the freshly-rendered body.

Two comment styles are supported (the sentinel matches the target file):
  * ``html`` — ``<!-- ... -->`` for markdown (AGENTS.md / CLAUDE.md / .cursor/rules)
  * ``hash`` — ``# ...``        for TOML (Codex config.toml)

JSON configs (.cursor/mcp.json) are NOT managed here — they have no comments and
are merged structurally by the caller. This module is pure text manipulation
(client-side file editing), with no I/O.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

FORMAT_VERSION = "v1"
_LABEL = "SEAGLASS MANAGED BLOCK"


@dataclass(frozen=True)
class CommentStyle:
    open: str
    close: str


HTML = CommentStyle(open="<!-- ", close=" -->")
HASH = CommentStyle(open="# ", close="")


def _body_hash(body: str) -> str:
    return hashlib.sha256(body.strip().encode("utf-8")).hexdigest()[:16]


def _begin(style: CommentStyle, body: str) -> str:
    return f"{style.open}BEGIN {_LABEL} {FORMAT_VERSION} sha256:{_body_hash(body)}{style.close}"


def _end(style: CommentStyle) -> str:
    return f"{style.open}END {_LABEL}{style.close}"


def render_block(body: str, *, style: CommentStyle = HTML) -> str:
    """Render the full sentinel-delimited block for ``body``."""
    inner = body.strip("\n")
    return f"{_begin(style, inner)}\n{inner}\n{_end(style)}"


def find_block(text: str, *, style: CommentStyle = HTML) -> tuple[int, int] | None:
    """Return (start, end) character span of the block, or ``None`` if absent.

    A second sentinel pair is ignored — the first region wins.
    """
    begin_marker = f"{style.open}BEGIN {_LABEL}"
    end_marker = _end(style)
    start = text.find(begin_marker)
    if start == -1:
        return None
    end = text.find(end_marker, start)
    if end == -1:
        return None
    return start, end + len(end_marker)


def upsert(text: str, body: str, *, style: CommentStyle = HTML) -> tuple[str, bool]:
    """Insert or replace the managed block. Returns (new_text, changed).

    No existing block → append one (separated by a blank line). Existing block →
    replace just the region. If the existing region already equals the rendered
    block (body hash matches), it's a no-op and ``changed`` is ``False``.
    """
    block = render_block(body, style=style)
    loc = find_block(text, style=style)
    if loc is not None:
        start, end = loc
        if text[start:end] == block:
            return text, False
        return text[:start] + block + text[end:], True
    if text.strip() == "":
        return block + "\n", True
    return text.rstrip("\n") + "\n\n" + block + "\n", True


def remove(text: str, *, style: CommentStyle = HTML) -> tuple[str, bool]:
    """Delete the managed block (and its separating blank line). Returns (new_text, changed)."""
    loc = find_block(text, style=style)
    if loc is None:
        return text, False
    start, end = loc
    before = text[:start].rstrip("\n")
    after = text[end:].lstrip("\n")
    new = f"{before}\n\n{after}" if before and after else before or after
    new = new.rstrip("\n")
    return (new + "\n" if new else ""), True

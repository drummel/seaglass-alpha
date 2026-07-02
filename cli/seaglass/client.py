"""Minimal MCP JSON-RPC client built on stdlib urllib.

Keeps cold-start under ~150ms and avoids a dependency footprint. The CLI
talks to the same `/mcp` endpoint as Claude Code, Claude Desktop, et al.,
which means the server-side auth, session, and tool-handler code paths are
identical.

A small multipart helper (`upload_document`) lives here too — it talks to
the bearer-authenticated REST endpoint at ``POST /v1/documents/upload``,
used by ``seaglass document store --file <path> --via-upload`` to avoid round-
tripping the document body through JSON-RPC.
"""

from __future__ import annotations

import contextlib
import json
import mimetypes
import os
import secrets
import sys
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from seaglass import __version__

DEFAULT_URL = "https://seaglass-api-stg.onrender.com"

# Single source for the User-Agent header so every request advertises the
# real package version (not a hardcoded literal that drifts on release).
USER_AGENT = f"seaglass-cli/{__version__}"

# Transient-failure retry for the stdio bridge: a flaky connection (laptop
# sleep/wake, VPN flap) shouldn't surface as a hard error on the first miss.
# Only connection-level URLErrors are retried — an HTTP status (incl. 401) is a
# definitive server answer and is never retried.
BRIDGE_RETRY_ATTEMPTS = 2
BRIDGE_RETRY_DELAY_SECONDS = 0.2
SESSION_FILE = Path.home() / ".cache" / "seaglass" / "session"
# Latest-version cache for the passive "you're out of date" nudge. Refreshed at
# most once per TTL so the hot command path makes no network call on most runs.
VERSION_CACHE_FILE = Path.home() / ".cache" / "seaglass" / "version_check.json"
VERSION_CHECK_TTL_SECONDS = 24 * 60 * 60
# Tokens minted via `seaglass auth login` are persisted here so subsequent commands
# can pick them up without env vars. SEAGLASS_TOKEN still wins when set.
TOKEN_FILE = Path.home() / ".config" / "seaglass" / "token"
# Sidecar metadata for the persisted token: where it came from ("login" or
# "redeem") and, for redeem-minted tokens, when it expires if unused. Purely
# informational (`seaglass auth status`); a missing or stale file is harmless.
TOKEN_META_FILE = Path.home() / ".config" / "seaglass" / "token_meta.json"

# One shared 401 recovery string: the agent-readable path first (works in a
# headless container over the existing MCP connection), the browser path second.
AUTH_RECOVERY_MESSAGE = (
    "Authentication failed (401). To re-authenticate without a browser, call the "
    "Seaglass cli_handoff tool, then run `seaglass auth redeem <code>` with the "
    "code it returns. On a machine with a browser, run `seaglass auth login` "
    "instead (or check SEAGLASS_TOKEN if you set it manually)."
)
# Base-URL pin written by `seaglass auth login --url`. Sits one layer below the
# SEAGLASS_URL env var and one above the baked DEFAULT_URL — see resolve_base_url.
CONFIG_FILE = Path.home() / ".config" / "seaglass" / "config.json"


# Exit codes are referenced from SKILL.md — keep these stable.
EXIT_OK = 0
EXIT_GENERIC = 1
EXIT_NOT_FOUND = 3
EXIT_RESOLUTION_REQUIRED = 4
EXIT_AUTH = 5

# Mirror of the server's MCP error-code → exit-code mapping.
# Codes without an entry fall through to EXIT_GENERIC. That is deliberate for the
# rich-data page errors — version-conflict (-32030), section not-found/exists
# (-32031/-32032), and write-forbidden (-32034) all carry their detail in the
# error `data`, so a script branches on the payload, not the exit code.
_RPC_TO_EXIT = {
    -32010: EXIT_RESOLUTION_REQUIRED,  # ERR_RESOLUTION_REQUIRED
    -32011: EXIT_GENERIC,  # ERR_TYPE_REQUIRED
    -32012: EXIT_GENERIC,  # ERR_INVALID_TYPED_ID
    -32021: EXIT_AUTH,  # ERR_TOKEN_REVOKED
    -32033: EXIT_NOT_FOUND,  # ERR_PAGE_NOT_FOUND
    -32040: EXIT_NOT_FOUND,  # ERR_NOT_FOUND
}


@dataclass(frozen=True)
class Config:
    base_url: str
    token: str | None
    client_session_id: str

    @property
    def mcp_url(self) -> str:
        return self.base_url.rstrip("/") + "/mcp"


def _read_token_file() -> str | None:
    """Read the persisted token from ~/.config/seaglass/token, or None."""
    try:
        value = TOKEN_FILE.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    except OSError:
        return None
    return value or None


def write_token_file(token: str) -> None:
    """Persist a token from `seaglass auth login`. Writes mode 0600 if possible."""
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(token + "\n", encoding="utf-8")
    with contextlib.suppress(OSError):
        TOKEN_FILE.chmod(0o600)


def clear_token_file() -> bool:
    """Remove the persisted token (and its metadata sidecar), if any.

    Returns True iff a token was removed.
    """
    with contextlib.suppress(OSError):
        TOKEN_META_FILE.unlink(missing_ok=True)
    try:
        TOKEN_FILE.unlink()
        return True
    except FileNotFoundError:
        return False
    except OSError:
        return False


def write_token_meta(*, source: str, expires_at: str | None = None) -> None:
    """Persist informational metadata for the stored token. Best-effort."""
    try:
        TOKEN_META_FILE.parent.mkdir(parents=True, exist_ok=True)
        data: dict[str, Any] = {"source": source}
        if expires_at:
            data["expires_at"] = expires_at
        TOKEN_META_FILE.write_text(json.dumps(data) + "\n", encoding="utf-8")
        with contextlib.suppress(OSError):
            TOKEN_META_FILE.chmod(0o600)
    except OSError:
        pass


def read_token_meta() -> dict[str, Any]:
    """Read the token metadata sidecar. Missing/corrupt → empty dict."""
    try:
        data = json.loads(TOKEN_META_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _read_config_url() -> str | None:
    """Read the pinned base URL from ~/.config/seaglass/config.json, or None.

    The file is written by `seaglass auth login --url <url>`. A missing file,
    unreadable file, malformed JSON, or absent/blank ``url`` key all yield None
    so the caller falls through to the baked default rather than erroring.
    """
    try:
        raw = CONFIG_FILE.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return None
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    url = data.get("url")
    if not isinstance(url, str):
        return None
    url = url.strip()
    return url or None


def write_config_url(url: str) -> None:
    """Persist a base-URL pin from `seaglass auth login --url`. Mode 0600 if possible.

    Merges into any existing config.json so unrelated keys survive a re-pin.
    """
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, Any] = {}
    try:
        existing = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        if isinstance(existing, dict):
            data = existing
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        data = {}
    data["url"] = url.strip()
    CONFIG_FILE.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    with contextlib.suppress(OSError):
        CONFIG_FILE.chmod(0o600)


def resolve_base_url() -> tuple[str, str]:
    """Resolve the API base URL through the layered cascade. Returns ``(url, source)``.

    Precedence, most-specific first:
      1. ``SEAGLASS_URL`` (env)              → source ``"env"``
      2. ``~/.config/seaglass/config.json``  → source ``"config"`` (set by ``auth login --url``)
      3. :data:`DEFAULT_URL` (baked)         → source ``"default"``

    Whitespace is stripped so a trailing newline (from a file or copy-paste)
    doesn't reach the urllib header layer. Shared by :func:`load_config` and
    ``install.py`` so every surface resolves the URL the same way.
    """
    raw_url = os.environ.get("SEAGLASS_URL")
    env_url = raw_url.strip() if raw_url else ""
    if env_url:
        return env_url, "env"
    pinned = _read_config_url()
    if pinned:
        return pinned, "config"
    return DEFAULT_URL, "default"


def load_config() -> Config:
    """Resolve config from env vars + token file. The MCP plugin uses the same names.

    URL precedence: SEAGLASS_URL (env) > ~/.config/seaglass/config.json (pin) >
    DEFAULT_URL — see :func:`resolve_base_url`. Token precedence: SEAGLASS_TOKEN
    (env) > ~/.config/seaglass/token (file). Both files are populated by
    `seaglass auth login`, which is why we don't ask the user to copy-paste
    tokens or export an env var any more.
    """
    base_url, _url_source = resolve_base_url()
    # Strip whitespace so a trailing newline (common when sourcing the token
    # from a file or copy-pasting) doesn't fail at the urllib header layer.
    raw_token = os.environ.get("SEAGLASS_TOKEN")
    token = raw_token.strip() if raw_token else None
    if token == "":
        token = None
    if token is None:
        token = _read_token_file()
    # A stable client_session_id per shell pid keeps audit trails coherent
    # without leaking IDs across users.
    csid = os.environ.get("SEAGLASS_CLIENT_SESSION_ID") or f"seaglass-cli-{os.getpid()}"
    return Config(base_url=base_url, token=token, client_session_id=csid)


def _read_session_id() -> str | None:
    try:
        return SESSION_FILE.read_text(encoding="utf-8").strip() or None
    except FileNotFoundError:
        return None
    except OSError:
        return None


def _write_session_id(value: str) -> None:
    try:
        SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
        SESSION_FILE.write_text(value, encoding="utf-8")
    except OSError:
        # Caching the session id is best-effort; a read-only homedir is fine.
        pass


class CliError(Exception):
    """Surface-level error raised to main() with a target exit code."""

    def __init__(self, message: str, exit_code: int = EXIT_GENERIC, data: Any = None):
        super().__init__(message)
        self.exit_code = exit_code
        self.data = data


def rpc_call(
    cfg: Config,
    method: str,
    params: dict[str, Any] | None = None,
    *,
    require_auth: bool = True,
    timeout: float = 30.0,
) -> Any:
    """Issue one JSON-RPC POST and return the `result` value.

    Raises `CliError` on transport, auth, or RPC failure.
    """
    if require_auth and not cfg.token:
        raise CliError(
            "No token configured. Run `seaglass auth login`, or set SEAGLASS_TOKEN.",
            EXIT_AUTH,
        )

    payload = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": method,
        "params": params or {},
    }
    body = json.dumps(payload).encode("utf-8")

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-Seaglass-Client-Session": cfg.client_session_id,
        "User-Agent": USER_AGENT,
    }
    if cfg.token:
        headers["Authorization"] = f"Bearer {cfg.token}"
    if (sid := _read_session_id()) is not None:
        headers["Mcp-Session-Id"] = sid

    req = urllib.request.Request(cfg.mcp_url, data=body, headers=headers, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            new_sid = resp.headers.get("Mcp-Session-Id")
            if new_sid:
                _write_session_id(new_sid)
            content_type = resp.headers.get("Content-Type") or ""
    except urllib.error.HTTPError as e:
        body_text = ""
        with contextlib.suppress(Exception):
            body_text = e.read().decode("utf-8", errors="replace")
        if e.code == 401:
            raise CliError(AUTH_RECOVERY_MESSAGE, EXIT_AUTH) from e
        raise CliError(
            f"HTTP {e.code} from {cfg.mcp_url}: {body_text or e.reason}",
            EXIT_GENERIC,
        ) from e
    except urllib.error.URLError as e:
        raise CliError(
            f"Could not reach {cfg.mcp_url}: {e.reason}. Is the API running?",
            EXIT_GENERIC,
        ) from e

    if not raw:
        # 204 No Content (notifications) — nothing to decode.
        return None

    if "json" not in content_type:
        raise CliError(f"Unexpected content-type {content_type!r}: {raw[:200]!r}", EXIT_GENERIC)

    try:
        envelope = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as e:
        raise CliError(f"Could not parse JSON-RPC response: {e}", EXIT_GENERIC) from e

    if "error" in envelope:
        err = envelope["error"]
        code = int(err.get("code", -32000))
        message = err.get("message") or "RPC error"
        data = err.get("data")
        exit_code = _RPC_TO_EXIT.get(code, EXIT_GENERIC)
        raise CliError(message, exit_code, data=data)

    return envelope.get("result")


def call_tool(cfg: Config, name: str, arguments: dict[str, Any]) -> Any:
    """Run an MCP tool and return its decoded JSON result.

    The transport wraps tool output in `{"content":[{"type":"text","text":<json>}]}`;
    we unwrap that here so callers see the raw service-layer dict.
    """
    result = rpc_call(cfg, "tools/call", {"name": name, "arguments": arguments})
    if not isinstance(result, dict):
        return result
    content = result.get("content") or []
    if not content:
        return None
    first = content[0]
    text = first.get("text") if isinstance(first, dict) else None
    if not isinstance(text, str):
        return result
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Tools may return verbatim strings via the `_text` sentinel.
        return text


def initialize(cfg: Config) -> dict[str, Any]:
    """Send the MCP `initialize` handshake — useful for `seaglass whoami`."""
    params = {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "seaglass-cli", "version": __version__},
    }
    result = rpc_call(cfg, "initialize", params)
    return result if isinstance(result, dict) else {}


def list_tools(cfg: Config) -> list[dict[str, Any]]:
    result = rpc_call(cfg, "tools/list")
    if isinstance(result, dict):
        tools = result.get("tools")
        if isinstance(tools, list):
            return tools
    return []


def stderr(msg: str) -> None:
    print(msg, file=sys.stderr)


# ----- version / update check ----------------------------------------------
#
# The CLI runs out of process per invocation, so the once-per-session nudge the
# MCP server emits on `initialize` doesn't fit the direct-CLI path. Instead we
# cache the latest version (refreshed at most once a day) and compare it to our
# own on every command — printing to stderr, the channel a human actually reads.
# `clientInfo.version` carries no authz weight, and neither does this.


def _parse_version(value: str) -> tuple[int, ...] | None:
    """Parse a dotted-integer version, or None if it isn't one (mirrors the server)."""
    out: list[int] = []
    for part in value.strip().split("."):
        if not part.isdigit():
            return None
        out.append(int(part))
    return tuple(out) if out else None


def is_outdated(current: str, latest: str) -> bool:
    """True iff both parse cleanly and `current` is strictly behind `latest`."""
    cur = _parse_version(current)
    new = _parse_version(latest)
    if cur is None or new is None:
        return False
    width = max(len(cur), len(new))
    return cur + (0,) * (width - len(cur)) < new + (0,) * (width - len(new))


def fetch_latest_version(cfg: Config, *, timeout: float = 2.0) -> str | None:
    """GET {base_url}/version and return the advertised version string, or None.

    Unauthenticated and best-effort: any transport or decode failure returns
    None so the caller can stay quiet rather than surface a checking error.
    """
    url = cfg.base_url.rstrip("/") + "/version"
    req = urllib.request.Request(url, headers={"Accept": "application/json"}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except (urllib.error.URLError, OSError):
        return None
    try:
        data = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    value = data.get("version") if isinstance(data, dict) else None
    return value if isinstance(value, str) else None


def _read_version_cache() -> tuple[str | None, float]:
    """Return (cached latest version, checked-at epoch). Missing/corrupt → (None, 0)."""
    try:
        data = json.loads(VERSION_CACHE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None, 0.0
    if not isinstance(data, dict):
        return None, 0.0
    latest = data.get("latest")
    checked = data.get("checked_at")
    return (
        latest if isinstance(latest, str) else None,
        float(checked) if isinstance(checked, (int, float)) else 0.0,
    )


def _write_version_cache(latest: str) -> None:
    """Persist the latest known version + timestamp. Best-effort (read-only home is fine)."""
    try:
        VERSION_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        VERSION_CACHE_FILE.write_text(
            json.dumps({"latest": latest, "checked_at": time.time()}),
            encoding="utf-8",
        )
    except OSError:
        pass


def maybe_notify_update(cfg: Config, *, current: str = __version__) -> str | None:
    """Print a stderr nudge if a newer version exists; return the message or None.

    Uses the day-cached latest version, refreshing it (one network call) only when
    the cache is missing or stale. Silent when current is up to date or the latest
    can't be determined.
    """
    latest, checked_at = _read_version_cache()
    if latest is None or (time.time() - checked_at) > VERSION_CHECK_TTL_SECONDS:
        fetched = fetch_latest_version(cfg)
        if fetched is not None:
            latest = fetched
            _write_version_cache(latest)
    if latest is None or not is_outdated(current, latest):
        return None
    message = (
        f"A new Seaglass release is available (v{latest}; you have v{current}).\n"
        "  Update: pipx upgrade seaglass-cli   (or: uv tool upgrade seaglass-cli)"
    )
    stderr(message)
    return message


# ----- MCP resource read ---------------------------------------------------


def read_resource(cfg: Config, uri: str) -> str:
    """Read an MCP resource (e.g. ``seaglass://profile``) and return its text.

    Resources are typed (mime-type-aware). For Seaglass's profile resource we
    register it as ``text/markdown`` and return the markdown body verbatim.
    """
    result = rpc_call(cfg, "resources/read", {"uri": uri})
    if not isinstance(result, dict):
        return ""
    contents = result.get("contents") or []
    if not contents:
        return ""
    first = contents[0]
    text = first.get("text") if isinstance(first, dict) else None
    return text if isinstance(text, str) else ""


# ----- admin REST helpers --------------------------------------------------


def _admin_request(
    cfg: Config,
    method: str,
    path: str,
    *,
    body: dict[str, Any] | None = None,
    timeout: float = 30.0,
) -> Any:
    """Hit a bearer-authenticated REST endpoint and unwrap the envelope.

    Used for the resource-addressed profile reads under
    ``/v1/accounts/{handle}/profile`` (the session-scoped ``/v1/admin/profile``
    twin was retired and deleted in #224). Those GETs are bearer-ok; the PATCH
    twins are cookie-only, so a bearer profile write fails closed with a 404.
    Returns the unwrapped envelope ``data`` field or raises ``CliError``.
    """
    if not cfg.token:
        raise CliError(
            "SEAGLASS_TOKEN is not set. Export it (or run `seaglass whoami` for diagnostics).",
            EXIT_AUTH,
        )
    url = cfg.base_url.rstrip("/") + path
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {cfg.token}",
        "User-Agent": USER_AGENT,
    }
    data: bytes | None = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode("utf-8")

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as e:
        body_text = ""
        with contextlib.suppress(Exception):
            body_text = e.read().decode("utf-8", errors="replace")
        if e.code == 401:
            raise CliError(AUTH_RECOVERY_MESSAGE, EXIT_AUTH) from e
        if e.code == 404:
            raise CliError(
                f"Not found: {path}. {body_text}".rstrip(),
                EXIT_NOT_FOUND,
            ) from e
        raise CliError(f"HTTP {e.code} from {url}: {body_text or e.reason}", EXIT_GENERIC) from e
    except urllib.error.URLError as e:
        raise CliError(
            f"Could not reach {url}: {e.reason}. Is the API running?", EXIT_GENERIC
        ) from e

    if not raw:
        return None
    try:
        envelope = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as e:
        raise CliError(f"Could not parse response: {e}", EXIT_GENERIC) from e
    if isinstance(envelope, dict) and envelope.get("success") is False:
        raise CliError(envelope.get("error") or "request failed", EXIT_GENERIC)
    if isinstance(envelope, dict) and "data" in envelope:
        return envelope["data"]
    return envelope


# ----- account-handle resolution (for addressed /v1/accounts/{handle}/...) --

# The resource-addressed profile routes are keyed on the account handle, which
# the bearer token alone doesn't carry. We fetch it once from `/v1/me` and cache
# it per (base_url, token) for the life of the process so the common two-call
# command (resolve an agent by name, then read/patch it) makes a single lookup.
_HANDLE_CACHE: dict[tuple[str, str | None], str] = {}


def _select_handle(me: dict[str, Any]) -> str | None:
    """Pick the account handle from a ``/v1/me`` payload.

    Prefers the personal-kind account (the user's own tenant — the natural home
    for profile state), then falls back to the first account, then the top-level
    ``handle`` (the personal-account handle). Returns ``None`` only when
    the payload carries no account at all.
    """
    accounts = me.get("accounts") or []
    personal = next((a for a in accounts if a.get("kind") == "personal"), None)
    if personal and personal.get("handle"):
        return personal["handle"]
    for a in accounts:
        if a.get("handle"):
            return a["handle"]
    top = me.get("handle")
    return top or None


def resolve_handle(cfg: Config) -> str:
    """The account handle to address the caller's profile under.

    ``SEAGLASS_ACCOUNT`` (env) overrides — an explicit account selection that
    skips the lookup entirely, matching the env-var config idiom the CLI already
    uses (``SEAGLASS_URL`` / ``SEAGLASS_TOKEN``). Otherwise we GET ``/v1/me`` once
    and select the personal-kind account (else the first), caching the result.
    Raises ``CliError`` when no account can be resolved.
    """
    override = os.environ.get("SEAGLASS_ACCOUNT")
    if override and override.strip():
        return override.strip()
    key = (cfg.base_url, cfg.token)
    cached = _HANDLE_CACHE.get(key)
    if cached is not None:
        return cached
    me = _admin_request(cfg, "GET", "/v1/me")
    handle = _select_handle(me) if isinstance(me, dict) else None
    if not handle:
        raise CliError(
            "Could not resolve an account handle from /v1/me. "
            "Set SEAGLASS_ACCOUNT to the account handle explicitly.",
            EXIT_GENERIC,
        )
    _HANDLE_CACHE[key] = handle
    return handle


# ----- raw JSON-RPC proxy (for `seaglass bridge` stdio transport) ----------


def forward_frame(cfg: Config, frame_bytes: bytes, *, timeout: float = 60.0) -> bytes | None:
    """POST a raw JSON-RPC frame to `{base_url}/mcp` and return the raw response.

    Used by the stdio shim — the frame is whatever bytes came in on stdin, sent
    verbatim so the upstream MCP server can interpret method/params/id without
    any reframing on our part. Returns `None` for 204 (notifications).

    The cached `Mcp-Session-Id` round-trip is preserved so the upstream
    sessions table can keep the same audit trail across a stdio Claude
    Code / Desktop session.

    Raises `CliError` on transport failure, 401, or unparseable responses.
    The shim is responsible for serialising those into JSON-RPC errors back
    to the upstream client.
    """
    if not cfg.token:
        raise CliError(
            "No token configured. Run `seaglass auth login`, or set SEAGLASS_TOKEN.",
            EXIT_AUTH,
        )

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Bearer {cfg.token}",
        "X-Seaglass-Client-Session": cfg.client_session_id,
        "User-Agent": USER_AGENT,
    }
    if (sid := _read_session_id()) is not None:
        headers["Mcp-Session-Id"] = sid

    req = urllib.request.Request(cfg.mcp_url, data=frame_bytes, headers=headers, method="POST")
    attempt = 0
    while True:
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                new_sid = resp.headers.get("Mcp-Session-Id")
                if new_sid:
                    _write_session_id(new_sid)
            return raw or None
        except urllib.error.HTTPError as e:
            body_text = ""
            with contextlib.suppress(Exception):
                body_text = e.read().decode("utf-8", errors="replace")
            if e.code == 401:
                raise CliError(AUTH_RECOVERY_MESSAGE, EXIT_AUTH) from e
            raise CliError(
                f"HTTP {e.code} from {cfg.mcp_url}: {body_text or e.reason}",
                EXIT_GENERIC,
            ) from e
        except urllib.error.URLError as e:
            attempt += 1
            if attempt < BRIDGE_RETRY_ATTEMPTS:
                # Transient connection blip — back off briefly and retry rather
                # than surfacing an error frame the upstream client must handle.
                time.sleep(BRIDGE_RETRY_DELAY_SECONDS)
                continue
            raise CliError(
                f"Could not reach {cfg.mcp_url}: {e.reason}. Is the API running?",
                EXIT_GENERIC,
            ) from e


# ----- multipart upload (for `seaglass document store --via-upload`) ------


def _build_multipart(
    *,
    file_name: str,
    file_bytes: bytes,
    file_mime: str,
    fields: dict[str, str],
) -> tuple[bytes, str]:
    """Build a multipart/form-data body. Returns (body_bytes, content_type)."""
    boundary = "----seaglass" + secrets.token_hex(16)
    boundary_bytes = boundary.encode("ascii")
    parts: list[bytes] = []
    for name, value in fields.items():
        if value is None:
            continue
        parts.append(b"--" + boundary_bytes + b"\r\n")
        parts.append((f'Content-Disposition: form-data; name="{name}"\r\n\r\n').encode())
        parts.append(value.encode("utf-8"))
        parts.append(b"\r\n")
    parts.append(b"--" + boundary_bytes + b"\r\n")
    parts.append(
        (
            f'Content-Disposition: form-data; name="file"; filename="{file_name}"\r\n'
            f"Content-Type: {file_mime}\r\n\r\n"
        ).encode()
    )
    parts.append(file_bytes)
    parts.append(b"\r\n--" + boundary_bytes + b"--\r\n")
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def upload_document(
    cfg: Config,
    *,
    file_path: Path,
    title: str | None = None,
    primary_page: str | None = None,
    primary_page_type: str | None = None,
    content_type: str | None = None,
    source_kind: str = "user_upload",
    source_ref: str | None = None,
    sensitivity: str | None = None,
    event_time: str | None = None,
    source_authored_at: str | None = None,
    source_modified_at: str | None = None,
    links: dict[str, list[str]] | None = None,
    timeout: float = 60.0,
) -> dict[str, Any]:
    """POST a file to the upload-by-reference endpoint and return the JSON result.

    Same auth + provenance handling as MCP. The response shape mirrors
    `store_document`: ``{document_id, primary_page_id, extraction_queued,
    deduplicated, ...}``.
    """
    if not cfg.token:
        raise CliError(
            "No token configured. Run `seaglass auth login`, or set SEAGLASS_TOKEN.",
            EXIT_AUTH,
        )

    file_bytes = file_path.read_bytes()
    file_mime = content_type or mimetypes.guess_type(file_path.name)[0] or "text/markdown"
    fields: dict[str, str] = {"source_kind": source_kind}
    if title is not None:
        fields["title"] = title
    if primary_page is not None:
        fields["primary_page"] = primary_page
    if primary_page_type is not None:
        fields["primary_page_type"] = primary_page_type
    if content_type is not None:
        fields["content_type"] = content_type
    if source_ref is not None:
        fields["source_ref"] = source_ref
    if sensitivity is not None:
        fields["sensitivity"] = sensitivity
    if event_time is not None:
        fields["event_time"] = event_time
    if source_authored_at is not None:
        fields["source_authored_at"] = source_authored_at
    if source_modified_at is not None:
        fields["source_modified_at"] = source_modified_at
    if links:
        fields["links"] = json.dumps(links)

    body, mp_content_type = _build_multipart(
        file_name=file_path.name,
        file_bytes=file_bytes,
        file_mime=file_mime,
        fields=fields,
    )

    url = cfg.base_url.rstrip("/") + "/v1/documents/upload"
    headers = {
        "Content-Type": mp_content_type,
        "Accept": "application/json",
        "Authorization": f"Bearer {cfg.token}",
        "X-Seaglass-Client-Session": cfg.client_session_id,
        "User-Agent": USER_AGENT,
    }
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as e:
        body_text = ""
        with contextlib.suppress(Exception):
            body_text = e.read().decode("utf-8", errors="replace")
        if e.code == 401:
            raise CliError(AUTH_RECOVERY_MESSAGE, EXIT_AUTH) from e
        if e.code == 409:
            # Resolution-required — surface the same exit code MCP uses.
            try:
                data = json.loads(body_text).get("detail")
            except (json.JSONDecodeError, AttributeError):
                data = body_text
            raise CliError(
                "ambiguous page reference — clarify which",
                EXIT_RESOLUTION_REQUIRED,
                data=data,
            ) from e
        raise CliError(f"HTTP {e.code} from {url}: {body_text or e.reason}", EXIT_GENERIC) from e
    except urllib.error.URLError as e:
        raise CliError(
            f"Could not reach {url}: {e.reason}. Is the API running?",
            EXIT_GENERIC,
        ) from e

    try:
        return json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as e:
        raise CliError(f"Could not parse upload response: {e}", EXIT_GENERIC) from e


# ----- session lifecycle ---------------------------------------------------


def end_session(cfg: Config, *, client_session_id: str, timeout: float = 30.0) -> dict[str, Any]:
    """Hit ``POST /v1/sessions/end`` so the API can flip ``ended_at``.

    Returns the decoded body, typically ``{"ended": bool}``. Raises
    ``CliError`` on auth or transport failure; "no matching session" is a
    successful 200 with ``ended=false``, not an error.
    """
    if not cfg.token:
        raise CliError(
            "No token configured. Run `seaglass auth login`, or set SEAGLASS_TOKEN.",
            EXIT_AUTH,
        )
    url = cfg.base_url.rstrip("/") + "/v1/sessions/end"
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Bearer {cfg.token}",
        "User-Agent": USER_AGENT,
    }
    body = json.dumps({"client_session_id": client_session_id}).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as e:
        body_text = ""
        with contextlib.suppress(Exception):
            body_text = e.read().decode("utf-8", errors="replace")
        if e.code == 401:
            raise CliError(AUTH_RECOVERY_MESSAGE, EXIT_AUTH) from e
        raise CliError(f"HTTP {e.code} from {url}: {body_text or e.reason}", EXIT_GENERIC) from e
    except urllib.error.URLError as e:
        raise CliError(
            f"Could not reach {url}: {e.reason}. Is the API running?",
            EXIT_GENERIC,
        ) from e

    try:
        payload = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as e:
        raise CliError(f"Could not parse response: {e}", EXIT_GENERIC) from e
    return payload if isinstance(payload, dict) else {}


# ----- device-link auth ----------------------------------------------------


def _bearer_json(
    cfg: Config,
    path: str,
    payload: dict[str, Any] | None,
    *,
    method: str = "POST",
    timeout: float = 30.0,
) -> tuple[int, dict[str, Any]]:
    """Bearer-authenticated JSON request returning ``(status, decoded_body)``.

    Unlike ``_post_json`` this surfaces expected non-2xx statuses (the
    transcript append protocol speaks in 409/413) instead of
    raising, so callers can reconcile. Transport failures still raise.
    """
    if not cfg.token:
        raise CliError(
            "No token configured. Run `seaglass auth login`, or set SEAGLASS_TOKEN.",
            EXIT_AUTH,
        )
    url = cfg.base_url.rstrip("/") + path
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Bearer {cfg.token}",
        "User-Agent": USER_AGENT,
    }
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            status = resp.status
    except urllib.error.HTTPError as e:
        if e.code in (409, 413):
            with contextlib.suppress(Exception):
                return e.code, json.loads(e.read().decode("utf-8", errors="replace"))
            return e.code, {}
        body_text = ""
        with contextlib.suppress(Exception):
            body_text = e.read().decode("utf-8", errors="replace")
        raise CliError(f"HTTP {e.code} from {url}: {body_text or e.reason}", EXIT_GENERIC) from e
    except urllib.error.URLError as e:
        raise CliError(
            f"Could not reach {url}: {e.reason}. Is the API running?",
            EXIT_GENERIC,
        ) from e
    try:
        return status, json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as e:
        raise CliError(f"Could not parse response: {e}", EXIT_GENERIC) from e


def transcript_append(
    cfg: Config,
    *,
    client_session_id: str,
    byte_offset: int,
    content: str,
    client_format: str = "claude_code_jsonl",
    timeout: float = 30.0,
) -> tuple[int, dict[str, Any]]:
    """``POST /v1/sessions/transcript/append`` — returns ``(status, body)``.

    200 carries the confirmed counters; 409 carries the server's
    ``byte_count`` for reconciliation; 413 means the cap was hit.
    """
    return _bearer_json(
        cfg,
        "/v1/sessions/transcript/append",
        {
            "client_session_id": client_session_id,
            "byte_offset": byte_offset,
            "content": content,
            "format": client_format,
        },
        timeout=timeout,
    )


def transcript_finalize(
    cfg: Config, *, client_session_id: str, reason: str = "other", timeout: float = 30.0
) -> dict[str, Any]:
    """``POST /v1/sessions/transcript/finalize`` (idempotent)."""
    _status, body = _bearer_json(
        cfg,
        "/v1/sessions/transcript/finalize",
        {"client_session_id": client_session_id, "reason": reason},
        timeout=timeout,
    )
    return body


def transcript_config(cfg: Config, *, timeout: float = 10.0) -> dict[str, Any]:
    """``GET /v1/sessions/transcript/config`` — effective capture setting."""
    _status, body = _bearer_json(
        cfg, "/v1/sessions/transcript/config", None, method="GET", timeout=timeout
    )
    return body


def session_briefing(cfg: Config, *, timeout: float = 10.0) -> dict[str, Any]:
    """``GET /v1/sessions/briefing`` — the calling agent's previous-session digest."""
    _status, body = _bearer_json(cfg, "/v1/sessions/briefing", None, method="GET", timeout=timeout)
    return body


def _post_json(
    url: str,
    payload: dict[str, Any],
    *,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """POST a JSON body to a REST endpoint and unwrap the `Envelope` `data` field.

    Raises CliError on transport failure. Returns the unwrapped data dict on
    success; for 4xx/5xx the wrapped server `error` is surfaced.
    """
    body = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    }
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as e:
        body_text = ""
        with contextlib.suppress(Exception):
            body_text = e.read().decode("utf-8", errors="replace")
        try:
            envelope = json.loads(body_text)
            err = envelope.get("error") or envelope.get("detail") or body_text
        except json.JSONDecodeError:
            err = body_text or e.reason
        raise CliError(f"HTTP {e.code} from {url}: {err}", EXIT_GENERIC) from e
    except urllib.error.URLError as e:
        raise CliError(
            f"Could not reach {url}: {e.reason}. Is the API running?",
            EXIT_GENERIC,
        ) from e

    try:
        envelope = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as e:
        raise CliError(f"Could not parse response: {e}", EXIT_GENERIC) from e
    if not envelope.get("success", False):
        raise CliError(envelope.get("error") or "request failed", EXIT_GENERIC)
    data = envelope.get("data")
    return data if isinstance(data, dict) else {}


def start_device_link(
    cfg: Config, *, client_kind: str = "seaglass-cli", client_name: str = ""
) -> dict[str, Any]:
    """Kick off `seaglass auth login`. Returns server payload incl. user_code + URLs."""
    url = cfg.base_url.rstrip("/") + "/v1/auth/device/start"
    return _post_json(
        url,
        {"client_kind": client_kind, "client_name": client_name},
    )


def poll_device_link(cfg: Config, device_code: str) -> dict[str, Any]:
    """Poll once. Returns `{status, raw_token?, agent_display_name?, interval?}`."""
    url = cfg.base_url.rstrip("/") + "/v1/auth/device/poll"
    return _post_json(url, {"device_code": device_code})


def redeem_handoff(cfg: Config, code: str) -> dict[str, Any]:
    """Exchange a cli_handoff code for a token via `seaglass auth redeem`.

    Returns `{status, raw_token?, agent_display_name?, client_kind?, expires_at?}`.
    """
    url = cfg.base_url.rstrip("/") + "/v1/auth/redeem"
    return _post_json(url, {"code": code})

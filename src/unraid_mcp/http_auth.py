"""Fail-closed authentication for the streamable-HTTP transport.

Python port of pfsense-mcp's ``src/http-auth.ts``.  Loaded only when
``UNRAID_TRANSPORT=http``; the stdio transport never touches this module.

Contract:

- Check order, per request: source IP (403) → Host (403) → Origin (403) →
  ``GET``/``HEAD`` on the exact raw path ``/health`` (exempt) → bearer token
  (401 with ``WWW-Authenticate: Bearer realm="unraid-mcp"``).  Unknown routes
  need the token too.  Rejections are answered before the request body is read
  and before the MCP app sees the request.
- The token comes ONLY from ``MCP_AUTH_TOKEN_FILE`` (absolute path, regular
  file, 0600, owned by the effective uid — the same :func:`read_key_file`
  checks as ``UNRAID_API_KEY_FILE``).  ``MCP_AUTH_TOKEN`` in the environment is
  refused outright: env values leak via ``docker inspect``, ``/proc/*/environ``
  and the Unraid template.
- Token ≥ 43 characters (256 bits as base64url) from the RFC 6750 b64token
  charset.  Only its SHA-256 digest is kept; comparison is
  :func:`hmac.compare_digest` over two 32-byte digests, so neither content nor
  length leaks through timing.
- ``MCP_ALLOW_UNAUTHENTICATED=1`` is a loopback-only dev shortcut; any other
  bind is refused.  A token, when present, always wins over the flag.
- Every ``MCP_*`` value (and ``FASTMCP_HOST``/``FASTMCP_PORT``) is trimmed and
  ``""`` means unset — Unraid templates pass empty strings.
- The peer address is ``scope["client"]``, the socket peer.  uvicorn runs with
  ``proxy_headers=False``, so ``X-Forwarded-For`` never rewrites it.
- Rejections log exactly one WARNING with the peer IP and sanitised, quoted
  header values.  The Authorization header is never logged, in any form.

FastMCP 4 native options, evaluated and NOT used:

- ``HostOriginGuardMiddleware`` answers a bad Host with a plain-text 421,
  always merges its default hosts and the bound address, accepts fnmatch
  wildcards and a same-origin fallback, and skips Host checks on non-loopback
  binds in "auto" mode.  It is pinned off with ``host_origin_protection=False``.
- Native auth (``RequireAuthMiddleware`` with ``StaticTokenVerifier`` or
  ``DebugTokenVerifier``) wraps only the ``/mcp`` route, leaving custom and
  unknown routes open; its challenge is RFC 9728 ``resource_metadata`` rather
  than a realm; ``StaticTokenVerifier`` holds plaintext tokens in a dict with a
  non-constant-time lookup; ``DebugTokenVerifier`` accepts any token; nothing
  filters by source IP.

What IS used from FastMCP: ``custom_route`` (for ``/health``), ``middleware=``
(to install :class:`AuthGuard` in front of routing) and ``uvicorn_config=``
(to force ``proxy_headers=False``).
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import logging
import os
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field
from ipaddress import IPv4Address, IPv4Network, IPv6Address, IPv6Network
from typing import Literal
from urllib.parse import unquote

from starlette.datastructures import Headers
from starlette.types import ASGIApp, Receive, Scope, Send

from unraid_mcp.settings import read_key_file

logger = logging.getLogger(__name__)


class HttpAuthConfigError(ValueError):
    """Startup refusal: the HTTP auth settings are missing, unsafe or invalid."""


MIN_TOKEN_LENGTH = 43
AUTH_CHALLENGE = 'Bearer realm="unraid-mcp"'

NO_TOKEN_REFUSAL = (
    "http auth: no bearer token configured — set MCP_AUTH_TOKEN_FILE to a 0600 file "
    "owned by this user, e.g. (umask 077; openssl rand -base64 48 | tr '+/' '-_' | "
    "tr -d '=' > http-token)"
)
ENV_TOKEN_REFUSAL = (
    "http auth: MCP_AUTH_TOKEN (environment) is refused — environment values leak via "
    "docker inspect and /proc; use MCP_AUTH_TOKEN_FILE"
)
TOKEN_TOO_SHORT_REFUSAL = (
    f"http auth: MCP_AUTH_TOKEN_FILE token is too short — at least {MIN_TOKEN_LENGTH} "
    "characters (256 bits) required"
)
TOKEN_CHARSET_REFUSAL = (
    "http auth: MCP_AUTH_TOKEN_FILE token has invalid characters — allowed: "
    "A-Z a-z 0-9 . _ ~ + / - with optional trailing ="
)
UNAUTHENTICATED_NON_LOOPBACK_REFUSAL = (
    "http auth: MCP_ALLOW_UNAUTHENTICATED=1 is only honoured when MCP_HOST is "
    "127.0.0.1, ::1 or localhost"
)
ALLOWED_HOSTS_REQUIRED_REFUSAL = (
    "http auth: MCP_ALLOWED_HOSTS is required when MCP_HOST binds every interface "
    "(0.0.0.0 or ::) — list the hostnames/IPs clients connect to, without a port, "
    "e.g. MCP_ALLOWED_HOSTS=10.10.10.78"
)
UNAUTHENTICATED_WARNING = (
    "http auth: authentication DISABLED (MCP_ALLOW_UNAUTHENTICATED=1) — loopback dev mode only"
)
OPEN_CLIENTS_WARNING = "http auth: MCP_ALLOWED_CLIENTS unset — any source may present the token"
FLAG_IGNORED_WARNING = (
    "http auth: MCP_ALLOW_UNAUTHENTICATED=1 ignored — a token file is configured, "
    "the bearer token is required"
)

_LOOPBACK_BINDS = frozenset({"127.0.0.1", "::1", "localhost"})
_LOOPBACK_HOSTNAMES = ("localhost", "127.0.0.1", "[::1]")
_TRUNCATION_MARKER = "…[truncated]"

# Every pattern is used with re.fullmatch: "$" would also match before a trailing "\n".
# RFC 6750 b64token: the only characters a stored or presented token may use.
_TOKEN_CHARSET = re.compile(r"[A-Za-z0-9._~+/-]+=*")
# re.ASCII keeps IGNORECASE from folding non-ASCII letters (e.g. U+212A KELVIN SIGN)
# into the token class, which would make the ascii encode below raise.
_BEARER_HEADER = re.compile(r"Bearer +([A-Za-z0-9._~+/-]+=*) *", re.IGNORECASE | re.ASCII)
# A long b64token-charset run in a logged path may be a token sent as a path segment.
# It may contain "/" but not start with one, so the path's leading slash stays visible.
_TOKENISH_RUN = re.compile(r"[A-Za-z0-9._~+-][A-Za-z0-9._~+/-]{31,}=*")
_REDACTED = "<redacted>"
_BRACKETED_IPV6 = re.compile(r"\[([0-9A-Fa-f:.]+)\]")
_HOSTNAME = re.compile(r"[a-z0-9-]+(?:\.[a-z0-9-]+)*")
_NUMERIC_LABEL = re.compile(r"[0-9]+")
_HOST_HEADER = re.compile(r"[A-Za-z0-9.:\[\]-]+")
_PORT = re.compile(r"[0-9]{1,5}")
_PREFIX = re.compile(r"[0-9]{1,3}")
_ORIGIN = re.compile(r"(https?)://(\[[0-9a-f:.]+\]|[a-z0-9.-]+)(?::([0-9]{1,5}))?")
_DEFAULT_PORTS = {"http": 80, "https": 443}

IPNetwork = IPv4Network | IPv6Network
IPAddress = IPv4Address | IPv6Address
BearerVerdict = Literal["ok", "missing", "malformed", "invalid"]


@dataclass(frozen=True)
class HttpAuthConfig:
    """Validated HTTP auth settings; never holds token material, only its digest."""

    bind_host: str
    port: int
    # SHA-256 of the token; None only in unauthenticated loopback dev mode.
    token_digest: bytes | None = field(repr=False)
    # None = any source address.
    allowed_clients: tuple[IPNetwork, ...] | None
    # Canonical hostnames (bracketed IPv6); never empty.
    allowed_hosts: tuple[str, ...]
    allowed_origins: tuple[str, ...]
    # Startup warnings; main() logs each at WARNING.
    warnings: tuple[str, ...]


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def _v(env: Mapping[str, str], name: str) -> str | None:
    """Trimmed env value; "" (or whitespace) means unset."""
    value = env.get(name, "").strip()
    return value or None


def _split_list(value: str) -> list[str]:
    """Split a comma list, trimming entries and dropping empties."""
    return [e for e in (part.strip() for part in value.split(",")) if e]


def _sanitize(value: str, max_len: int) -> str:
    """NFKC-normalise, drop control/format characters and cap the length."""
    normalised = unicodedata.normalize("NFKC", value)
    cleaned = "".join(c for c in normalised if unicodedata.category(c) not in {"Cc", "Cf"})
    if len(cleaned) > max_len:
        return cleaned[:max_len] + _TRUNCATION_MARKER
    return cleaned


def _log_path(raw_path: str) -> str:
    """Path for a log line: percent-decoded, sanitised, token-like runs redacted, capped."""
    # Redact before capping so truncation cannot leave a partial token visible.
    # NFKC can expand a character up to 18x; the bound only keeps this pass uncapped.
    decoded = _sanitize(unquote(raw_path, encoding="latin-1"), 18 * len(raw_path))
    return _sanitize(_TOKENISH_RUN.sub(_REDACTED, decoded), 64)


def _quote(value: str | None) -> str:
    """Quote an untrusted value for a message or log line, or "(none)"."""
    return "(none)" if value is None else json.dumps(_sanitize(value, 100))


def _sha256(value: str) -> bytes:
    return hashlib.sha256(value.encode("ascii")).digest()


# ---------------------------------------------------------------------------
# Peer address and client allowlist
# ---------------------------------------------------------------------------
def normalize_ip(address: str) -> IPAddress | None:
    """Parse *address*, unwrapping IPv4-mapped IPv6; None for zone ids or garbage."""
    if "%" in address:
        return None
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return None
    if isinstance(ip, IPv6Address) and ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    return ip


def parse_allowed_clients(value: str) -> tuple[IPNetwork, ...]:
    """Parse MCP_ALLOWED_CLIENTS (comma-separated IPs/CIDRs) into networks."""

    def invalid(entry: str) -> HttpAuthConfigError:
        return HttpAuthConfigError(
            f"http auth: invalid MCP_ALLOWED_CLIENTS entry {_quote(entry)} "
            "(expected IPv4/IPv6 address or CIDR)"
        )

    entries = _split_list(value)
    if not entries:
        raise invalid(value)
    networks: list[IPNetwork] = []
    for entry in entries:
        address, sep, prefix = entry.partition("/")
        if "/" in prefix or (sep and not _PREFIX.fullmatch(prefix)):
            raise invalid(entry)
        ip = normalize_ip(address)
        if ip is None:
            raise invalid(entry)
        if sep:
            if int(prefix) > ip.max_prefixlen:
                raise invalid(entry)
            networks.append(ipaddress.ip_network(f"{ip}/{int(prefix)}", strict=False))
        else:
            networks.append(ipaddress.ip_network(ip))
    return tuple(networks)


def client_allowed(networks: tuple[IPNetwork, ...], address: str | None) -> bool:
    """True when the socket peer *address* is inside one of *networks*."""
    if not address:
        return False
    ip = normalize_ip(address)
    if ip is None:
        return False
    # `ip in net` across IP versions is simply False.
    return any(ip in net for net in networks)


# ---------------------------------------------------------------------------
# Host allowlist
# ---------------------------------------------------------------------------
def _canonical_hostname(text: str) -> str | None:
    """Canonical lowercase hostname, dotted-quad IPv4 or ``[compressed-ipv6]``."""
    bracketed = _BRACKETED_IPV6.fullmatch(text)
    if bracketed:
        try:
            return f"[{IPv6Address(bracketed.group(1)).compressed}]"
        except ValueError:
            return None
    # isascii first: str.lower() folds some non-ASCII letters (U+212A → "k").
    if not text.isascii():
        return None
    host = text.lower()
    if not _HOSTNAME.fullmatch(host):
        return None
    last = host.rsplit(".", 1)[-1]
    if _NUMERIC_LABEL.fullmatch(last) or last.startswith("0x"):
        # Looks numeric: only a strict dotted quad is accepted, so "127.1" and
        # "0x7f.0.0.1" cannot alias an allowed IP.
        try:
            return str(IPv4Address(host))
        except ValueError:
            return None
    return host


def parse_allowed_hosts(value: str) -> tuple[str, ...]:
    """Parse MCP_ALLOWED_HOSTS into canonical hostnames (no ports)."""
    hostnames: list[str] = []
    for raw in _split_list(value):
        canonical: str | None
        if ":" in raw and not raw.startswith("["):
            canonical = None
            if "%" not in raw:
                try:
                    canonical = f"[{IPv6Address(raw).compressed}]"
                except ValueError:
                    canonical = None
        else:
            canonical = _canonical_hostname(raw)
        if canonical is None:
            raise HttpAuthConfigError(
                f"http auth: invalid MCP_ALLOWED_HOSTS entry {_quote(raw)} "
                "(hostname or IP, no port — Host matching is port-agnostic)"
            )
        if canonical not in hostnames:
            hostnames.append(canonical)
    if not hostnames:
        raise HttpAuthConfigError("http auth: MCP_ALLOWED_HOSTS lists no hosts")
    return tuple(hostnames)


def host_allowed(header: str | None, allowed: tuple[str, ...]) -> bool:
    """Port-agnostic Host header check against canonical hostnames."""
    if not header or not _HOST_HEADER.fullmatch(header):
        return False
    if header.startswith("["):
        end = header.find("]")
        if end == -1:
            return False
        host, rest = header[: end + 1], header[end + 1 :]
        if rest and not rest.startswith(":"):
            return False
        port = rest[1:] if rest else None
    else:
        host, sep, port_text = header.partition(":")
        port = port_text if sep else None
    if port is not None and (not _PORT.fullmatch(port) or int(port) > 65535):
        return False
    return _canonical_hostname(host) in allowed


# ---------------------------------------------------------------------------
# Origin allowlist
# ---------------------------------------------------------------------------
def parse_allowed_origins(value: str) -> tuple[str, ...]:
    """Parse MCP_ALLOWED_ORIGINS: exact serialised ``scheme://host[:port]`` only."""
    origins: list[str] = []
    for entry in _split_list(value):
        match = _ORIGIN.fullmatch(entry)
        ok = False
        if match:
            scheme, host, port = match.groups()
            ok = _canonical_hostname(host) == host
            if ok and port is not None:
                ok = (
                    not port.startswith("0")
                    and 1 <= int(port) <= 65535
                    and int(port) != _DEFAULT_PORTS[scheme]
                )
        if not ok:
            raise HttpAuthConfigError(
                f"http auth: invalid MCP_ALLOWED_ORIGINS entry {_quote(entry)} "
                "(expected exact scheme://host[:port], no path or trailing slash)"
            )
        if entry not in origins:
            origins.append(entry)
    return tuple(origins)


# ---------------------------------------------------------------------------
# Bearer token
# ---------------------------------------------------------------------------
def check_bearer(header: str | None, expected: bytes) -> BearerVerdict:
    """Constant-time bearer check: compares SHA-256 digests, never raw strings."""
    if not header:
        return "missing"
    match = _BEARER_HEADER.fullmatch(header)
    if not match:
        return "malformed"
    return "ok" if hmac.compare_digest(_sha256(match.group(1)), expected) else "invalid"


def describe_http_auth(config: HttpAuthConfig) -> str:
    """One-line startup summary; never contains token material."""
    mode = (
        "bearer token required"
        if config.token_digest is not None
        else "DISABLED (MCP_ALLOW_UNAUTHENTICATED=1)"
    )
    clients = (
        ", ".join(str(net) for net in config.allowed_clients) if config.allowed_clients else "any"
    )
    hosts = ", ".join(config.allowed_hosts)
    origins = ", ".join(config.allowed_origins) or "none (any Origin refused)"
    return (
        f"http auth: {mode}; bind {config.bind_host}:{config.port}; clients: {clients}; "
        f"hosts: {hosts} (port-agnostic); origins: {origins}"
    )


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------
def _is_wildcard(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_unspecified
    except ValueError:
        return False


def load_http_auth_config(env: Mapping[str, str] | None = None) -> HttpAuthConfig:
    """Read and validate the HTTP auth settings from *env* (default ``os.environ``).

    Raises :class:`HttpAuthConfigError` on any refusal; no message ever contains
    token material.
    """
    if env is None:
        env = os.environ
    warnings: list[str] = []

    bind_host = _v(env, "MCP_HOST") or _v(env, "FASTMCP_HOST") or "127.0.0.1"

    port_var, port_text = "MCP_PORT", _v(env, "MCP_PORT")
    if port_text is None:
        port_var, port_text = "FASTMCP_PORT", _v(env, "FASTMCP_PORT")
    if port_text is None:
        port_text = "8000"
    if not _PORT.fullmatch(port_text) or int(port_text) > 65535:
        raise HttpAuthConfigError(
            f"http auth: invalid {port_var} {_quote(port_text)} (expected 0-65535)"
        )
    port = int(port_text)

    if _v(env, "MCP_AUTH_TOKEN") is not None:
        raise HttpAuthConfigError(ENV_TOKEN_REFUSAL)

    flag = _v(env, "MCP_ALLOW_UNAUTHENTICATED")
    if flag == "1":
        allow_unauthenticated = True
    elif flag is None or flag == "0":
        allow_unauthenticated = False
    else:
        raise HttpAuthConfigError(
            f"http auth: invalid MCP_ALLOW_UNAUTHENTICATED {json.dumps(_sanitize(flag, 32))} "
            "(expected 0 or 1)"
        )

    is_loopback_bind = bind_host in _LOOPBACK_BINDS
    token_digest: bytes | None
    token_file = _v(env, "MCP_AUTH_TOKEN_FILE")
    if token_file is not None:
        try:
            token = read_key_file(token_file)
        except ValueError as exc:
            raise HttpAuthConfigError(f"http auth: MCP_AUTH_TOKEN_FILE: {exc}") from None
        if len(token) < MIN_TOKEN_LENGTH:
            raise HttpAuthConfigError(TOKEN_TOO_SHORT_REFUSAL)
        if not _TOKEN_CHARSET.fullmatch(token):
            raise HttpAuthConfigError(TOKEN_CHARSET_REFUSAL)
        token_digest = _sha256(token)
        if allow_unauthenticated:
            warnings.append(FLAG_IGNORED_WARNING)
    elif allow_unauthenticated:
        if not is_loopback_bind:
            raise HttpAuthConfigError(UNAUTHENTICATED_NON_LOOPBACK_REFUSAL)
        token_digest = None
        warnings.append(UNAUTHENTICATED_WARNING)
    else:
        raise HttpAuthConfigError(NO_TOKEN_REFUSAL)

    clients_text = _v(env, "MCP_ALLOWED_CLIENTS")
    allowed_clients = None if clients_text is None else parse_allowed_clients(clients_text)
    if token_digest is not None and allowed_clients is None and not is_loopback_bind:
        warnings.append(OPEN_CLIENTS_WARNING)

    hosts_text = _v(env, "MCP_ALLOWED_HOSTS")
    if hosts_text is not None:
        allowed_hosts = parse_allowed_hosts(hosts_text)
    elif _is_wildcard(bind_host):
        raise HttpAuthConfigError(ALLOWED_HOSTS_REQUIRED_REFUSAL)
    elif is_loopback_bind:
        allowed_hosts = _LOOPBACK_HOSTNAMES
    else:
        allowed_hosts = parse_allowed_hosts(bind_host)

    origins_text = _v(env, "MCP_ALLOWED_ORIGINS")
    allowed_origins = () if origins_text is None else parse_allowed_origins(origins_text)

    return HttpAuthConfig(
        bind_host=bind_host,
        port=port,
        token_digest=token_digest,
        allowed_clients=allowed_clients,
        allowed_hosts=allowed_hosts,
        allowed_origins=allowed_origins,
        warnings=tuple(warnings),
    )


# ---------------------------------------------------------------------------
# ASGI middleware
# ---------------------------------------------------------------------------
async def _reject(send: Send, status: Literal[401, 403], message: str) -> None:
    body = json.dumps(
        {"jsonrpc": "2.0", "error": {"code": -32000, "message": message}, "id": None},
        separators=(",", ":"),
    ).encode()
    headers = [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(body)).encode()),
    ]
    if status == 401:
        headers.append((b"www-authenticate", AUTH_CHALLENGE.encode()))
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})


class AuthGuard:
    """Pure ASGI middleware enforcing the HTTP auth contract (see module docstring).

    It never calls ``receive``: a rejected request's body is never read.  The
    wrapped app is called only when every check passes.
    """

    def __init__(self, app: ASGIApp, config: HttpAuthConfig) -> None:
        self.app = app
        self.config = config

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            await self.app(scope, receive, send)
            return

        client = scope.get("client")
        raw_peer: str | None = client[0] if client else None
        ip = normalize_ip(raw_peer) if raw_peer else None
        if ip is not None:
            peer = str(ip)
        elif raw_peer:
            peer = _sanitize(raw_peer, 64)
        else:
            peer = "unknown"
        raw_path: bytes = (scope.get("raw_path") or scope["path"].encode()).split(b"?", 1)[0]
        method: str = scope.get("method", "WEBSOCKET")
        where = f"from {peer} {_sanitize(method, 16)} {_log_path(raw_path.decode('latin-1'))}"

        if scope["type"] != "http":
            logger.warning("http: 403 websocket refused %s", where)
            await send({"type": "websocket.close", "code": 1008})
            return

        config = self.config
        headers = Headers(scope=scope)

        if config.allowed_clients is not None and not client_allowed(
            config.allowed_clients, raw_peer
        ):
            logger.warning("http: 403 client not allowed %s", where)
            await _reject(send, 403, "Forbidden")
            return

        hosts = headers.getlist("host")
        if not (len(hosts) == 1 and host_allowed(hosts[0], config.allowed_hosts)):
            logger.warning(
                "http: 403 host not allowed %s host=%s", where, _quote(", ".join(hosts) or None)
            )
            await _reject(send, 403, "Forbidden")
            return

        # An absent Origin passes (non-browser clients); an empty one does not.
        origins = headers.getlist("origin")
        if origins and not (len(origins) == 1 and origins[0] in config.allowed_origins):
            logger.warning(
                "http: 403 origin not allowed %s origin=%s", where, _quote(", ".join(origins))
            )
            await _reject(send, 403, "Forbidden")
            return

        # Exact raw-path match only: "//health", "/health/" and "/%68ealth" need the token.
        if method in {"GET", "HEAD"} and raw_path == b"/health":
            await self.app(scope, receive, send)
            return

        if config.token_digest is None:
            await self.app(scope, receive, send)
            return

        authorizations = headers.getlist("authorization")
        verdict: BearerVerdict = (
            "malformed"
            if len(authorizations) > 1
            else check_bearer(authorizations[0] if authorizations else None, config.token_digest)
        )
        if verdict != "ok":
            logger.warning("http: 401 %s bearer token %s", verdict, where)
            await _reject(send, 401, "Unauthorized")
            return

        await self.app(scope, receive, send)

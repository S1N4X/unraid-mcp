# unraid-mcp

MCP server for Unraid's official GraphQL API (Unraid 7.3.2 / `unraid-api` 4.35.1).
Connects to `/graphql` on the standard web port — not port 31337.

## Install

```bash
claude mcp add unraid -e UNRAID_HOST=tower.local -e UNRAID_API_KEY=your-key -- uvx unraid-mcp
```

## Tool surface

One MCP tool: `unraid(domain, action, **params)`.

| Domain | Read actions | Write actions (gated) |
|---|---|---|
| `system` | `info`, `versions`, `vars`, `server`, `time`, `plugins` | — |
| `array` | `status`, `disks`, `parity_history` | `start`, `stop`, `parity_start`, `parity_pause`, `parity_resume`, `parity_cancel` |
| `docker` | `list`, `get`, `logs`, `networks`, `port_conflicts`, `update_status` | `start`, `stop`, `restart`, `pause`, `unpause` |
| `vm` | `list`, `get` | `start`, `stop`, `pause`, `resume`, `reboot` |
| `share` | `list`, `get` | — |
| `notification` | `overview`, `list` | `archive`, `unread`, `archive_all` |
| `metrics` | `cpu`, `memory`, `temperature`, `network`, `ups` | — |
| `logs` | `list`, `read` | — |
| `health` | `ping`, `schema_check`, `capabilities` | — |

## Configuration

| Env var | Default | Meaning |
|---|---|---|
| `UNRAID_HOST` | — (required unless `UNRAID_API_URL`) | Hostname/IP of the Unraid server |
| `UNRAID_API_KEY_FILE` | — (one of KEY/KEY_FILE; preferred) | Absolute path to a file holding the API key: regular file, mode 0600, owned by the effective uid |
| `UNRAID_API_KEY` | — (one of KEY/KEY_FILE) | API key from `unraid-api apikey --create`; setting both is refused at startup |
| `UNRAID_API_URL` | `http://{host}/graphql` | Full endpoint override |
| `UNRAID_ALLOW_WRITES` | `0` | Master write switch |
| `UNRAID_VERIFY_SSL` | `1` | `0` or path to CA bundle |
| `UNRAID_TIMEOUT` | `30` | Read timeout in seconds |
| `UNRAID_MAX_RESPONSE_BYTES` | `40000` | Response cap |
| `UNRAID_TRANSPORT` | `stdio` | `stdio` or `http` |
| `UNRAID_LOG_LEVEL` | `INFO` | Logging level |

HTTP transport variables are read only when `UNRAID_TRANSPORT=http`. For every
`MCP_*` variable (and `FASTMCP_HOST`/`FASTMCP_PORT`) surrounding whitespace is
trimmed and `""` means unset, so empty Unraid template fields are harmless.

| Env var | Code default | Image default | Meaning |
|---|---|---|---|
| `MCP_HOST` | `FASTMCP_HOST`, else `127.0.0.1` | — (`FASTMCP_HOST=0.0.0.0`) | Bind address |
| `MCP_PORT` | `FASTMCP_PORT`, else `8000` | — (`FASTMCP_PORT=8000`) | Bind port (0–65535) |
| `MCP_AUTH_TOKEN_FILE` | — (required) | `/config/http-token` | Absolute path to the bearer token file (see below) |
| `MCP_AUTH_TOKEN` | — | — | **Refused** at startup: environment values leak via `docker inspect` and `/proc` |
| `MCP_ALLOW_UNAUTHENTICATED` | `0` | — | `1` disables auth; honoured only on a `127.0.0.1`, `::1` or `localhost` bind and ignored when a token file is set |
| `MCP_ALLOWED_CLIENTS` | any source | — | Comma list of source IPs/CIDRs (IPv4-mapped IPv6 peers are matched as IPv4) |
| `MCP_ALLOWED_HOSTS` | loopback bind: `localhost,127.0.0.1,[::1]`; other specific bind: the bind address; `0.0.0.0`/`::`: **required** | — | Comma list of accepted `Host` names/IPs, no port (matching is port-agnostic) |
| `MCP_ALLOWED_ORIGINS` | none (any `Origin` header refused) | — | Comma list of exact `scheme://host[:port]` origins; requests without `Origin` pass |

## HTTP authentication

With `UNRAID_TRANSPORT=http` the server fails closed: it refuses to start without
a bearer-token file, and every request passes these checks in order before
FastMCP routes it or reads its body:

| # | Check | On failure |
|---|---|---|
| 1 | Source IP (socket peer) in `MCP_ALLOWED_CLIENTS`, when set | 403 |
| 2 | Exactly one `Host` header, in `MCP_ALLOWED_HOSTS` (port ignored) | 403 |
| 3 | `Origin` absent, or exactly one value listed in `MCP_ALLOWED_ORIGINS` | 403 |
| 4 | `GET`/`HEAD` on the exact raw path `/health` skips the token check | — |
| 5 | `Authorization: Bearer <token>` matches the token file | 401 with `WWW-Authenticate: Bearer realm="unraid-mcp"` |

Rejections carry a JSON-RPC body (`{"jsonrpc":"2.0","error":{"code":-32000,"message":"Forbidden"|"Unauthorized"},"id":null}`)
and log one WARNING with the peer IP; the `Authorization` header is never
logged. Unknown routes, `POST /health`, `/health/` and `//health` all need the
token. WebSocket connections are closed with code 1008.

### Token file

Generate a 256-bit token:

```bash
(umask 077; openssl rand -base64 48 | tr '+/' '-_' | tr -d '=' > http-token)
```

`MCP_AUTH_TOKEN_FILE` (and `UNRAID_API_KEY_FILE`) must be:

- an absolute path to a regular file,
- mode `0600`, owned by the effective uid of the server process (root in the
  container),
- non-empty UTF-8 text (surrounding whitespace is stripped).

The token must also be at least 43 characters from the RFC 6750 b64token
charset (`A-Z a-z 0-9 . _ ~ + / -`, optional trailing `=`). Only its SHA-256
digest is kept in memory.

### Startup refusals

The server exits with an `unraid-mcp: http auth: …` message when:

- no `MCP_AUTH_TOKEN_FILE` is set (and `MCP_ALLOW_UNAUTHENTICATED` is not `1`);
- `MCP_AUTH_TOKEN` is set in the environment (even alongside a file);
- the token file fails any file check, is shorter than 43 characters or uses
  characters outside the b64token charset;
- `MCP_ALLOW_UNAUTHENTICATED` is anything other than `0`/`1`, or is `1` on a
  non-loopback bind;
- the bind is `0.0.0.0` or `::` and `MCP_ALLOWED_HOSTS` is unset;
- `MCP_PORT`/`FASTMCP_PORT`, or an entry of `MCP_ALLOWED_CLIENTS`,
  `MCP_ALLOWED_HOSTS` or `MCP_ALLOWED_ORIGINS`, is invalid.

At startup it logs a one-line summary (mode, bind, clients, hosts, origins) and
a warning when, for example, `MCP_ALLOWED_CLIENTS` is unset on a non-loopback
bind.

### Example: container on monolith

```bash
UNRAID_TRANSPORT=http
FASTMCP_HOST=0.0.0.0                       # image default
MCP_AUTH_TOKEN_FILE=/config/http-token     # image default
UNRAID_API_KEY_FILE=/config/unraid-api.key # image default; remove UNRAID_API_KEY
MCP_ALLOWED_HOSTS=10.10.10.78
MCP_ALLOWED_CLIENTS=192.168.0.240
```

Check it from an allowed client:

```bash
curl -s http://10.10.10.78:8000/health          # 200 {"status":"ok"}
curl -s -o /dev/null -w '%{http_code}\n' -X POST http://10.10.10.78:8000/mcp  # 401
```

### FastMCP native auth vs this guard

FastMCP 4's own options were evaluated and are not used:

- `HostOriginGuardMiddleware` answers a bad Host with a plain-text 421, always
  merges its default hosts and the bound address, accepts wildcards and a
  same-origin fallback, and skips Host checks on non-loopback binds in "auto"
  mode. It is pinned off with `host_origin_protection=False`.
- Native auth (`RequireAuthMiddleware` with `StaticTokenVerifier` or
  `DebugTokenVerifier`) wraps only the `/mcp` route, leaving custom and unknown
  routes open; its challenge is RFC 9728 `resource_metadata` rather than a
  realm; `StaticTokenVerifier` keeps plaintext tokens with a non-constant-time
  lookup; `DebugTokenVerifier` accepts any token; nothing filters by source IP.

What is used from FastMCP: `custom_route` (for `/health`), `middleware=` (to put
the pure-ASGI `AuthGuard` in front of routing) and `uvicorn_config=` (to force
`proxy_headers=False`, so `X-Forwarded-For` never replaces the socket peer).

## Safety

Two independent write locks prevent accidental mutations:

1. **Server-level**: writes are refused unless `UNRAID_ALLOW_WRITES=1`. Default
   is read-only. Refusal is a structured `write_disabled` error naming the env
   var.
2. **Call-level**: every write action requires `confirm=true` or an accepted MCP
   elicitation prompt.

For defence in depth, use a **VIEWER-role API key** so the Unraid API itself
rejects mutations regardless of server configuration.

`docker restart` is implemented as `stop` then `start` (the API has no restart
mutation).

## Non-goals (v1)

Not implemented: disk add/remove, `clearArrayDiskStatistics`, `removeContainer`,
VM `forceStop`/`reset`, API-key mutations, OIDC, rclone, `updateSettings`, flash
backup, plugin install/remove, GraphQL subscriptions.

Each returns a structured `not_implemented` error naming the reason.

## Development

```bash
uv sync
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
```

Live tests against a real Unraid server (read-only):

```bash
UNRAID_LIVE=1 uv run --env-file .env pytest tests/test_live.py
```

## License

MIT

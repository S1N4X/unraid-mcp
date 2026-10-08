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
| `MCP_HOST` | `FASTMCP_HOST`, else `127.0.0.1` | — | Bind address |
| `MCP_PORT` | `FASTMCP_PORT`, else `8000` | — | Bind port (0–65535) |
| `MCP_AUTH_TOKEN_FILE` | — (required) | `/config/http-token` | Absolute path to the bearer token file (see below) |
| `MCP_AUTH_TOKEN` | — | — | **Refused** at startup: environment values leak via `docker inspect` and `/proc` |
| `MCP_ALLOW_UNAUTHENTICATED` | `0` | — | `1` disables auth; honoured only on a `127.0.0.1`, `::1` or `localhost` bind and ignored when a token file is set |
| `MCP_ALLOWED_CLIENTS` | any source | — | Comma list of source IPs/CIDRs (IPv4-mapped IPv6 peers are matched as IPv4) |
| `MCP_ALLOWED_HOSTS` | loopback bind: `localhost,127.0.0.1,[::1]`; other specific bind: the bind address; `0.0.0.0`/`::`: **required** | — | Comma list of accepted `Host` names/IPs, no port (matching is port-agnostic) |
| `MCP_ALLOWED_ORIGINS` | none (any `Origin` header refused) | — | Comma list of exact `scheme://host[:port]` origins; requests without `Origin` pass |

The image sets no bind, so without `MCP_HOST`/`MCP_PORT` it binds `127.0.0.1`
on port `8000`.

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
- mode `0600`, owned by the effective uid of the server process (uid 10078 in
  the container image),
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

The canonical dockerMan template is [`deploy/my-unraid-mcp.xml`](deploy/my-unraid-mcp.xml).
The container uses host networking, binds only `10.10.10.50:8078` and reads the
API at `UNRAID_API_URL=http://127.0.0.1/graphql`.

Why host networking: the old `br0.500` macvlan container (a dedicated
`10.10.10.x` IP) could not reach its own host (macvlan host isolation), so
every upstream read hung (#360). On the host network it reaches Unraid's nginx on `127.0.0.1:80`.

```bash
UNRAID_TRANSPORT=http
UNRAID_API_URL=http://127.0.0.1/graphql
MCP_HOST=10.10.10.50
MCP_PORT=8078
MCP_ALLOWED_HOSTS=10.10.10.50
MCP_ALLOWED_CLIENTS=192.168.0.240
MCP_AUTH_TOKEN_FILE=/config/http-token     # image default
UNRAID_API_KEY_FILE=/config/unraid-api.key # image default; remove UNRAID_API_KEY
```

Run flags: `--network host --user 10078:10078 --read-only --cap-drop ALL
--security-opt no-new-privileges`, with `/config` mounted read-only. The appdata
directory is owned by `10078:10078` with mode `700`; `http-token` and
`unraid-api.key` are owned by `10078:10078` with mode `600`.

Deploy from this repo (dry run first, then for real; `MONOLITH` overrides the
default `root@192.168.0.50`):

```bash
deploy/deploy.sh --backup-suffix YYYYMMDD-tag --dry-run
deploy/deploy.sh --backup-suffix YYYYMMDD-tag
```

It builds the image, backs up the live template and autostart file, records
the owners/modes of the appdata directory and both secrets
(`/var/lib/docker/unraid-autostart.bak-<suffix>.owners`) and tags the running
image `unraid-mcp:bak-<suffix>`, then ships the new image, installs the
template, fixes secret ownership/modes, keeps `unraid-mcp` in autostart,
rebuilds the container and verifies the listener is exactly `10.10.10.50:8078`
and the container runs the image ID it built. If any step from the backup on
fails it prints the backups and the restore commands (template, autostart,
secret owners/modes back to the recorded ones — the previous image ran as
root — `docker tag` back, rebuild).

Check it from an allowed client:

```bash
curl -s http://10.10.10.50:8078/health          # 200 {"status":"ok"}
curl -s -o /dev/null -w '%{http_code}\n' -X POST http://10.10.10.50:8078/mcp  # 401
```

Live HTTP smoke (token from `UNRAID_MCP_TOKEN_FILE`, default
`~/.config/unraid-mcp/http-token`):

```bash
UNRAID_MCP_LIVE_URL=http://10.10.10.50:8078 uv run pytest tests/test_live_http.py --no-cov
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
   is read-only. Refusal is a structured `write_disabled` error whose `hint`
   names the env var.
2. **Call-level**: every write action requires `confirm=true` or an MCP
   elicitation prompt (choices `yes` / `no`) that the user accepts **and**
   answers `yes`. The match is exact and case-sensitive: accepting with `no`,
   an empty or missing answer, or any other value (`YES`, ` yes`) refuses the
   write, as do a declined or cancelled prompt. FastMCP 4 offers elicitation
   only on initialize-handshake (legacy) connections; on a 2026-07-28
   connection the prompt cannot be sent, so the write is refused unless
   `confirm=true` is passed.

For defence in depth, use a **VIEWER-role API key** so the Unraid API itself
rejects mutations regardless of server configuration.

`docker restart` is implemented as `stop` then `start` (the API has no restart
mutation).

## Non-goals (v1)

Not implemented: disk add/remove, `clearArrayDiskStatistics`, `removeContainer`,
VM `forceStop`/`reset`, API-key mutations, OIDC, rclone, `updateSettings`, flash
backup, plugin install/remove, GraphQL subscriptions.

Each returns a structured `not_implemented` error naming the reason.

## Errors

A failed call returns an MCP tool error (`isError: true`) whose text is compact
JSON:

```json
{"code":"write_disabled","message":"Write operations are disabled.","hint":"Set UNRAID_ALLOW_WRITES=1 to enable."}
```

`code` is always present (`write_disabled`, `confirmation_required`,
`unknown_action`, `not_implemented`, `invalid_params`, `unauthorized`,
`not_found`, `introspection_disabled`, `upstream_error`, `connection_failed`);
`hint` and `details` appear when set. Redaction before the error leaves the
server:

- **GraphQL `extensions` allowlist**: of an upstream GraphQL error's
  `extensions`, only `code` (when a string) is forwarded, as
  `details.extensions.code`; every other extension key is dropped.
- **By key name** (`details`, any depth): a dict value is replaced by
  `***REDACTED***` when any segment of its key — split on non-alphanumerics
  and camelCase, singular or plural — is `key`, `apikey`, `token`, `secret`,
  `password`, `passwd`, `pwd`, `authorization`, `auth`, `cookie`, `session`,
  `credential` or `bearer`, **or** when the key, lowercased with
  non-alphanumerics removed, contains one of the unambiguous words
  `password`, `passwd`, `secret`, `apikey`, `accesskey`, `privatekey`,
  `sshkey`, `token`, `credential`, `authorization`, `cookie`, `bearer`,
  `session`. So `apiKey`, `x-api-key`, `dbpassword`, `clientsecret`,
  `sshkeys` match; `keyword`, `monkeyCount`, `author` do not. Subtrees deeper
  than 20 levels are replaced wholesale.
- **By value** (the whole error text — `message`, `hint`, `details`): the
  configured API key (when at least 8 characters long) and `Bearer <token>`
  strings are masked. The same scrubbing applies to the server's
  `unraid <domain>.<action> failed: <code>: <message>` warning log line,
  where control characters (newlines) are also escaped.

Not detected: other secrets inside free text, or under key names that match
neither rule (for example a database password embedded in a `dsn` URL).
These guarantees cover structured (`UnraidError`) failures only. Unexpected
(non-Unraid) exceptions keep FastMCP's generic
`Error calling tool 'unraid': …` text and are logged with a full traceback;
neither is scrubbed.

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
UNRAID_LIVE=1 uv run --env-file .env pytest tests/test_live.py --no-cov
```

Live HTTP smoke against a deployed server (token from `UNRAID_MCP_TOKEN_FILE`,
default `~/.config/unraid-mcp/http-token`):

```bash
UNRAID_MCP_LIVE_URL=http://10.10.10.50:8078 uv run pytest tests/test_live_http.py --no-cov
```

## License

MIT

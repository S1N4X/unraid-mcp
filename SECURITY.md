# Security Policy

## Supported versions

| Version | Supported |
|---------|-----------|
| 0.1.x   | Yes       |

## Key handling

- The API key is sent only as an `X-API-Key` header over the configured URL.
- The client never logs requests, headers or response bodies. A failed tool
  call logs one warning line, `unraid <domain>.<action> failed: <code>:
  <message>` (no details, no traceback), with the API key and bearer tokens
  scrubbed as below and control characters (newlines) escaped.
- GraphQL error `extensions` are upstream-controlled: only
  `extensions.code` (when a string) is forwarded to the client; every other
  extension key is dropped before any redaction runs (allowlist).
- In error results returned to the MCP client (`unraid_mcp.redaction`):
  - `details` values are recursively redacted by **key name**: when any
    segment of the key (split on non-alphanumerics and camelCase, singular or
    plural) is `key`, `apikey`, `token`, `secret`, `password`, `passwd`,
    `pwd`, `authorization`, `auth`, `cookie`, `session`, `credential`,
    `bearer`, or when the key lowercased with non-alphanumerics removed
    contains `password`, `passwd`, `secret`, `apikey`, `accesskey`,
    `privatekey`, `sshkey`, `token`, `credential`, `authorization`, `cookie`,
    `bearer` or `session` (so `apiKey`, `dbpassword`, `clientsecret` match;
    `keyword`, `author` do not). Subtrees nested deeper than 20 levels are
    replaced wholesale (fail closed).
  - The configured API key (when at least 8 characters long) and
    `Bearer <token>` strings are scrubbed **by value** from the whole error
    text (`message`, `hint`, `details`, including truncated upstream HTTP
    bodies).
  - Limit: other secrets inside free text, or under key names matching
    neither rule, are not detected and can reach the client.
- No credentials are written to disk. For `UnraidError` failures (every
  structured error), the configured API key (subject to the 8-character
  minimum above) is never included in the client error text or in the
  boundary warning line; other upstream secrets are masked only as described
  above.
- Scope limit: an unexpected non-`UnraidError` exception keeps FastMCP's
  generic `Error calling tool 'unraid': <message>` text, and `server.py` logs
  it with `logger.exception` (full traceback). Neither is scrubbed.
- Prefer `UNRAID_API_KEY_FILE` over `UNRAID_API_KEY`. The file must be an
  absolute path to a regular file, mode `0600`, owned by the effective uid, and
  non-empty; otherwise the server refuses to start. Error messages name the
  variable but never echo its value (a pasted key may start with `/`) or the
  file content.
- Never set both: `UNRAID_API_KEY` together with `UNRAID_API_KEY_FILE` is
  refused as ambiguous. Keep the environment key for local stdio use only —
  environment values leak via `docker inspect` and `/proc/*/environ`.

## HTTP transport

`UNRAID_TRANSPORT=http` fails closed (details in the README, "HTTP
authentication"):

- The server refuses to start without a bearer token. The token is read only
  from `MCP_AUTH_TOKEN_FILE` (same file checks as the API key file, at least 43
  characters); `MCP_AUTH_TOKEN` in the environment is refused.
- Only the token's SHA-256 digest is kept in memory, and presented tokens are
  compared digest-to-digest with `hmac.compare_digest` (constant time).
- `MCP_ALLOW_UNAUTHENTICATED=1` is honoured only on a loopback bind.
- Source IP, `Host` and `Origin` allowlists are enforced before the token
  check; a wildcard bind requires `MCP_ALLOWED_HOSTS`.
- The source IP is the socket peer only: uvicorn runs with
  `proxy_headers=False`, so `X-Forwarded-For` is ignored.
- The uvicorn access log is off (`access_log=False`): it would print raw
  paths and query strings, bypassing the guard's token redaction.
- Rejected requests are answered before their body is read. Each logs one
  WARNING with the peer IP and sanitised header values; the `Authorization`
  header is never logged.

## Deployment

- The monolith container runs on the host network, bound to one specific
  address (`10.10.10.50:8078`), never `0.0.0.0`. The image sets no bind
  default: without `MCP_HOST`/`MCP_PORT` it falls back to `127.0.0.1:8000`.
- The image runs as non-root uid/gid 10078 with a read-only root filesystem,
  `--cap-drop ALL` and `no-new-privileges`. `/config` is mounted read-only;
  the secret files are mode 600 in a mode 700 directory, all owned by 10078.
- Host networking shares monolith's network namespace, including services
  listening on the host loopback. The hardening above limits what a
  compromised process can do with that.
- Network layer: a pfSense floating rule rejects every source except
  `192.168.0.240` to `10.10.10.50:8078`. Same-VLAN peers and monolith itself
  never cross pfSense; the app's `MCP_ALLOWED_CLIENTS` refuses them with 403.
- The bearer token travels in cleartext HTTP on the LAN (vclaude02
  `192.168.0.240` → pfSense → `10.10.10.50:8078`); anyone who can sniff or
  intercept that path can read and replay it. This is an accepted risk for
  this homelab deployment (read-only by default, network-layer reject plus
  the source allowlist). Terminate TLS in front of the container before
  exposing it more widely.

## Read-only by default

- `UNRAID_ALLOW_WRITES` defaults to `0` (off). Write actions are refused at the
  server level unless explicitly enabled.
- Every write action additionally requires an explicit `confirm=true` parameter
  or an accepted MCP elicitation prompt answered exactly `yes`.
- For defence in depth, use a **VIEWER-role** API key so the Unraid API itself
  rejects mutations regardless of server configuration.

## Elicitation and confirmation

Without `confirm=true`, every write action asks for confirmation through an
elicitation prompt with the choices `yes` / `no`. The write proceeds only when
the prompt is accepted and the answer is exactly `yes` (case-sensitive, no
trimming); accepting with `no` or any other value, declining, cancelling, or a
client that does not support elicitation refuses the request and sends nothing
to the Unraid API. FastMCP 4 does not offer elicitation on 2026-07-28
connections, so there `confirm=true` is the only way to confirm a write.

## Reporting a vulnerability

Open an issue on the GitHub repository. There is no bug bounty. Please include
steps to reproduce and the version affected.

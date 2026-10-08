# Security Policy

## Supported versions

| Version | Supported |
|---------|-----------|
| 0.1.x   | Yes       |

## Key handling

- The API key is sent only as an `X-API-Key` header over the configured URL.
- Keys, tokens, secrets, and passwords are recursively redacted from all log
  output and error messages.
- No credentials are written to disk or included in MCP responses.
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

## Read-only by default

- `UNRAID_ALLOW_WRITES` defaults to `0` (off). Write actions are refused at the
  server level unless explicitly enabled.
- Every write action additionally requires an explicit `confirm=true` parameter
  or an accepted MCP elicitation prompt.
- For defence in depth, use a **VIEWER-role** API key so the Unraid API itself
  rejects mutations regardless of server configuration.

## Elicitation and confirmation

Write actions that are flagged `destructive` describe the operation in an
elicitation prompt the user must accept. If the MCP client does not support
elicitation and `confirm` is not set, the request is refused.

## Reporting a vulnerability

Open an issue on the GitHub repository. There is no bug bounty. Please include
steps to reproduce and the version affected.

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

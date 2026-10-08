# Changelog

## Unreleased

### Added

- HTTP bearer auth with source-IP, Host and Origin allowlists.
- `/health` endpoint (GET/HEAD).
- `UNRAID_API_KEY_FILE` to read the API key from a file.

### Fixed

- Write confirmation by elicitation now proceeds only when the prompt is
  accepted **and** answered exactly `yes`. Before, accepting with `no` (or any
  other answer) let the write through, bypassing the second write lock.
- Tool errors now reach the client as compact JSON with `code`, `message`,
  `hint` and `details`; FastMCP previously reduced them to
  `Error calling tool 'unraid': <message>`.
- Secrets in error `details` are redacted before they leave the server
  (`unraid_mcp.redaction`); the redaction helper existed but was never called.
  Key matching is by segment (singular or plural) plus unambiguous substrings
  (`keyword` no longer matches; `authorization`, `cookie`, `session`,
  `credential`, `dbpassword`, `clientsecret`, `sshkeys` do), and over-deep
  subtrees are redacted wholesale. The configured API key and bearer tokens
  are scrubbed by value from the whole error text (message, hint, details,
  upstream HTTP bodies). Other secrets in free text or under non-secret key
  names are not detected.
- GraphQL error `extensions` are no longer forwarded wholesale: only
  `extensions.code` (a string) reaches the client, every other key is dropped.
- Tool errors are logged once at the boundary
  (`unraid <domain>.<action> failed: <code>: <message>`), scrubbed the same
  way, with control characters escaped; no details or traceback. A failed
  elicitation is not logged separately (the boundary line records the
  `confirmation_required` refusal).
- These guarantees cover structured `UnraidError` failures only; unexpected
  exceptions keep FastMCP's generic text and a full traceback in the log,
  unscrubbed.

### Breaking

- HTTP transport refuses to start without a token file.
- A wildcard bind requires `MCP_ALLOWED_HOSTS`.
- The image now defaults both `*_FILE` vars, so an `UNRAID_API_KEY` set in the
  env must be removed.
- FastMCP's native Host/Origin guard is pinned off.

## 0.1.0 — 2026-09-12

Initial release.

- Single `unraid(domain, action, **params)` MCP tool targeting Unraid 7.3.2 /
  `unraid-api` 4.35.1 via the `/graphql` endpoint on the standard web port.
- Nine domains: system, array, docker, vm, share, notification, metrics, logs,
  health.
- Two independent write locks: server-level (`UNRAID_ALLOW_WRITES`) and
  call-level (`confirm` / elicitation).
- Contract tests validate every registered GraphQL document against the vendored
  SDL snapshot.
- Repaired SDL: `InfoCpu.topology` field added (present in live introspection,
  missing from the published schema).

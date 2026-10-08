# Changelog

## Unreleased

### Added

- HTTP bearer auth with source-IP, Host and Origin allowlists.
- `/health` endpoint (GET/HEAD).
- `UNRAID_API_KEY_FILE` to read the API key from a file.

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

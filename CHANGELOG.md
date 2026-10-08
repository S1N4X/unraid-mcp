# Changelog

## Unreleased

### Added

- HTTP bearer auth with source-IP, Host and Origin allowlists.
- `/health` endpoint (GET/HEAD).
- `UNRAID_API_KEY_FILE` to read the API key from a file.
- `deploy/my-unraid-mcp.xml` (canonical dockerMan template) and
  `deploy/deploy.sh` (with `--dry-run`; backs up the template, autostart file,
  secret owners/modes and previous image before shipping, checks that the
  shipped and running image is the one it built, and prints the restore
  commands when any step from the backup on fails).
- `tests/test_deploy_assets.py`: checks the template's host network, bind
  (matches `deploy.sh`) and hardening flags, and the Dockerfile's non-root
  user, venv `CMD` and lack of bind defaults.
- `tests/test_deploy_dry_run.py`: runs `deploy.sh --dry-run` with docker and
  ssh faked: nothing is called, the nine steps run in order, a missing or
  invalid `--backup-suffix` exits 2.
- `tests/test_live_http.py`: live HTTP smoke of a deployed server, opt-in via
  `UNRAID_MCP_LIVE_URL`.

### Fixed

- The monolith deployment hung on every upstream read: macvlan host isolation
  kept the container from reaching its own host (#360). It now runs on the
  host network and reads the API at `http://127.0.0.1/graphql`.
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
- The image runs as uid/gid 10078: the secret files and the appdata directory
  must be owned by 10078.
- The image no longer defaults `FASTMCP_HOST=0.0.0.0`/`FASTMCP_PORT=8000`: set
  `MCP_HOST`/`MCP_PORT` (unset binds `127.0.0.1:8000`).
- `EXPOSE 8000` is dropped.
- `CMD` runs the venv python directly with `PYTHONDONTWRITEBYTECODE=1`, so the
  image works on a read-only root.

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

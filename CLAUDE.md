# unraid-mcp

MCP server for the official Unraid GraphQL API (Unraid 7.3.2 / unraid-api 4.35.1).

## Stack

- Python ≥3.11 (uv-managed), FastMCP 4.x, httpx, graphql-core
- Single `unraid(domain, action, params, confirm)` tool — 9 domains, 50 actions
- Vendored SDL in `src/unraid_mcp/schema/` — every GraphQL document is validated against it

## Commands

```bash
uv sync                          # install deps
uv run pytest                    # full suite (676 tests, ≥90% coverage gate)
uv run ruff check .              # lint
uv run ruff format --check .     # format check
uv run mypy                      # strict type check
UNRAID_LIVE=1 uv run --env-file .env pytest tests/test_live.py  # live smoke (read-only)
```

## Architecture

- `settings.py` — `Settings.from_env()` called once in `__main__.py`; no module-level env reads; `read_key_file` / `UNRAID_API_KEY_FILE`
- `http_auth.py` — `load_http_auth_config(env)` + ASGI `AuthGuard` (IP → Host → Origin → GET/HEAD /health → bearer); loaded only for `UNRAID_TRANSPORT=http`
- `client.py` — pooled httpx, retries (non-mutations only), error mapping; GraphQL `extensions` allowlist (only `code` forwarded); HTTP body excerpts scrubbed via `value_secrets`
- `errors.py` — `UnraidError` hierarchy; `to_client_text()` = compact JSON (code/message/hint/details), details redacted
- `redaction.py` — `redact()` by key name for error details: segment match (key(s)/apikey(s)/token/secret/password/pwd/auth/cookie/session/credential…, singular or plural) or unambiguous substring (password/secret/apikey/accesskey/privatekey/sshkey/token/credential/authorization/cookie/bearer/session; `key`/`auth`/`pwd` stay segment-only); fail-closed depth limit. `scrub_text()` + `value_secrets()` mask the configured API key (≥8 chars) and bearer tokens by value. Not detected: other secrets in free text or under non-matching key names
- `registry.py` — `Action` entries with GraphQL documents; `execute_action()` dispatcher
- `domains/*.py` — one module per domain, each exports `ACTIONS: dict[str, Action]`
- `server.py` — FastMCP wiring, write gate (two locks: env + confirm/elicitation answered exactly "yes"); the tool logs `unraid <domain>.<action> failed: <code>: <message>` and re-raises `UnraidError` as `ToolError(to_client_text())`, both scrubbed of the API key/bearer tokens (log fields control-char escaped). Non-`UnraidError` exceptions are not scrubbed (generic FastMCP text + `logger.exception` traceback)
- `responses.py` — `cap_list()` + `finalize()` for bounded, valid-JSON responses

## Safety

1. Writes disabled unless `UNRAID_ALLOW_WRITES=1`
2. Each write requires `confirm=True` or an accepted MCP elicitation answered exactly `"yes"` (FastMCP 4: elicitation only on legacy connections)
3. Use a VIEWER-role API key for read-only deployments
4. HTTP transport fails closed (token file required)

## Testing

- `test_contract.py` — validates all GraphQL documents against the vendored SDL
- `test_registry.py` — action set matches SPEC, flags consistent
- `test_mock_server.py` — in-process GraphQL server with real SDL + stub resolvers
- `test_guards.py` — write gate: both locks, elicitation answers (yes/no/None/""/case), declined/cancelled, not-implemented
- `test_server.py` — real FastMCP `Client` path: structured error text, extensions allowlist, API-key scrubbing of error text and the boundary log line, elicitation over legacy and 2026-07-28 connections
- `test_client.py` — retries, timeouts, error mapping, redaction helpers (segment + substring keys, depth, body scrubbing, value_secrets)
- `test_http_auth.py` — auth config loading and AuthGuard checks
- `test_http_app.py` — HTTP app wiring end-to-end through the guard
- `test_live.py` — opt-in (`UNRAID_LIVE=1`) read-only smoke against a real server

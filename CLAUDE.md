# unraid-mcp

MCP server for the official Unraid GraphQL API (Unraid 7.3.2 / unraid-api 4.35.1).

## Stack

- Python ≥3.11 (uv-managed), FastMCP 4.x, httpx, graphql-core
- Single `unraid(domain, action, params, confirm)` tool — 9 domains, 50 actions
- Vendored SDL in `src/unraid_mcp/schema/` — every GraphQL document is validated against it

## Commands

```bash
uv sync                          # install deps
uv run pytest                    # full suite (296 tests, ≥90% coverage gate)
uv run ruff check .              # lint
uv run ruff format --check .     # format check
uv run mypy                      # strict type check
UNRAID_LIVE=1 uv run --env-file .env pytest tests/test_live.py  # live smoke (read-only)
```

## Architecture

- `settings.py` — `Settings.from_env()` called once in `__main__.py`; no module-level env reads
- `client.py` — pooled httpx, retries (non-mutations only), secret redaction
- `registry.py` — `Action` entries with GraphQL documents; `execute_action()` dispatcher
- `domains/*.py` — one module per domain, each exports `ACTIONS: dict[str, Action]`
- `server.py` — FastMCP wiring, write gate (two locks: env + confirm/elicitation)
- `responses.py` — `cap_list()` + `finalize()` for bounded, valid-JSON responses

## Safety

1. Writes disabled unless `UNRAID_ALLOW_WRITES=1`
2. Each write requires `confirm=True` or accepted MCP elicitation
3. Use a VIEWER-role API key for read-only deployments

## Testing

- `test_contract.py` — validates all GraphQL documents against the vendored SDL
- `test_registry.py` — action set matches SPEC, flags consistent
- `test_mock_server.py` — in-process GraphQL server with real SDL + stub resolvers
- `test_guards.py` — write gate: both locks, elicitation paths, not-implemented
- `test_client.py` — retries, timeouts, error mapping, redaction
- `test_live.py` — opt-in (`UNRAID_LIVE=1`) read-only smoke against a real server

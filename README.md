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
| `UNRAID_API_KEY` | — (required) | API key from `unraid-api apikey --create` |
| `UNRAID_API_URL` | `http://{host}/graphql` | Full endpoint override |
| `UNRAID_ALLOW_WRITES` | `0` | Master write switch |
| `UNRAID_VERIFY_SSL` | `1` | `0` or path to CA bundle |
| `UNRAID_TIMEOUT` | `30` | Read timeout in seconds |
| `UNRAID_MAX_RESPONSE_BYTES` | `40000` | Response cap |
| `UNRAID_TRANSPORT` | `stdio` | `stdio` or `http` |
| `UNRAID_LOG_LEVEL` | `INFO` | Logging level |

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

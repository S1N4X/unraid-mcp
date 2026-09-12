# unraid-mcp — v1 specification

A small, correct, well-tested MCP server for Unraid, built on the **official Unraid GraphQL API**.
Ground truth: Unraid **7.3.2**, `unraid-api` **4.35.1**, schema snapshot in `schema/unraid-api-4.35.1.graphql`
(introspected from the live server on 2026-09-12).

## 0. Why another one

| Existing | Fatal flaw we fix |
|---|---|
| jmagar/dinglebear | 3 languages, 280 source files, OIDC/Google-auth/rclone/incus — unmaintainable |
| TheTechChild | config read at import time (untestable); advertises actions the API does not have |
| theippenguin | no tests, no retries, no write gating |
| ruaan-deysel | runs *on* the server as root; bypasses the official API |
| **all four** | hardcode port **31337** (wrong on 7.3.x — the endpoint is `/graphql` on the normal web port); no schema-drift detection; unbounded responses |

## 1. Non-goals (v1)

Explicitly **not** implemented: disk add/remove, `clearArrayDiskStatistics`, `removeContainer`,
VM `forceStop`/`reset`, API-key mutations, OIDC, rclone, `updateSettings`, flash backup,
plugin install/remove, GraphQL subscriptions. Each is a documented `not_implemented` error naming
the reason, never a silent failure.

## 2. Architecture

```
src/unraid_mcp/
  __init__.py
  __main__.py        # entrypoint: build Settings -> build server -> run
  settings.py        # Settings dataclass, from_env(); NO import-time env reads
  client.py          # UnraidClient: pooled httpx, retries, error mapping, redaction
  errors.py          # UnraidError hierarchy -> structured MCP errors
  responses.py       # cap_list(), truncation marker, json encoder
  registry.py        # ACTIONS: dict[(domain, action)] -> Action(...)
  server.py          # FastMCP wiring, the single `unraid` tool, write gate
  domains/
    system.py array.py docker.py vm.py share.py notification.py
    metrics.py logs.py health.py
schema/              # vendored introspection JSON + SDL snapshot
tests/
```

Hard rules:
- **No module-level environment reads.** `Settings.from_env()` is called once in `__main__`;
  everything else receives `Settings` / `UnraidClient` by injection. This is what makes the
  whole surface testable without monkeypatching `os.environ`.
- **Every GraphQL document lives in a registry entry**, never inline in a handler. That is what
  lets the contract test validate all of them against the schema snapshot.
- One module per domain, one `Action` per capability. No class hierarchies.

## 3. Tool surface

**One** MCP tool: `unraid(domain: str, action: str, **params)`. Rationale: a single tool schema
costs ~2k tokens of context; 90 flat tools cost ~25k.

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

`unraid("health", "capabilities")` returns the full action table with each action's
`writes`/`destructive`/`implemented` flags — self-describing, so the agent never guesses.

`docker restart` = `stop` then `start` (the API has no restart mutation); documented as such.

## 4. Safety model — two independent locks

1. **Server-level:** writes are refused unless `UNRAID_ALLOW_WRITES=1`. Default is read-only.
   Refusal is a structured `write_disabled` error naming the env var.
2. **Call-level:** every write action requires `confirm=True`, or an MCP elicitation the user
   accepts. No elicitation support in the client + no `confirm` ⇒ refuse.

Additionally, the README instructs using a **VIEWER-role API key** for read-only deployments —
Unraid supports fine-grained `RESOURCE:ACTION` permissions, so defence in depth is free.

## 5. Robustness requirements

| Concern | Requirement |
|---|---|
| Endpoint | Default `http://{UNRAID_HOST}/graphql`; `UNRAID_API_URL` overrides. Probe `:31337` only if explicitly configured. |
| Auth | `X-API-Key` header. Key never logged; `_redact()` covers key/token/secret/password/apikey recursively. |
| Timeouts | connect 5 s, read 30 s; `disk`/`logs` profile read 90 s. |
| Retries | 2 retries with exponential backoff + jitter on connect errors, 502/503/504 only. **Never retry a mutation.** |
| Pooling | One `httpx.AsyncClient` per server instance, closed on lifespan shutdown. No module-level singleton. |
| Errors | GraphQL `errors[]` mapped by `extensions.code` → `UnauthorizedError`, `NotFoundError`, `IntrospectionDisabledError`, `UpstreamError`. HTTP 401/403 → `UnauthorizedError` with a "check API key roles" hint. |
| Response size | `cap_list(items, limit, default=20, byte_budget=...)` + a `_meta.truncated` block. Over-cap results are replaced by a **valid JSON** `response_truncated` marker with a narrowing hint — never a mid-string cut. |
| Idempotency | "already started/stopped", HTTP 304 → success with `idempotent: true`. |
| Drift | `health.schema_check` validates every registered document against the vendored SDL; if live introspection is enabled it also diffs live vs. snapshot and reports added/removed fields. |

## 6. Test plan (all offline except the opt-in live suite)

| Suite | What it proves |
|---|---|
| `test_contract.py` | **Every** registered GraphQL document parses and `graphql.validate()`s clean against `schema/unraid-api-4.35.1.graphql`. Catches a typo'd field or an API-version drift at CI time, not in production. |
| `test_registry.py` | Registry is internally consistent: no orphan handler, no undeclared action, every write flagged, `health.capabilities` output matches the registry exactly, docstrings present. |
| `test_mock_server.py` | An in-process GraphQL server built from the **real SDL** with stub resolvers, wired to the client via `httpx.MockTransport`. Each read action is executed end-to-end and its response shape asserted. Responses are therefore schema-checked in both directions. |
| `test_guards.py` | Write refused with `UNRAID_ALLOW_WRITES` unset; refused without `confirm`; accepted with both; elicitation accept/decline paths; destructive not-implemented actions refuse with a named reason. |
| `test_client.py` | Retry only on the retryable set; **no retry on mutations**; backoff bounded; timeout profiles; redaction of secrets in logs and in error text; GraphQL error-code mapping; malformed JSON handling. |
| `test_responses.py` | `cap_list` count + byte budget, always ≥1 item, `limit<=0` returns all; truncation marker is valid JSON and stays under the cap. |
| `test_settings.py` | `from_env` defaults, URL derivation, bool parsing (`true/1/yes`), missing-required errors name the variable, no import-time side effects (importing every module with a blank environ must not raise). |
| `test_live.py` | Opt-in via `UNRAID_LIVE=1`: read-only smoke against a real server (`health.ping`, `system.info`, `docker.list`). Skipped by default. |

Coverage gate: ≥90 % on `src/unraid_mcp`, enforced in CI. `ruff` + `mypy --strict` clean.

## 7. Distribution

`uvx unraid-mcp` / `pipx`; PyPI package `unraid-mcp`; MIT; GitHub Actions CI (lint, type, test,
coverage) on 3.11/3.12/3.13; `README.md` with a one-line Claude Code install and a security
section; `SECURITY.md`; `CHANGELOG.md`.

## 8. Configuration

| Env var | Default | Meaning |
|---|---|---|
| `UNRAID_HOST` | — (required unless `UNRAID_API_URL`) | Hostname/IP of the Unraid server |
| `UNRAID_API_KEY` | — (required) | API key from `unraid-api apikey --create` |
| `UNRAID_API_URL` | `http://{host}/graphql` | Full endpoint override |
| `UNRAID_ALLOW_WRITES` | `0` | Master write switch |
| `UNRAID_VERIFY_SSL` | `1` | `0`/path-to-CA-bundle supported |
| `UNRAID_TIMEOUT` | `30` | Read timeout seconds |
| `UNRAID_MAX_RESPONSE_BYTES` | `40000` | Response cap |
| `UNRAID_TRANSPORT` | `stdio` | `stdio` or `http` |
| `UNRAID_LOG_LEVEL` | `INFO` | — |

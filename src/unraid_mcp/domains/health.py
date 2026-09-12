"""Health domain: ping, schema_check, capabilities."""

from __future__ import annotations

import importlib.resources
import time
from typing import Any

from graphql import build_schema, validate
from graphql import parse as gql_parse

from unraid_mcp.registry import Action, ActionContext, identity_shape, no_variables
from unraid_mcp.responses import finalize

_PING_QUERY = """\
query {
  info {
    os { hostname }
  }
}
"""


def load_snapshot_schema() -> str:
    """Load the vendored SDL snapshot via importlib.resources."""
    files = importlib.resources.files("unraid_mcp.schema")
    return (files / "unraid-api-4.35.1.graphql").read_text(encoding="utf-8")


async def _ping_run(ctx: ActionContext, params: dict[str, Any]) -> Any:
    """Timed ping: execute a trivial query and report latency."""
    t0 = time.monotonic()
    data = await ctx.client.execute(_PING_QUERY)
    elapsed_ms = round((time.monotonic() - t0) * 1000, 1)
    hostname = None
    if isinstance(data, dict):
        info = data.get("info")
        if isinstance(info, dict):
            os_info = info.get("os")
            if isinstance(os_info, dict):
                hostname = os_info.get("hostname")
    return {
        "status": "ok",
        "latency_ms": elapsed_ms,
        "hostname": hostname,
    }


async def _schema_check_run(ctx: ActionContext, params: dict[str, Any]) -> Any:
    """Validate all registered documents against the vendored SDL."""
    sdl = load_snapshot_schema()
    schema = build_schema(sdl)

    from unraid_mcp.registry import get_actions

    actions = get_actions()
    results: list[dict[str, Any]] = []
    all_valid = True

    for (domain, action), act in sorted(actions.items()):
        if not act.document:
            continue
        try:
            doc = gql_parse(act.document)
            errors = validate(schema, doc)
            if errors:
                all_valid = False
                results.append(
                    {
                        "action": f"{domain}.{action}",
                        "valid": False,
                        "errors": [str(e) for e in errors],
                    }
                )
            else:
                results.append(
                    {
                        "action": f"{domain}.{action}",
                        "valid": True,
                    }
                )
        except Exception as exc:
            all_valid = False
            results.append(
                {
                    "action": f"{domain}.{action}",
                    "valid": False,
                    "errors": [str(exc)],
                }
            )

    budget = ctx.settings.max_response_bytes
    return finalize({"all_valid": all_valid, "checks": results}, budget)


async def _capabilities_run(ctx: ActionContext, params: dict[str, Any]) -> Any:
    """Return the full action table with flags."""
    from unraid_mcp.registry import get_actions

    actions = get_actions()
    table: list[dict[str, Any]] = []
    for (domain, action), act in sorted(actions.items()):
        table.append(
            {
                "domain": domain,
                "action": action,
                "doc": act.doc,
                "writes": act.writes,
                "destructive": act.destructive,
                "implemented": act.implemented,
            }
        )

    budget = ctx.settings.max_response_bytes
    return finalize({"actions": table}, budget)


ACTIONS: dict[tuple[str, str], Action] = {
    ("health", "ping"): Action(
        doc="Timed health check against the Unraid API.",
        document=_PING_QUERY,
        variables=no_variables,
        shape=identity_shape,
        run=_ping_run,
    ),
    ("health", "schema_check"): Action(
        doc="Validate all registered GraphQL documents against the schema snapshot.",
        document="",
        variables=no_variables,
        shape=identity_shape,
        run=_schema_check_run,
    ),
    ("health", "capabilities"): Action(
        doc="List all available actions with flags.",
        document="",
        variables=no_variables,
        shape=identity_shape,
        run=_capabilities_run,
    ),
}

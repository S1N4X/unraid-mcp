"""Action registry: maps (domain, action) to Action descriptors."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from unraid_mcp.client import UnraidClient
from unraid_mcp.errors import (
    InvalidParamsError,
    NotImplementedActionError,
    UnknownActionError,
)
from unraid_mcp.responses import cap_list, finalize
from unraid_mcp.settings import Settings


class RunFn(Protocol):
    async def __call__(self, ctx: ActionContext, params: dict[str, Any]) -> Any: ...


class VariablesFn(Protocol):
    def __call__(self, params: dict[str, Any]) -> dict[str, Any] | None: ...


class ShapeFn(Protocol):
    def __call__(self, data: Any, params: dict[str, Any], budget: int) -> Any: ...


@dataclass(frozen=True)
class ActionContext:
    """Runtime context passed to action handlers."""

    client: UnraidClient
    settings: Settings
    actions: dict[tuple[str, str], Action]


@dataclass(frozen=True)
class Action:
    """Descriptor for one (domain, action) pair."""

    doc: str
    document: str
    variables: VariablesFn
    shape: ShapeFn
    run: RunFn | None = None
    writes: bool = False
    destructive: bool = False
    implemented: bool = True
    reason: str = ""
    profile: str | None = None


# ---------------------------------------------------------------------------
# Helpers for common patterns
# ---------------------------------------------------------------------------


def no_variables(params: dict[str, Any]) -> dict[str, Any] | None:
    """No variables needed."""
    return None


def identity_shape(data: Any, params: dict[str, Any], budget: int) -> Any:
    """Pass data through, applying finalize."""
    return finalize(data, budget)


def require_str(params: dict[str, Any], key: str) -> str:
    """Extract a required string parameter, raising InvalidParamsError."""
    val = params.get(key)
    if not val or not isinstance(val, str):
        raise InvalidParamsError(f"Required parameter '{key}' (string) is missing.")
    return val


def id_variables(params: dict[str, Any]) -> dict[str, Any] | None:
    """Extract 'id' from params for use as a GraphQL variable."""
    return {"id": require_str(params, "id")}


def list_shape(key: str) -> ShapeFn:
    """Return a shape function that caps a list under *key*."""

    def _shape(data: Any, params: dict[str, Any], budget: int) -> Any:
        if not isinstance(data, dict):
            return finalize(data, budget)
        items = data.get(key)
        if not isinstance(items, list):
            return finalize(data, budget)
        limit = params.get("limit")
        if isinstance(limit, str):
            limit = int(limit)
        return finalize(cap_list(items, limit, byte_budget=budget), budget)

    return _shape


def not_implemented(reason: str) -> Action:
    """Convenience for an unimplemented action stub."""
    return Action(
        doc=f"Not implemented: {reason}",
        document="",
        variables=no_variables,
        shape=identity_shape,
        implemented=False,
        reason=reason,
    )


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


async def execute_action(
    ctx: ActionContext,
    domain: str,
    action: str,
    params: dict[str, Any],
) -> Any:
    """Look up and execute a registered action."""
    key = (domain, action)
    act = ctx.actions.get(key)
    if act is None:
        raise UnknownActionError(
            f"Unknown action '{domain}.{action}'.",
            hint="Use health.capabilities to list available actions.",
        )

    if not act.implemented:
        raise NotImplementedActionError(
            f"'{domain}.{action}' is not implemented: {act.reason}",
        )

    if act.run is not None:
        return await act.run(ctx, params)

    variables = act.variables(params)
    data = await ctx.client.execute(act.document, variables, profile=act.profile)
    budget = ctx.settings.max_response_bytes
    return act.shape(data, params, budget)


# ---------------------------------------------------------------------------
# ACTIONS dict — built lazily to avoid circular imports
# ---------------------------------------------------------------------------

_ACTIONS: dict[tuple[str, str], Action] | None = None


def get_actions() -> dict[tuple[str, str], Action]:
    """Return the global ACTIONS dict, building it on first call."""
    global _ACTIONS  # noqa: PLW0603
    if _ACTIONS is not None:
        return _ACTIONS

    from unraid_mcp.domains.array import ACTIONS as array_actions
    from unraid_mcp.domains.docker import ACTIONS as docker_actions
    from unraid_mcp.domains.health import ACTIONS as health_actions
    from unraid_mcp.domains.logs import ACTIONS as logs_actions
    from unraid_mcp.domains.metrics import ACTIONS as metrics_actions
    from unraid_mcp.domains.notification import ACTIONS as notification_actions
    from unraid_mcp.domains.share import ACTIONS as share_actions
    from unraid_mcp.domains.system import ACTIONS as system_actions
    from unraid_mcp.domains.vm import ACTIONS as vm_actions

    _ACTIONS = {}
    for module_actions in [
        system_actions,
        array_actions,
        docker_actions,
        vm_actions,
        share_actions,
        notification_actions,
        metrics_actions,
        logs_actions,
        health_actions,
    ]:
        _ACTIONS.update(module_actions)

    return _ACTIONS

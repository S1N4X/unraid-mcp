"""FastMCP server wiring: single ``unraid`` tool with write gate."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any, Protocol

from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.elicitation import AcceptedElicitation

from unraid_mcp.client import UnraidClient
from unraid_mcp.errors import (
    ConfirmationRequiredError,
    NotImplementedActionError,
    UnknownActionError,
    UnraidError,
    WriteDisabledError,
)
from unraid_mcp.registry import ActionContext, execute_action, get_actions
from unraid_mcp.responses import to_json
from unraid_mcp.settings import Settings

logger = logging.getLogger(__name__)


class ElicitFn(Protocol):
    """Protocol matching ctx.elicit signature."""

    async def __call__(self, message: str, response_type: Any) -> Any: ...


async def handle_unraid(
    domain: str,
    action: str,
    settings: Settings,
    client: UnraidClient,
    elicit: ElicitFn | None = None,
    params: dict[str, Any] | None = None,
    confirm: bool = False,
) -> str:
    """Core logic for the ``unraid`` tool, testable without FastMCP context."""
    if params is None:
        params = {}

    actions = get_actions()
    key = (domain, action)
    act = actions.get(key)

    if act is None:
        raise UnknownActionError(
            f"Unknown action '{domain}.{action}'.",
            hint="Use health.capabilities to list available actions.",
        )

    if not act.implemented:
        raise NotImplementedActionError(
            f"'{domain}.{action}' is not implemented: {act.reason}",
        )

    # Write gate
    if act.writes:
        if not settings.allow_writes:
            raise WriteDisabledError(
                "Write operations are disabled.",
                hint="Set UNRAID_ALLOW_WRITES=1 to enable.",
            )

        if not confirm:
            if elicit is None:
                raise ConfirmationRequiredError(
                    f"'{domain}.{action}' requires confirmation. Pass confirm=True.",
                )
            try:
                result = await elicit(
                    f"Confirm write action '{domain}.{action}'?",
                    ["yes", "no"],
                )
                if isinstance(result, AcceptedElicitation):
                    pass  # Accepted, proceed
                else:
                    raise ConfirmationRequiredError(
                        f"'{domain}.{action}' requires confirmation. "
                        "Pass confirm=True or accept the elicitation.",
                    )
            except (ToolError, Exception) as exc:
                # ToolError on modern connections, other exceptions on legacy
                if isinstance(exc, (ConfirmationRequiredError, WriteDisabledError)):
                    raise
                raise ConfirmationRequiredError(
                    f"'{domain}.{action}' requires confirmation. "
                    "Pass confirm=True or accept the elicitation.",
                ) from exc

    request_ctx = ActionContext(
        client=client,
        settings=settings,
        actions=actions,
    )

    try:
        data = await execute_action(request_ctx, domain, action, params)
    except UnraidError:
        raise
    except Exception:
        logger.exception("Unexpected error in %s.%s", domain, action)
        raise

    return to_json(data)


def build_server(
    settings: Settings,
    transport: Any | None = None,
) -> FastMCP:
    """Create a configured FastMCP server."""
    _transport = transport

    @asynccontextmanager
    async def lifespan(app: FastMCP):  # type: ignore[no-untyped-def]
        client = UnraidClient(settings, transport=_transport)
        try:
            yield {"client": client, "settings": settings}
        finally:
            await client.close()

    mcp = FastMCP("unraid-mcp", lifespan=lifespan)

    @mcp.tool()
    async def unraid(
        domain: str,
        action: str,
        ctx: Context,
        params: dict[str, Any] | None = None,
        confirm: bool = False,
    ) -> str:
        """Single entry point for all Unraid operations.

        Use health.capabilities to discover available actions.
        """
        client: UnraidClient = ctx.request_context.lifespan_context["client"]  # type: ignore[union-attr]
        return await handle_unraid(
            domain=domain,
            action=action,
            settings=settings,
            client=client,
            elicit=ctx.elicit,
            params=params,
            confirm=confirm,
        )

    return mcp

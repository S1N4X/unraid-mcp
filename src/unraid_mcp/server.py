"""FastMCP server wiring: single ``unraid`` tool with write gate."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any, Protocol

from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.elicitation import AcceptedElicitation
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from unraid_mcp.client import UnraidClient
from unraid_mcp.errors import (
    ConfirmationRequiredError,
    NotImplementedActionError,
    UnknownActionError,
    UnraidError,
    WriteDisabledError,
)
from unraid_mcp.redaction import scrub_text, value_secrets
from unraid_mcp.registry import ActionContext, execute_action, get_actions
from unraid_mcp.responses import to_json
from unraid_mcp.settings import Settings

logger = logging.getLogger(__name__)


def _log_safe(text: str) -> str:
    """*text* with newlines and other control characters backslash-escaped."""
    if text.isprintable():
        return text
    return "".join(ch if ch.isprintable() else repr(ch)[1:-1] for ch in text)


class ElicitFn(Protocol):
    """Protocol matching ctx.elicit signature."""

    async def __call__(self, message: str, response_type: Any) -> Any: ...


CONFIRM_YES = "yes"


def is_confirmed(result: Any) -> bool:
    """Return True only for an accepted elicitation whose answer is exactly ``"yes"``.

    The prompt offers the choices ``["yes", "no"]``.  Accepting the prompt is not
    consent by itself: FastMCP returns ``AcceptedElicitation(data="no")`` when the
    user accepts and picks "no".  The match is exact and case-sensitive, with no
    whitespace stripping: a client must send back one of the offered choices, and
    anything else (``"no"``, ``"YES"``, ``" yes"``, ``""``, ``None``, non-strings,
    declined or cancelled results) refuses the write.
    """
    return isinstance(result, AcceptedElicitation) and result.data == CONFIRM_YES


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
                    [CONFIRM_YES, "no"],
                )
            except Exception as exc:
                # ToolError on modern connections, other exceptions on legacy
                # clients without elicitation support.  Not logged here: the
                # tool boundary logs the resulting confirmation_required error.
                raise ConfirmationRequiredError(
                    f"'{domain}.{action}' requires confirmation, but the confirmation "
                    "prompt could not be shown. Pass confirm=True.",
                ) from exc
            if not is_confirmed(result):
                raise ConfirmationRequiredError(
                    f"'{domain}.{action}' was not confirmed: the elicitation was not "
                    f"accepted with the answer '{CONFIRM_YES}'. Nothing was changed.",
                    hint="Answer 'yes' to the confirmation prompt, or pass confirm=True.",
                )

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
        try:
            return await handle_unraid(
                domain=domain,
                action=action,
                settings=settings,
                client=client,
                elicit=ctx.elicit,
                params=params,
                confirm=confirm,
            )
        except UnraidError as exc:
            # FastMCP passes a ToolError's text to the client verbatim; any other
            # exception becomes "Error calling tool 'unraid': <message>", which
            # drops code, hint and details.  Details are redacted by key name;
            # the configured API key and Bearer tokens are scrubbed by value
            # from the whole text and from the log line.  domain, action and
            # message are caller/upstream-influenced: control characters are
            # escaped so they cannot forge extra log lines.
            secrets = value_secrets(settings.api_key)
            logger.warning(
                "unraid %s.%s failed: %s: %s",
                _log_safe(domain),
                _log_safe(action),
                exc.code,
                _log_safe(scrub_text(exc.message, secrets)),
            )
            raise ToolError(scrub_text(exc.to_client_text(), secrets)) from exc

    # Liveness probe; the HTTP AuthGuard exempts exactly GET/HEAD /health from the
    # bearer check (Starlette answers HEAD for a GET route).  Unused on stdio.
    @mcp.custom_route("/health", methods=["GET"])
    async def health(request: Request) -> Response:
        return JSONResponse({"status": "ok"})

    return mcp

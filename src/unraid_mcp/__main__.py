"""Entrypoint for the Unraid MCP server."""

from __future__ import annotations

import logging

from starlette.middleware import Middleware

from unraid_mcp.http_auth import (
    AuthGuard,
    HttpAuthConfigError,
    describe_http_auth,
    load_http_auth_config,
)
from unraid_mcp.server import build_server
from unraid_mcp.settings import Settings

logger = logging.getLogger(__name__)


def main() -> None:
    """Build settings from env and run the server."""
    try:
        settings = Settings.from_env()
    except ValueError as exc:
        raise SystemExit(f"unraid-mcp: {exc}") from None

    if settings.transport != "http":
        build_server(settings).run(transport="stdio")
        return

    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # Fail closed before the server is even built.
    try:
        auth = load_http_auth_config()
    except HttpAuthConfigError as exc:
        raise SystemExit(f"unraid-mcp: {exc}") from None
    for warning in auth.warnings:
        logger.warning("%s", warning)
    logger.info("%s", describe_http_auth(auth))

    build_server(settings).run(
        transport="http",
        host=auth.bind_host,
        port=auth.port,
        middleware=[Middleware(AuthGuard, config=auth)],
        # The native Host/Origin guard would answer 421 ahead of AuthGuard's 403s.
        host_origin_protection=False,
        # The peer must be the socket address; never trust X-Forwarded-For.
        uvicorn_config={"proxy_headers": False, "access_log": False},
    )


if __name__ == "__main__":
    main()

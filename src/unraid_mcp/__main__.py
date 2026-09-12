"""Entrypoint for the Unraid MCP server."""

from __future__ import annotations

from unraid_mcp.server import build_server
from unraid_mcp.settings import Settings


def main() -> None:
    """Build settings from env and run the server."""
    settings = Settings.from_env()
    server = build_server(settings)
    server.run(transport=settings.transport)  # type: ignore[arg-type]


if __name__ == "__main__":
    main()

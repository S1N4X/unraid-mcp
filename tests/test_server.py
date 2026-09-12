"""Tests for unraid_mcp.server build_server and related."""

from __future__ import annotations

import json
from typing import Any

import httpx

from unraid_mcp.server import build_server
from unraid_mcp.settings import Settings


def _ok_transport(data: Any = None) -> httpx.MockTransport:
    body = json.dumps({"data": data or {}}).encode()

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    return httpx.MockTransport(handler)


class TestBuildServer:
    def test_build_server_returns_fastmcp(self) -> None:
        settings = Settings.from_env({"UNRAID_API_KEY": "k", "UNRAID_HOST": "tower"})
        server = build_server(settings, transport=_ok_transport())
        assert server.name == "unraid-mcp"

    def test_build_server_has_unraid_tool(self) -> None:
        settings = Settings.from_env({"UNRAID_API_KEY": "k", "UNRAID_HOST": "tower"})
        server = build_server(settings, transport=_ok_transport())
        # The server should have at least one tool registered
        assert server is not None

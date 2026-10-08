"""Live HTTP smoke of a deployed server — opt-in via UNRAID_MCP_LIVE_URL (#360)."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from mcp_types import TextContent

from unraid_mcp.http_auth import AUTH_CHALLENGE

LIVE_URL = os.environ.get("UNRAID_MCP_LIVE_URL", "").strip().rstrip("/")
TIMEOUT_S = 15.0

pytestmark = pytest.mark.skipif(
    not LIVE_URL,
    reason="set UNRAID_MCP_LIVE_URL (e.g. http://10.10.10.50:8078)",
)


@pytest.fixture(scope="module")
def token() -> str:
    """Read the bearer token from the token file; never echo its value."""
    path = Path(
        os.environ.get("UNRAID_MCP_TOKEN_FILE") or "~/.config/unraid-mcp/http-token"
    ).expanduser()
    value = path.read_text().strip()
    if not value:
        pytest.fail("token file is empty")
    return value


async def _call_unraid(token: str, arguments: dict[str, Any]) -> Any:
    transport = StreamableHttpTransport(
        f"{LIVE_URL}/mcp", headers={"Authorization": f"Bearer {token}"}
    )
    async with asyncio.timeout(TIMEOUT_S), Client(transport, timeout=TIMEOUT_S) as client:
        result = await client.call_tool("unraid", arguments, raise_on_error=False)
    text = "".join(c.text for c in result.content if isinstance(c, TextContent))
    assert not result.is_error, text
    return json.loads(text)


async def test_health_ok() -> None:
    async with httpx.AsyncClient(timeout=TIMEOUT_S) as http:
        response = await http.get(f"{LIVE_URL}/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_mcp_without_token_is_401() -> None:
    async with httpx.AsyncClient(timeout=TIMEOUT_S) as http:
        response = await http.post(f"{LIVE_URL}/mcp", json={})
    assert response.status_code == 401
    assert response.headers.get("www-authenticate") == AUTH_CHALLENGE


async def test_health_ping(token: str) -> None:
    result = await _call_unraid(token, {"domain": "health", "action": "ping"})
    assert result["status"] == "ok"


async def test_system_time(token: str) -> None:
    result = await _call_unraid(token, {"domain": "system", "action": "time"})
    assert result["systemTime"]["currentTime"]

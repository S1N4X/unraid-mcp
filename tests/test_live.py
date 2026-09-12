"""Live smoke tests — opt-in via UNRAID_LIVE=1."""

from __future__ import annotations

import dataclasses
import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("UNRAID_LIVE") != "1",
    reason="set UNRAID_LIVE=1",
)


@pytest.fixture(scope="module")
def settings():  # type: ignore[no-untyped-def]
    """Build read-only settings from real environment."""
    from unraid_mcp.settings import Settings

    s = Settings.from_env()
    return dataclasses.replace(s, allow_writes=False)


@pytest.fixture()
async def ctx(settings):  # type: ignore[no-untyped-def]
    """Create a live client context."""
    from unraid_mcp.client import UnraidClient
    from unraid_mcp.registry import ActionContext, get_actions

    async with UnraidClient(settings) as client:
        yield ActionContext(client=client, settings=settings, actions=get_actions())


async def test_health_ping(ctx) -> None:  # type: ignore[no-untyped-def]
    from unraid_mcp.registry import execute_action

    result = await execute_action(ctx, "health", "ping", {})
    assert result["status"] == "ok"
    assert "latency_ms" in result


async def test_system_info(ctx) -> None:  # type: ignore[no-untyped-def]
    from unraid_mcp.registry import execute_action

    result = await execute_action(ctx, "system", "info", {})
    assert "info" in result
    assert "os" in result["info"]


async def test_docker_list(ctx) -> None:  # type: ignore[no-untyped-def]
    from unraid_mcp.registry import execute_action

    result = await execute_action(ctx, "docker", "list", {})
    assert "items" in result

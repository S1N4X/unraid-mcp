"""Tests for the health domain."""

from __future__ import annotations

from tests.mock_unraid import make_transport
from unraid_mcp.client import UnraidClient
from unraid_mcp.registry import ActionContext, execute_action, get_actions
from unraid_mcp.settings import Settings

SETTINGS = Settings(
    host="tower.local",
    api_key="test-key",
    api_url="http://tower.local/graphql",
    allow_writes=False,
    verify_ssl=False,
    timeout=30,
    max_response_bytes=40000,
    transport="stdio",
    log_level="INFO",
)


def _make_ctx() -> ActionContext:
    client = UnraidClient(SETTINGS, transport=make_transport())
    return ActionContext(client=client, settings=SETTINGS, actions=get_actions())


class TestPing:
    async def test_ping_returns_status_ok(self) -> None:
        ctx = _make_ctx()
        result = await execute_action(ctx, "health", "ping", {})
        assert isinstance(result, dict)
        assert result["status"] == "ok"
        assert "latency_ms" in result
        assert result["hostname"] == "tower"


class TestSchemaCheck:
    async def test_schema_check_all_valid(self) -> None:
        ctx = _make_ctx()
        result = await execute_action(ctx, "health", "schema_check", {})
        assert isinstance(result, dict)
        assert result["all_valid"] is True
        assert "checks" in result
        assert len(result["checks"]) > 0


class TestCapabilities:
    async def test_capabilities_returns_action_table(self) -> None:
        ctx = _make_ctx()
        result = await execute_action(ctx, "health", "capabilities", {})
        assert isinstance(result, dict)
        assert "actions" in result
        actions = result["actions"]
        assert len(actions) > 0
        # Verify structure
        first = actions[0]
        assert "domain" in first
        assert "action" in first
        assert "writes" in first
        assert "implemented" in first

    async def test_capabilities_matches_registry(self) -> None:
        ctx = _make_ctx()
        result = await execute_action(ctx, "health", "capabilities", {})
        actions_from_caps = {(a["domain"], a["action"]) for a in result["actions"]}
        registry_keys = set(get_actions().keys())
        assert actions_from_caps == registry_keys


class TestLoadSnapshot:
    def test_load_snapshot_schema(self) -> None:
        from unraid_mcp.domains.health import load_snapshot_schema

        sdl = load_snapshot_schema()
        assert "type Query" in sdl
        assert len(sdl) > 100

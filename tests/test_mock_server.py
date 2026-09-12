"""End-to-end tests using the mock GraphQL server."""

from __future__ import annotations

import json
from typing import Any

import pytest

from tests.mock_unraid import make_transport
from unraid_mcp.client import UnraidClient
from unraid_mcp.errors import InvalidParamsError, NotFoundError, UnknownActionError
from unraid_mcp.registry import ActionContext, execute_action, get_actions
from unraid_mcp.server import handle_unraid
from unraid_mcp.settings import Settings

SETTINGS = Settings(
    host="tower.local",
    api_key="test-key",
    api_url="http://tower.local/graphql",
    allow_writes=True,
    verify_ssl=False,
    timeout=30,
    max_response_bytes=40000,
    transport="stdio",
    log_level="INFO",
)

READ_ONLY_SETTINGS = Settings(
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


def _make_ctx(settings: Settings | None = None) -> ActionContext:
    s = settings or SETTINGS
    client = UnraidClient(s, transport=make_transport())
    return ActionContext(client=client, settings=s, actions=get_actions())


# All implemented read actions for parametrized testing.
_READ_ACTIONS = [
    (d, a)
    for (d, a), act in sorted(get_actions().items())
    if act.implemented and not act.writes and act.run is None and act.document
]


class TestReadActions:
    @pytest.mark.parametrize(
        "domain,action",
        _READ_ACTIONS,
        ids=[f"{d}.{a}" for d, a in _READ_ACTIONS],
    )
    async def test_read_action_returns_data(self, domain: str, action: str) -> None:
        ctx = _make_ctx()
        # Some actions need parameters
        params: dict[str, Any] = {}
        if action == "read" and domain == "logs":
            params = {"path": "/var/log/syslog"}
        if action == "get" and domain == "docker":
            params = {"id": "container:abc123"}
        if action == "logs" and domain == "docker":
            params = {"id": "container:abc123"}
        if action == "get" and domain == "vm":
            params = {"id": "vm:win10"}
        if action == "get" and domain == "share":
            params = {"name": "appdata"}
        if action == "list" and domain == "notification":
            params = {"type": "UNREAD"}

        result = await execute_action(ctx, domain, action, params)
        assert result is not None


class TestSystemDomain:
    async def test_info_has_os(self) -> None:
        ctx = _make_ctx()
        result = await execute_action(ctx, "system", "info", {})
        assert isinstance(result, dict)
        info = result.get("info")
        assert isinstance(info, dict)
        assert info["os"]["hostname"] == "tower"

    async def test_versions_has_core(self) -> None:
        ctx = _make_ctx()
        result = await execute_action(ctx, "system", "versions", {})
        assert isinstance(result, dict)
        info = result.get("info")
        assert isinstance(info, dict)
        assert info["versions"]["core"]["unraid"] == "7.3.2"


class TestArrayDomain:
    async def test_status_has_state(self) -> None:
        ctx = _make_ctx()
        result = await execute_action(ctx, "array", "status", {})
        assert isinstance(result, dict)
        assert result["array"]["state"] == "STARTED"

    async def test_disks_returns_data(self) -> None:
        ctx = _make_ctx()
        result = await execute_action(ctx, "array", "disks", {})
        assert isinstance(result, dict)
        array = result["array"]
        assert len(array["disks"]) >= 1

    async def test_parity_history(self) -> None:
        ctx = _make_ctx()
        result = await execute_action(ctx, "array", "parity_history", {})
        assert "items" in result
        assert result["_meta"]["total"] >= 1


class TestDockerDomain:
    async def test_list_returns_containers(self) -> None:
        ctx = _make_ctx()
        result = await execute_action(ctx, "docker", "list", {})
        assert "items" in result
        assert len(result["items"]) >= 1
        assert result["items"][0]["names"] == ["/plex"]

    async def test_get_returns_container(self) -> None:
        ctx = _make_ctx()
        result = await execute_action(ctx, "docker", "get", {"id": "container:abc123"})
        assert isinstance(result, dict)

    async def test_networks(self) -> None:
        ctx = _make_ctx()
        result = await execute_action(ctx, "docker", "networks", {})
        assert "items" in result

    async def test_restart_is_stop_then_start(self) -> None:
        ctx = _make_ctx()
        result = await execute_action(ctx, "docker", "restart", {"id": "container:abc123"})
        assert result is not None


class TestVmDomain:
    async def test_list_returns_domains(self) -> None:
        ctx = _make_ctx()
        result = await execute_action(ctx, "vm", "list", {})
        assert "items" in result
        assert len(result["items"]) >= 1
        assert result["items"][0]["name"] == "Windows 10"

    async def test_get_by_id_returns_single_dict(self) -> None:
        ctx = _make_ctx()
        result = await execute_action(ctx, "vm", "get", {"id": "vm:win10"})
        assert isinstance(result, dict)
        assert result["id"] == "vm:win10"
        assert result["name"] == "Windows 10"

    async def test_get_by_name_returns_single_dict(self) -> None:
        ctx = _make_ctx()
        result = await execute_action(ctx, "vm", "get", {"name": "Windows 10"})
        assert isinstance(result, dict)
        assert result["name"] == "Windows 10"

    async def test_get_unknown_id_raises_not_found(self) -> None:
        ctx = _make_ctx()
        with pytest.raises(NotFoundError):
            await execute_action(ctx, "vm", "get", {"id": "vm:nonexistent"})

    async def test_get_missing_params_raises_invalid(self) -> None:
        ctx = _make_ctx()
        with pytest.raises(InvalidParamsError):
            await execute_action(ctx, "vm", "get", {})


class TestShareDomain:
    async def test_list_returns_shares(self) -> None:
        ctx = _make_ctx()
        result = await execute_action(ctx, "share", "list", {})
        assert "items" in result
        assert len(result["items"]) >= 2

    async def test_get_by_name(self) -> None:
        ctx = _make_ctx()
        result = await execute_action(ctx, "share", "get", {"name": "appdata"})
        assert isinstance(result, dict)
        assert result.get("name") == "appdata"


class TestNotificationDomain:
    async def test_overview(self) -> None:
        ctx = _make_ctx()
        result = await execute_action(ctx, "notification", "overview", {})
        assert isinstance(result, dict)


class TestMetricsDomain:
    async def test_cpu(self) -> None:
        ctx = _make_ctx()
        result = await execute_action(ctx, "metrics", "cpu", {})
        assert isinstance(result, dict)
        assert result["metrics"]["cpu"]["percentTotal"] == 15.5

    async def test_memory(self) -> None:
        ctx = _make_ctx()
        result = await execute_action(ctx, "metrics", "memory", {})
        assert isinstance(result, dict)

    async def test_temperature(self) -> None:
        ctx = _make_ctx()
        result = await execute_action(ctx, "metrics", "temperature", {})
        assert isinstance(result, dict)


class TestLogsDomain:
    async def test_list(self) -> None:
        ctx = _make_ctx()
        result = await execute_action(ctx, "logs", "list", {})
        assert "items" in result

    async def test_read(self) -> None:
        ctx = _make_ctx()
        result = await execute_action(ctx, "logs", "read", {"path": "/var/log/syslog"})
        assert isinstance(result, dict)


class TestErrorCases:
    async def test_unknown_action(self) -> None:
        ctx = _make_ctx()
        with pytest.raises(UnknownActionError):
            await execute_action(ctx, "system", "nonexistent", {})

    async def test_missing_required_param(self) -> None:
        ctx = _make_ctx()
        with pytest.raises(InvalidParamsError):
            await execute_action(ctx, "docker", "get", {})

    async def test_share_get_missing_name(self) -> None:
        ctx = _make_ctx()
        with pytest.raises(InvalidParamsError):
            await execute_action(ctx, "share", "get", {})


class TestTruncation:
    async def test_small_budget_truncates(self) -> None:
        small_settings = Settings(
            host="tower.local",
            api_key="test-key",
            api_url="http://tower.local/graphql",
            allow_writes=False,
            verify_ssl=False,
            timeout=30,
            max_response_bytes=50,
            transport="stdio",
            log_level="INFO",
        )
        ctx = ActionContext(
            client=UnraidClient(small_settings, transport=make_transport()),
            settings=small_settings,
            actions=get_actions(),
        )
        result = await execute_action(ctx, "system", "info", {})
        # With a 50-byte budget, finalize should return a truncation marker
        assert isinstance(result, dict)
        assert result.get("response_truncated") is True


class TestHandleUnraid:
    async def test_full_roundtrip(self) -> None:
        result = await handle_unraid(
            "system",
            "info",
            READ_ONLY_SETTINGS,
            UnraidClient(READ_ONLY_SETTINGS, transport=make_transport()),
        )
        parsed = json.loads(result)
        assert isinstance(parsed, dict)
        assert "info" in parsed

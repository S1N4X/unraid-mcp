"""Guard tests: write gate, confirmation, elicitation, not-implemented, unknown."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest

from unraid_mcp.client import UnraidClient
from unraid_mcp.errors import (
    ConfirmationRequiredError,
    NotImplementedActionError,
    UnknownActionError,
    WriteDisabledError,
)
from unraid_mcp.registry import get_actions, not_implemented
from unraid_mcp.server import handle_unraid
from unraid_mcp.settings import Settings

MINIMAL_ENV = {"UNRAID_API_KEY": "test-key", "UNRAID_HOST": "tower.local"}


def _ok_transport(data: Any = None) -> httpx.MockTransport:
    body = json.dumps({"data": data or {}}).encode()

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    return httpx.MockTransport(handler)


def _settings(allow_writes: bool = False) -> Settings:
    env = {**MINIMAL_ENV}
    if allow_writes:
        env["UNRAID_ALLOW_WRITES"] = "true"
    return Settings.from_env(env)


def _client(settings: Settings | None = None) -> UnraidClient:
    s = settings or _settings()
    return UnraidClient(s, transport=_ok_transport())


class TestWriteRefused:
    async def test_write_refused_without_allow_writes(self) -> None:
        s = _settings(allow_writes=False)
        with pytest.raises(WriteDisabledError, match="disabled"):
            await handle_unraid("array", "start", s, _client(s))

    async def test_write_refused_without_confirm(self) -> None:
        s = _settings(allow_writes=True)
        with pytest.raises(ConfirmationRequiredError):
            await handle_unraid("array", "start", s, _client(s), elicit=None)


class TestWriteAllowed:
    async def test_confirm_true_bypasses(self) -> None:
        s = _settings(allow_writes=True)
        result = await handle_unraid("array", "start", s, _client(s), confirm=True)
        assert result is not None
        parsed = json.loads(result)
        assert isinstance(parsed, dict)


class TestElicitation:
    async def test_elicitation_accepted(self) -> None:
        from fastmcp.server.elicitation import AcceptedElicitation

        s = _settings(allow_writes=True)
        elicit = AsyncMock(return_value=AcceptedElicitation(data="yes"))
        result = await handle_unraid("array", "start", s, _client(s), elicit=elicit)
        assert result is not None

    async def test_elicitation_declined(self) -> None:
        from fastmcp.server.elicitation import DeclinedElicitation

        s = _settings(allow_writes=True)
        elicit = AsyncMock(return_value=DeclinedElicitation())
        with pytest.raises(ConfirmationRequiredError):
            await handle_unraid("array", "start", s, _client(s), elicit=elicit)

    async def test_elicitation_toolerror(self) -> None:
        """ToolError from elicit maps to ConfirmationRequiredError."""
        from fastmcp.exceptions import ToolError

        s = _settings(allow_writes=True)
        elicit = AsyncMock(side_effect=ToolError("not supported"))
        with pytest.raises(ConfirmationRequiredError):
            await handle_unraid("array", "start", s, _client(s), elicit=elicit)

    async def test_elicitation_generic_exception(self) -> None:
        """Generic exception from elicit maps to ConfirmationRequiredError."""
        s = _settings(allow_writes=True)
        elicit = AsyncMock(side_effect=Exception("Elicitation not supported"))
        with pytest.raises(ConfirmationRequiredError):
            await handle_unraid("array", "start", s, _client(s), elicit=elicit)


class TestNotImplemented:
    async def test_not_implemented_action(self) -> None:
        actions = get_actions()
        actions[("test", "nope")] = not_implemented("v2 feature")
        try:
            s = _settings()
            with pytest.raises(NotImplementedActionError, match="not implemented"):
                await handle_unraid("test", "nope", s, _client(s))
        finally:
            del actions[("test", "nope")]


class TestUnknownAction:
    async def test_unknown_action(self) -> None:
        s = _settings()
        with pytest.raises(UnknownActionError, match="nonexistent"):
            await handle_unraid("system", "nonexistent", s, _client(s))


class TestReadsReadOnly:
    async def test_reads_work_read_only(self) -> None:
        s = _settings(allow_writes=False)
        result = await handle_unraid("system", "info", s, _client(s))
        parsed = json.loads(result)
        assert isinstance(parsed, dict)

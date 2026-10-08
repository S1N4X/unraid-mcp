"""Tests for unraid_mcp.server build_server and related."""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx
import pytest
from fastmcp import Client
from fastmcp.client.elicitation import ElicitResult
from mcp_types import TextContent

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


# ---------------------------------------------------------------------------
# Real FastMCP tool-call path (in-memory fastmcp.Client)
# ---------------------------------------------------------------------------
def _recording_transport() -> tuple[httpx.MockTransport, list[httpx.Request]]:
    requests: list[httpx.Request] = []
    body = json.dumps({"data": {}}).encode()

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, content=body)

    return httpx.MockTransport(handler), requests


def _env(allow_writes: bool = False) -> Settings:
    env = {"UNRAID_API_KEY": "k", "UNRAID_HOST": "tower"}
    if allow_writes:
        env["UNRAID_ALLOW_WRITES"] = "1"
    return Settings.from_env(env)


async def _call(server: Any, arguments: dict[str, Any], **client_kwargs: Any) -> tuple[bool, str]:
    async with Client(server, **client_kwargs) as client:
        result = await client.call_tool("unraid", arguments, raise_on_error=False)
    text = "".join(c.text for c in result.content if isinstance(c, TextContent))
    return result.is_error, text


class TestToolErrorsReachClient:
    async def test_write_disabled_carries_code_and_hint(self) -> None:
        server = build_server(_env(), transport=_ok_transport())
        is_error, text = await _call(server, {"domain": "array", "action": "start"})
        assert is_error
        payload = json.loads(text)
        assert payload["code"] == "write_disabled"
        assert payload["message"] == "Write operations are disabled."
        assert "UNRAID_ALLOW_WRITES=1" in payload["hint"]

    async def test_unknown_action_carries_code_and_hint(self) -> None:
        server = build_server(_env(), transport=_ok_transport())
        is_error, text = await _call(server, {"domain": "nope", "action": "x"})
        assert is_error
        payload = json.loads(text)
        assert payload["code"] == "unknown_action"
        assert "health.capabilities" in payload["hint"]

    async def test_error_details_are_redacted(self) -> None:
        """Secrets in an UnraidError's details never reach the client."""

        async def handler(request: httpx.Request) -> httpx.Response:
            body = {
                "errors": [
                    {
                        "message": "upstream exploded",
                        "extensions": {
                            "code": "INTERNAL_SERVER_ERROR",
                            "apiKey": "SECRET-API-KEY-123",
                            "nested": {"token": "SECRET-TOKEN-456", "safe": "visible"},
                        },
                    }
                ]
            }
            return httpx.Response(200, content=json.dumps(body).encode())

        server = build_server(_env(), transport=httpx.MockTransport(handler))
        is_error, text = await _call(server, {"domain": "system", "action": "info"})
        assert is_error
        assert "SECRET-API-KEY-123" not in text
        assert "SECRET-TOKEN-456" not in text
        payload = json.loads(text)
        assert payload["code"] == "upstream_error"
        # Extensions are allowlisted: only "code" is forwarded.
        ext = payload["details"]["extensions"]
        assert ext == {"code": "INTERNAL_SERVER_ERROR"}
        assert "visible" not in text

    async def test_authorization_in_extensions_is_redacted(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            body = {
                "errors": [
                    {
                        "message": "upstream exploded",
                        "extensions": {
                            "request": {"headers": {"authorization": "Bearer abc-SECRET"}},
                            "Cookie": "sid=COOKIE-SECRET",
                            "sessionId": "SESSION-SECRET",
                        },
                    }
                ]
            }
            return httpx.Response(200, content=json.dumps(body).encode())

        server = build_server(_env(), transport=httpx.MockTransport(handler))
        is_error, text = await _call(server, {"domain": "system", "action": "info"})
        assert is_error
        for secret in ("abc-SECRET", "COOKIE-SECRET", "SESSION-SECRET"):
            assert secret not in text
        # No "code" extension: nothing from extensions is forwarded at all.
        assert "details" not in json.loads(text)

    async def test_non_allowlisted_extension_is_dropped(self) -> None:
        """A secret under a key name the denylist misses never reaches the client."""

        async def handler(request: httpx.Request) -> httpx.Response:
            body = {
                "errors": [
                    {
                        "message": "upstream exploded",
                        "extensions": {"smtpPass": "HUNTER2", "code": "X"},
                    }
                ]
            }
            return httpx.Response(200, content=json.dumps(body).encode())

        server = build_server(_env(), transport=httpx.MockTransport(handler))
        is_error, text = await _call(server, {"domain": "system", "action": "info"})
        assert is_error
        assert "HUNTER2" not in text
        assert "smtpPass" not in text
        payload = json.loads(text)
        assert payload["code"] == "upstream_error"
        assert payload["details"]["extensions"] == {"code": "X"}

    @pytest.mark.parametrize("status", [500, 200])
    async def test_http_body_secrets_are_scrubbed(self, status: int) -> None:
        """API key and bearer tokens in raw upstream bodies never reach the client."""
        api_key = "LONG-UNRAID-API-KEY-0123456789"
        content = f"<html>bad {api_key} Authorization: Bearer xyzTOKEN.987</html>"

        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(status, content=content.encode())

        settings = Settings.from_env({"UNRAID_API_KEY": api_key, "UNRAID_HOST": "tower"})
        server = build_server(settings, transport=httpx.MockTransport(handler))
        is_error, text = await _call(server, {"domain": "system", "action": "info"})
        assert is_error
        assert api_key not in text
        assert "xyzTOKEN.987" not in text
        payload = json.loads(text)
        assert payload["code"] == "upstream_error"
        assert "***REDACTED***" in payload["details"]["body"]

    async def test_api_key_in_graphql_message_is_scrubbed(self) -> None:
        api_key = "LONG-UNRAID-API-KEY-0123456789"

        async def handler(request: httpx.Request) -> httpx.Response:
            body = {"errors": [{"message": f"invalid key {api_key} for user"}]}
            return httpx.Response(200, content=json.dumps(body).encode())

        settings = Settings.from_env({"UNRAID_API_KEY": api_key, "UNRAID_HOST": "tower"})
        server = build_server(settings, transport=httpx.MockTransport(handler))
        is_error, text = await _call(server, {"domain": "system", "action": "info"})
        assert is_error
        assert api_key not in text
        payload = json.loads(text)
        assert payload["code"] == "upstream_error"
        assert "***REDACTED***" in text

    @pytest.mark.parametrize(
        "extensions",
        [
            {"debug": "request used key {key}"},
            {"dsn": "postgres://u:{key}@db"},
        ],
    )
    async def test_api_key_under_non_secret_extension_key_is_scrubbed(
        self, extensions: dict[str, str]
    ) -> None:
        api_key = "LONG-UNRAID-API-KEY-0123456789"
        ext = {k: v.format(key=api_key) for k, v in extensions.items()}

        async def handler(request: httpx.Request) -> httpx.Response:
            body = {"errors": [{"message": "upstream exploded", "extensions": ext}]}
            return httpx.Response(200, content=json.dumps(body).encode())

        settings = Settings.from_env({"UNRAID_API_KEY": api_key, "UNRAID_HOST": "tower"})
        server = build_server(settings, transport=httpx.MockTransport(handler))
        is_error, text = await _call(server, {"domain": "system", "action": "info"})
        assert is_error
        assert api_key not in text
        assert json.loads(text)["code"] == "upstream_error"
        assert "details" not in json.loads(text)

    async def test_tool_error_is_logged_without_api_key(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        api_key = "LONG-UNRAID-API-KEY-0123456789"

        async def handler(request: httpx.Request) -> httpx.Response:
            body = {"errors": [{"message": f"invalid key {api_key}"}]}
            return httpx.Response(200, content=json.dumps(body).encode())

        settings = Settings.from_env({"UNRAID_API_KEY": api_key, "UNRAID_HOST": "tower"})
        server = build_server(settings, transport=httpx.MockTransport(handler))
        with caplog.at_level(logging.WARNING, logger="unraid_mcp.server"):
            is_error, _ = await _call(server, {"domain": "system", "action": "info"})
        assert is_error
        records = [r for r in caplog.records if r.name == "unraid_mcp.server"]
        assert any("system.info failed: upstream_error" in r.getMessage() for r in records)
        assert all(api_key not in r.getMessage() for r in records)
        assert api_key not in caplog.text

    async def test_boundary_log_line_escapes_control_characters(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A newline in domain/action cannot forge a second log line."""
        server = build_server(_env(), transport=_ok_transport())
        with caplog.at_level(logging.WARNING, logger="unraid_mcp.server"):
            is_error, _ = await _call(server, {"domain": "system", "action": "x\nFORGED"})
        assert is_error
        records = [r for r in caplog.records if r.name == "unraid_mcp.server"]
        assert any("system.x\\nFORGED failed: unknown_action" in r.getMessage() for r in records)
        assert all("\n" not in r.getMessage() for r in records)

    async def test_success_is_not_an_error(self) -> None:
        server = build_server(_env(), transport=_ok_transport())
        is_error, _ = await _call(server, {"domain": "health", "action": "ping"})
        assert not is_error


class TestElicitationThroughClient:
    """Elicitation over a legacy (initialize-handshake) connection.

    On a 2026-07-28 connection FastMCP 4 refuses server-initiated elicitation
    (``ctx.elicit`` raises), so the write is refused there; see
    ``test_modern_connection_refuses_write``.
    """

    async def _write_with_answer(
        self, answer: Any, mode: str = "legacy"
    ) -> tuple[bool, str, list[httpx.Request]]:
        transport, requests = _recording_transport()
        server = build_server(_env(allow_writes=True), transport=transport)

        async def handler(message: str, response_type: Any, params: Any, ctx: Any) -> Any:
            return answer

        is_error, text = await _call(
            server,
            {"domain": "array", "action": "start"},
            elicitation_handler=handler,
            mode=mode,
        )
        return is_error, text, requests

    async def test_accepting_no_refuses_write(self) -> None:
        is_error, text, requests = await self._write_with_answer("no")
        assert is_error
        assert json.loads(text)["code"] == "confirmation_required"
        assert requests == []  # the mutation was never sent

    async def test_declining_refuses_write(self) -> None:
        is_error, text, requests = await self._write_with_answer(ElicitResult(action="decline"))
        assert is_error
        assert json.loads(text)["code"] == "confirmation_required"
        assert requests == []

    async def test_accepting_yes_sends_write(self) -> None:
        is_error, _, requests = await self._write_with_answer("yes")
        assert not is_error
        assert len(requests) == 1

    async def test_modern_connection_refuses_write(self) -> None:
        """No elicitation on 2026-07-28: even a "yes" handler cannot confirm."""
        is_error, text, requests = await self._write_with_answer("yes", mode="auto")
        assert is_error
        assert json.loads(text)["code"] == "confirmation_required"
        assert requests == []

    async def test_confirm_true_on_modern_connection_sends_write(self) -> None:
        transport, requests = _recording_transport()
        server = build_server(_env(allow_writes=True), transport=transport)
        is_error, _ = await _call(server, {"domain": "array", "action": "start", "confirm": True})
        assert not is_error
        assert len(requests) == 1

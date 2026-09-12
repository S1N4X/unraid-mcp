"""Tests for unraid_mcp.client."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest

from unraid_mcp.client import UnraidClient, _is_mutation, _redact
from unraid_mcp.errors import (
    ConnectionFailedError,
    IntrospectionDisabledError,
    NotFoundError,
    UnauthorizedError,
    UpstreamError,
)
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

QUERY = "query { info { os { hostname } } }"
MUTATION = "mutation { array { setState(input: {desiredState: START}) { id } } }"


def _make_transport(
    status: int = 200,
    body: dict[str, Any] | None = None,
    raw: str | None = None,
    exc: Exception | None = None,
) -> httpx.MockTransport:
    async def handler(request: httpx.Request) -> httpx.Response:
        if exc is not None:
            raise exc
        content = raw if raw is not None else json.dumps(body or {"data": {}})
        return httpx.Response(status, content=content.encode())

    return httpx.MockTransport(handler)


# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------
class TestRedact:
    def test_redacts_key_fields(self) -> None:
        data = {"apikey": "secret123", "name": "ok", "nested": {"password": "p"}}
        result = _redact(data)
        assert result["apikey"] == "***REDACTED***"
        assert result["name"] == "ok"
        assert result["nested"]["password"] == "***REDACTED***"

    def test_redacts_in_lists(self) -> None:
        data = [{"token": "t"}, {"safe": "v"}]
        result = _redact(data)
        assert result[0]["token"] == "***REDACTED***"
        assert result[1]["safe"] == "v"


# ---------------------------------------------------------------------------
# Mutation detection
# ---------------------------------------------------------------------------
class TestMutationDetection:
    def test_query_is_not_mutation(self) -> None:
        assert _is_mutation(QUERY) is False

    def test_mutation_detected(self) -> None:
        assert _is_mutation(MUTATION) is True

    def test_invalid_doc(self) -> None:
        assert _is_mutation("not graphql") is False


# ---------------------------------------------------------------------------
# HTTP error mapping
# ---------------------------------------------------------------------------
class TestHttpErrors:
    @pytest.mark.parametrize("status", [401, 403])
    async def test_auth_error(self, status: int) -> None:
        client = UnraidClient(SETTINGS, transport=_make_transport(status=status))
        with pytest.raises(UnauthorizedError, match=str(status)):
            await client.execute(QUERY)
        await client.close()

    async def test_server_error_no_retry_mutation(self) -> None:
        call_count = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            return httpx.Response(502, content=b'{"error":"bad"}')

        client = UnraidClient(SETTINGS, transport=httpx.MockTransport(handler))
        with pytest.raises(UpstreamError):
            await client.execute(MUTATION)
        assert call_count == 1
        await client.close()

    async def test_http_error_body_truncated(self) -> None:
        """HTTP error bodies are truncated to 200 chars, not passed to _redact."""
        long_body = "x" * 500
        client = UnraidClient(SETTINGS, transport=_make_transport(status=400, raw=long_body))
        with pytest.raises(UpstreamError) as exc_info:
            await client.execute(QUERY)
        body = exc_info.value.details.get("body", "")
        assert len(body) == 200
        assert body == "x" * 200
        await client.close()

    async def test_http_304_idempotent(self) -> None:
        client = UnraidClient(SETTINGS, transport=_make_transport(status=304))
        result = await client.execute(QUERY)
        assert result == {"idempotent": True}
        await client.close()


# ---------------------------------------------------------------------------
# Retry behaviour
# ---------------------------------------------------------------------------
class TestRetries:
    async def test_retries_on_502(self) -> None:
        import unraid_mcp.client as client_mod

        original_sleep = client_mod._sleep
        client_mod._sleep = AsyncMock()

        call_count = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return httpx.Response(503, content=b"retry")
            return httpx.Response(200, content=json.dumps({"data": {"ok": True}}).encode())

        try:
            client = UnraidClient(SETTINGS, transport=httpx.MockTransport(handler))
            result = await client.execute(QUERY)
            assert result == {"ok": True}
            assert call_count == 3
            await client.close()
        finally:
            client_mod._sleep = original_sleep

    async def test_no_retry_on_mutation(self) -> None:
        import unraid_mcp.client as client_mod

        original_sleep = client_mod._sleep
        client_mod._sleep = AsyncMock()

        call_count = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            return httpx.Response(503, content=b"retry")

        try:
            client = UnraidClient(SETTINGS, transport=httpx.MockTransport(handler))
            with pytest.raises(UpstreamError):
                await client.execute(MUTATION)
            assert call_count == 1
            await client.close()
        finally:
            client_mod._sleep = original_sleep

    async def test_connect_error_retries(self) -> None:
        import unraid_mcp.client as client_mod

        original_sleep = client_mod._sleep
        client_mod._sleep = AsyncMock()

        call_count = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise httpx.ConnectError("refused")
            return httpx.Response(200, content=json.dumps({"data": {"ok": True}}).encode())

        try:
            client = UnraidClient(SETTINGS, transport=httpx.MockTransport(handler))
            result = await client.execute(QUERY)
            assert result == {"ok": True}
            assert call_count == 3
            await client.close()
        finally:
            client_mod._sleep = original_sleep

    async def test_connect_error_exhausted(self) -> None:
        import unraid_mcp.client as client_mod

        original_sleep = client_mod._sleep
        client_mod._sleep = AsyncMock()

        async def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused")

        try:
            client = UnraidClient(SETTINGS, transport=httpx.MockTransport(handler))
            with pytest.raises(ConnectionFailedError):
                await client.execute(QUERY)
            await client.close()
        finally:
            client_mod._sleep = original_sleep


# ---------------------------------------------------------------------------
# GraphQL error mapping
# ---------------------------------------------------------------------------
class TestGraphQLErrors:
    async def test_unauthenticated(self) -> None:
        body = {"errors": [{"message": "nope", "extensions": {"code": "UNAUTHENTICATED"}}]}
        client = UnraidClient(SETTINGS, transport=_make_transport(body=body))
        with pytest.raises(UnauthorizedError):
            await client.execute(QUERY)
        await client.close()

    async def test_not_found(self) -> None:
        body = {"errors": [{"message": "nope", "extensions": {"code": "NOT_FOUND"}}]}
        client = UnraidClient(SETTINGS, transport=_make_transport(body=body))
        with pytest.raises(NotFoundError):
            await client.execute(QUERY)
        await client.close()

    async def test_introspection_disabled(self) -> None:
        body = {"errors": [{"message": "nope", "extensions": {"code": "INTROSPECTION_DISABLED"}}]}
        client = UnraidClient(SETTINGS, transport=_make_transport(body=body))
        with pytest.raises(IntrospectionDisabledError):
            await client.execute(QUERY)
        await client.close()

    async def test_generic_upstream(self) -> None:
        body = {"errors": [{"message": "boom", "extensions": {"code": "INTERNAL"}}]}
        client = UnraidClient(SETTINGS, transport=_make_transport(body=body))
        with pytest.raises(UpstreamError):
            await client.execute(QUERY)
        await client.close()


# ---------------------------------------------------------------------------
# Malformed JSON
# ---------------------------------------------------------------------------
class TestMalformedJson:
    async def test_malformed_json(self) -> None:
        client = UnraidClient(SETTINGS, transport=_make_transport(raw="not json"))
        with pytest.raises(UpstreamError, match="Malformed JSON"):
            await client.execute(QUERY)
        await client.close()


# ---------------------------------------------------------------------------
# Timeout profiles
# ---------------------------------------------------------------------------
class TestProfiles:
    async def test_disk_profile(self) -> None:
        client = UnraidClient(SETTINGS, transport=_make_transport(body={"data": {"ok": True}}))
        result = await client.execute(QUERY, profile="disk")
        assert result == {"ok": True}
        await client.close()

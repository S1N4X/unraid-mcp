"""Tests for unraid_mcp.client."""

from __future__ import annotations

import dataclasses
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

    async def test_http_error_body_scrubs_api_key_and_bearer(self) -> None:
        """The configured API key and bearer tokens never survive in details.body."""
        raw = "boom key=test-key auth: Bearer abc.DEF-123_xyz== tail"
        client = UnraidClient(SETTINGS, transport=_make_transport(status=500, raw=raw))
        with pytest.raises(UpstreamError) as exc_info:
            await client.execute(MUTATION)
        body = exc_info.value.details["body"]
        assert "test-key" not in body
        assert "abc.DEF-123_xyz==" not in body
        assert body == "boom key=***REDACTED*** auth: Bearer ***REDACTED*** tail"
        assert "test-key" not in exc_info.value.to_client_text()
        await client.close()

    async def test_http_error_body_scrubbed_before_truncation(self) -> None:
        """A key straddling the 200-char cut is masked, not partially leaked."""
        raw = "x" * 196 + "test-key" + "y" * 50
        client = UnraidClient(SETTINGS, transport=_make_transport(status=400, raw=raw))
        with pytest.raises(UpstreamError) as exc_info:
            await client.execute(QUERY)
        body = exc_info.value.details["body"]
        assert len(body) == 200
        assert "test" not in body
        await client.close()

    async def test_http_error_body_scrubs_json_escaped_key(self) -> None:
        """The key's JSON-escaped form is masked too (value_secrets rule)."""
        settings = dataclasses.replace(SETTINGS, api_key='quo"ted-key-123')
        raw = json.dumps({"error": 'bad key quo"ted-key-123'})
        client = UnraidClient(settings, transport=_make_transport(status=500, raw=raw))
        with pytest.raises(UpstreamError) as exc_info:
            await client.execute(MUTATION)
        body = exc_info.value.details["body"]
        assert "ted-key-123" not in body
        assert "***REDACTED***" in body
        await client.close()

    async def test_http_error_body_short_key_not_scrubbed(self) -> None:
        """Keys under the 8-char floor are not scrubbed (would corrupt every body)."""
        settings = dataclasses.replace(SETTINGS, api_key="k")
        client = UnraidClient(settings, transport=_make_transport(status=400, raw="kkk ok"))
        with pytest.raises(UpstreamError) as exc_info:
            await client.execute(QUERY)
        assert exc_info.value.details["body"] == "kkk ok"
        await client.close()

    async def test_malformed_json_body_scrubbed(self) -> None:
        raw = "<html>test-key Bearer tok123</html>"
        client = UnraidClient(SETTINGS, transport=_make_transport(status=200, raw=raw))
        with pytest.raises(UpstreamError, match="Malformed") as exc_info:
            await client.execute(QUERY)
        body = exc_info.value.details["body"]
        assert "test-key" not in body
        assert "tok123" not in body
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

    async def test_generic_upstream_forwards_only_extension_code(self) -> None:
        ext = {"code": "INTERNAL", "smtpPass": "HUNTER2", "stacktrace": ["at x"]}
        body = {"errors": [{"message": "boom", "extensions": ext}]}
        client = UnraidClient(SETTINGS, transport=_make_transport(body=body))
        with pytest.raises(UpstreamError) as exc_info:
            await client.execute(QUERY)
        assert exc_info.value.details == {"extensions": {"code": "INTERNAL"}}
        await client.close()

    @pytest.mark.parametrize("ext", [None, {}, {"smtpPass": "HUNTER2"}, {"code": 7}])
    async def test_generic_upstream_without_str_code_has_no_details(
        self, ext: dict[str, Any] | None
    ) -> None:
        error: dict[str, Any] = {"message": "boom"}
        if ext is not None:
            error["extensions"] = ext
        client = UnraidClient(SETTINGS, transport=_make_transport(body={"errors": [error]}))
        with pytest.raises(UpstreamError) as exc_info:
            await client.execute(QUERY)
        assert exc_info.value.details == {}
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


class TestRedactModule:
    def test_client_alias_is_redaction_redact(self) -> None:
        from unraid_mcp.redaction import redact

        assert _redact is redact

    def test_tuples_and_non_str_keys(self) -> None:
        from unraid_mcp.redaction import redact

        assert redact(({"secret": "s"}, 1)) == [{"secret": "***REDACTED***"}, 1]
        assert redact({1: "v"}) == {1: "v"}

    def test_depth_limit_fails_closed(self) -> None:
        from unraid_mcp.redaction import MAX_DEPTH, REDACTED, redact

        deep: dict[str, Any] = {"password": "leak"}
        for _ in range(MAX_DEPTH + 5):
            deep = {"n": deep}
        out = redact(deep)
        assert "leak" not in json.dumps(out)
        node = out
        while isinstance(node, dict):
            node = node["n"]
        assert node == REDACTED

    @pytest.mark.parametrize("key", ["keyword", "monkeyCount", "turkey", "author", "keyboard"])
    def test_non_secret_keys_pass(self, key: str) -> None:
        from unraid_mcp.redaction import redact

        assert redact({key: "v"}) == {key: "v"}

    @pytest.mark.parametrize(
        "key",
        [
            "apiKey",
            "api_key",
            "apikey",
            "APIKey",
            "x-api-key",
            "X-API-Key",
            "accessToken",
            "privateKey",
            "sessionId",
            "authorization",
            "Authorization",
            "Cookie",
            "set-cookie",
            "credentials",
            "passwd",
            "pwd",
            "client_secret",
            "UNRAID_API_KEY",
            # Unsplit lowercase / all-caps compounds (substring rule).
            "dbpassword",
            "adminpassword",
            "accesskey",
            "accesstoken",
            "clientsecret",
            "xapikey",
            "privatekey",
            "smtppassword",
            "sshkeys",
            "MYAPIKEY",
            # Plural segments.
            "apiKeys",
            "keys",
        ],
    )
    def test_secret_keys_redacted(self, key: str) -> None:
        from unraid_mcp.redaction import redact

        assert redact({key: "v"}) == {key: "***REDACTED***"}

    def test_scrub_text(self) -> None:
        from unraid_mcp.redaction import scrub_text

        assert scrub_text("a S3CR3T b", ["S3CR3T", ""]) == "a ***REDACTED*** b"
        assert scrub_text("BEARER abc", []) == "Bearer ***REDACTED***"
        assert scrub_text("no secrets here") == "no secrets here"

    def test_value_secrets(self) -> None:
        from unraid_mcp.redaction import value_secrets

        assert value_secrets("LONG-API-KEY-123") == ["LONG-API-KEY-123"]
        assert value_secrets('LONG"KEY\\123') == ['LONG"KEY\\123', 'LONG\\"KEY\\\\123']
        # Too short to scrub without corrupting every message.
        assert value_secrets("k", "", None) == []

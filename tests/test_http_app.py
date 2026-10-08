"""Integration tests: AuthGuard in front of the real FastMCP streamable-HTTP app."""

from __future__ import annotations

import json
import secrets
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.testclient import TestClient

from unraid_mcp.http_auth import AUTH_CHALLENGE, AuthGuard, load_http_auth_config
from unraid_mcp.server import build_server
from unraid_mcp.settings import Settings

TOKEN = secrets.token_urlsafe(32)
BASE_URL = "http://10.10.10.78:8000"
ALLOWED_PEER = "192.168.0.240"
CIDR_PEER = "10.10.10.5"
DENIED_PEER = "10.10.11.1"
MCP_HEADERS = {"Accept": "application/json, text/event-stream"}
INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "0"},
    },
}
FORBIDDEN_BODY = {"jsonrpc": "2.0", "error": {"code": -32000, "message": "Forbidden"}, "id": None}
UNAUTHORIZED_BODY = {
    "jsonrpc": "2.0",
    "error": {"code": -32000, "message": "Unauthorized"},
    "id": None,
}


def _unraid_transport() -> httpx.MockTransport:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b'{"data": {}}')

    return httpx.MockTransport(handler)


def _build_app(auth_env: dict[str, str]) -> Starlette:
    settings = Settings.from_env(
        {"UNRAID_API_KEY": "k", "UNRAID_HOST": "tower", "UNRAID_TRANSPORT": "http"}
    )
    cfg = load_http_auth_config(auth_env)
    server = build_server(settings, transport=_unraid_transport())
    return server.http_app(
        transport="http",
        middleware=[Middleware(AuthGuard, config=cfg)],
        host_origin_protection=False,
    )


@pytest.fixture()
def app(make_secret_file: Callable[..., str]) -> Starlette:
    assert len(TOKEN) == 43
    return _build_app(
        {
            "MCP_HOST": "0.0.0.0",
            "MCP_AUTH_TOKEN_FILE": make_secret_file(TOKEN, name="http-token"),
            "MCP_ALLOWED_HOSTS": "10.10.10.78",
            "MCP_ALLOWED_CLIENTS": "192.168.0.240,10.10.10.0/24",
            "MCP_ALLOWED_ORIGINS": "https://ok.example",
        }
    )


def _client(app: Starlette, peer: str = ALLOWED_PEER, base_url: str = BASE_URL) -> TestClient:
    return TestClient(app, base_url=base_url, client=(peer, 50000))


def _auth(token: str = TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _assert_forbidden(response: httpx.Response) -> None:
    assert response.status_code == 403
    assert response.json() == FORBIDDEN_BODY
    assert "www-authenticate" not in response.headers


def _assert_unauthorized(response: httpx.Response) -> None:
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == AUTH_CHALLENGE
    assert response.headers["www-authenticate"] == 'Bearer realm="unraid-mcp"'
    assert response.json() == UNAUTHORIZED_BODY


def _initialize(client: TestClient, headers: dict[str, str] | None = None) -> Any:
    return client.post("/mcp", json=INITIALIZE, headers={**MCP_HEADERS, **(headers or {})})


class TestClientIp:
    @pytest.mark.parametrize("peer", [ALLOWED_PEER, CIDR_PEER, "::ffff:192.168.0.240"])
    def test_allowed_peer(self, app: Starlette, peer: str) -> None:
        assert _client(app, peer).get("/health").status_code == 200

    def test_denied_peer(self, app: Starlette) -> None:
        _assert_forbidden(_client(app, DENIED_PEER).get("/health", headers=_auth()))


class TestXForwardedForIgnored:
    def test_denied_peer_with_allowed_xff(self, app: Starlette) -> None:
        response = _client(app, DENIED_PEER).get(
            "/health", headers={"X-Forwarded-For": ALLOWED_PEER}
        )
        _assert_forbidden(response)

    def test_allowed_peer_with_bogus_xff(self, app: Starlette) -> None:
        response = _client(app).get("/health", headers={"X-Forwarded-For": DENIED_PEER})
        assert response.status_code == 200


class TestHost:
    def test_allowed_host(self, app: Starlette) -> None:
        assert _client(app).get("/health").status_code == 200

    def test_denied_host(self, app: Starlette) -> None:
        response = _client(app, base_url="http://evil.example:8000").get("/health")
        _assert_forbidden(response)

    def test_port_agnostic(self, app: Starlette) -> None:
        response = _client(app, base_url="http://10.10.10.78:1234").get("/health")
        assert response.status_code == 200


class TestOrigin:
    def test_absent_origin_passes(self, app: Starlette) -> None:
        assert _client(app).get("/health").status_code == 200

    def test_foreign_origin_refused(self, app: Starlette) -> None:
        response = _client(app).get("/health", headers={"Origin": "https://evil.example"})
        _assert_forbidden(response)

    def test_allowed_origin_passes(self, app: Starlette) -> None:
        response = _client(app).get("/health", headers={"Origin": "https://ok.example"})
        assert response.status_code == 200


class TestHealth:
    def test_get_without_token(self, app: Starlette) -> None:
        response = _client(app).get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_head_without_token(self, app: Starlette) -> None:
        assert _client(app).head("/health").status_code == 200

    def test_post_needs_token(self, app: Starlette) -> None:
        _assert_unauthorized(_client(app).post("/health"))

    def test_trailing_slash_needs_token(self, app: Starlette) -> None:
        _assert_unauthorized(_client(app).get("/health/"))

    def test_double_slash_needs_token(self, app: Starlette) -> None:
        _assert_unauthorized(_client(app).get(f"{BASE_URL}//health"))


class TestBearer:
    def test_no_token(self, app: Starlette) -> None:
        with _client(app) as client:
            _assert_unauthorized(_initialize(client))

    def test_basic_auth(self, app: Starlette) -> None:
        with _client(app) as client:
            _assert_unauthorized(_initialize(client, {"Authorization": "Basic dXNlcjpwYXNz"}))

    def test_wrong_token(self, app: Starlette) -> None:
        with _client(app) as client:
            _assert_unauthorized(_initialize(client, _auth(secrets.token_urlsafe(32))))

    def test_correct_token_initializes(self, app: Starlette) -> None:
        with _client(app) as client:
            response = _initialize(client, _auth())
        assert response.status_code == 200
        assert "protocolVersion" in response.text


class TestUnknownRoute:
    def test_without_token(self, app: Starlette) -> None:
        _assert_unauthorized(_client(app).get("/nope"))

    def test_with_token(self, app: Starlette) -> None:
        assert _client(app).get("/nope", headers=_auth()).status_code == 404


class TestUnauthenticatedLoopback:
    def test_initialize_without_token(self) -> None:
        app = _build_app({"MCP_ALLOW_UNAUTHENTICATED": "1"})
        client = TestClient(app, base_url="http://localhost:8000", client=("127.0.0.1", 50000))
        with client:
            response = _initialize(client)
        assert response.status_code == 200
        assert "protocolVersion" in response.text


def test_rejection_body_is_compact_json(app: Starlette) -> None:
    response = _client(app).get("/nope")
    assert response.content == json.dumps(UNAUTHORIZED_BODY, separators=(",", ":")).encode()

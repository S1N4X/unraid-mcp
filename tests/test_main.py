"""Tests for the __main__ entrypoint."""

from __future__ import annotations

import logging
import secrets
from collections.abc import Callable
from dataclasses import replace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from unraid_mcp.__main__ import main
from unraid_mcp.http_auth import (
    NO_TOKEN_REFUSAL,
    AuthGuard,
    HttpAuthConfig,
    HttpAuthConfigError,
    describe_http_auth,
    load_http_auth_config,
)
from unraid_mcp.settings import Settings


class TestMain:
    def test_main_calls_from_env_and_run(self) -> None:
        """main() builds settings, builds server, and runs."""
        mock_server = MagicMock()
        mock_settings = MagicMock()
        mock_settings.transport = "stdio"

        with (
            patch(
                "unraid_mcp.__main__.Settings.from_env",
                return_value=mock_settings,
            ) as mock_from_env,
            patch(
                "unraid_mcp.__main__.build_server",
                return_value=mock_server,
            ) as mock_build,
        ):
            from unraid_mcp.__main__ import main

            main()
            mock_from_env.assert_called_once()
            mock_build.assert_called_once_with(mock_settings)
            mock_server.run.assert_called_once_with(transport="stdio")

    def test_import_does_not_call_main(self) -> None:
        """Importing __main__ must not trigger main()."""
        import importlib

        import unraid_mcp.__main__ as mod

        # Just verifying the import doesn't crash or call main()
        importlib.reload(mod)


def _http_auth_env(token_file: str) -> dict[str, str]:
    return {
        "MCP_HOST": "0.0.0.0",
        "MCP_PORT": "8123",
        "MCP_AUTH_TOKEN_FILE": token_file,
        "MCP_ALLOWED_HOSTS": "10.10.10.78",
        "MCP_ALLOWED_CLIENTS": "192.168.0.240",
    }


class TestMainHttp:
    @pytest.fixture()
    def auth_config(self, make_secret_file: Callable[..., str]) -> HttpAuthConfig:
        token_file = make_secret_file(secrets.token_urlsafe(32), name="http-token")
        return load_http_auth_config(_http_auth_env(token_file))

    def test_stdio_does_not_load_http_auth(self) -> None:
        mock_settings = MagicMock()
        mock_settings.transport = "stdio"
        with (
            patch("unraid_mcp.__main__.Settings.from_env", return_value=mock_settings),
            patch("unraid_mcp.__main__.build_server") as mock_build,
            patch("unraid_mcp.__main__.load_http_auth_config") as mock_load,
        ):
            main()
        mock_load.assert_not_called()
        mock_build.return_value.run.assert_called_once_with(transport="stdio")

    def test_http_wiring(self, auth_config: HttpAuthConfig) -> None:
        mock_settings = MagicMock()
        mock_settings.transport = "http"
        mock_settings.log_level = "INFO"
        with (
            patch("unraid_mcp.__main__.Settings.from_env", return_value=mock_settings),
            patch("unraid_mcp.__main__.build_server") as mock_build,
            patch("unraid_mcp.__main__.load_http_auth_config", return_value=auth_config),
        ):
            main()
        mock_build.assert_called_once_with(mock_settings)
        run = mock_build.return_value.run
        run.assert_called_once()
        kwargs = run.call_args.kwargs
        assert kwargs["transport"] == "http"
        assert kwargs["host"] == "0.0.0.0"
        assert kwargs["port"] == 8123
        assert kwargs["host_origin_protection"] is False
        assert kwargs["uvicorn_config"] == {"proxy_headers": False, "access_log": False}
        middleware = kwargs["middleware"]
        assert len(middleware) == 1
        assert middleware[0].cls is AuthGuard
        assert middleware[0].kwargs == {"config": auth_config}

    def test_http_logs_warnings_and_summary(
        self, auth_config: HttpAuthConfig, caplog: pytest.LogCaptureFixture
    ) -> None:
        mock_settings = MagicMock()
        mock_settings.transport = "http"
        mock_settings.log_level = "INFO"
        warned = replace(auth_config, warnings=("http auth: test warning",))
        with (
            caplog.at_level(logging.INFO, logger="unraid_mcp.__main__"),
            patch("unraid_mcp.__main__.Settings.from_env", return_value=mock_settings),
            patch("unraid_mcp.__main__.build_server"),
            patch("unraid_mcp.__main__.load_http_auth_config", return_value=warned),
        ):
            main()
        records = [r for r in caplog.records if r.name == "unraid_mcp.__main__"]
        assert [(r.levelno, r.getMessage()) for r in records] == [
            (logging.WARNING, "http auth: test warning"),
            (logging.INFO, describe_http_auth(warned)),
        ]

    def test_http_auth_refusal_exits_before_build(self) -> None:
        mock_settings = MagicMock()
        mock_settings.transport = "http"
        mock_settings.log_level = "INFO"
        with (
            patch("unraid_mcp.__main__.Settings.from_env", return_value=mock_settings),
            patch("unraid_mcp.__main__.build_server") as mock_build,
            patch(
                "unraid_mcp.__main__.load_http_auth_config",
                side_effect=HttpAuthConfigError(NO_TOKEN_REFUSAL),
            ),
            pytest.raises(SystemExit) as excinfo,
        ):
            main()
        assert NO_TOKEN_REFUSAL in str(excinfo.value.code)
        assert str(excinfo.value.code).startswith("unraid-mcp: ")
        mock_build.assert_not_called()
        mock_build.return_value.run.assert_not_called()

    def test_settings_error_exits(self) -> None:
        with (
            patch(
                "unraid_mcp.__main__.Settings.from_env",
                side_effect=ValueError(
                    "UNRAID_API_KEY_FILE (preferred) or UNRAID_API_KEY is required"
                ),
            ),
            patch("unraid_mcp.__main__.build_server") as mock_build,
            pytest.raises(SystemExit) as excinfo,
        ):
            main()
        assert "UNRAID_API_KEY" in str(excinfo.value.code)
        mock_build.assert_not_called()

    def test_end_to_end_uvicorn_config(
        self, auth_config: HttpAuthConfig, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import fastmcp
        import uvicorn
        from fastmcp.server.http import HostOriginGuardMiddleware
        from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

        monkeypatch.setattr(fastmcp.settings, "show_server_banner", False)
        settings = Settings.from_env(
            {"UNRAID_API_KEY": "k", "UNRAID_HOST": "tower", "UNRAID_TRANSPORT": "http"}
        )
        captured: list[uvicorn.Config] = []

        async def fake_serve(self: uvicorn.Server, sockets: Any = None) -> None:
            captured.append(self.config)

        monkeypatch.setattr(uvicorn.Server, "serve", fake_serve)
        with (
            patch("unraid_mcp.__main__.Settings.from_env", return_value=settings),
            patch("unraid_mcp.__main__.load_http_auth_config", return_value=auth_config),
        ):
            main()

        assert len(captured) == 1
        config = captured[0]
        assert config.host == "0.0.0.0"
        assert config.port == 8123
        assert config.proxy_headers is False
        assert config.access_log is False
        middleware_classes = [m.cls for m in config.app.user_middleware]
        assert AuthGuard in middleware_classes
        assert HostOriginGuardMiddleware not in middleware_classes
        config.load()
        assert not isinstance(config.loaded_app, ProxyHeadersMiddleware)

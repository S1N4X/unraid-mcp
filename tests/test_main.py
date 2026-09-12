"""Tests for the __main__ entrypoint."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


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

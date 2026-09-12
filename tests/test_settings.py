"""Tests for unraid_mcp.settings."""

from __future__ import annotations

import pytest

from unraid_mcp.settings import Settings, _parse_bool

# ---------------------------------------------------------------------------
# Minimal valid env
# ---------------------------------------------------------------------------
MINIMAL_ENV = {"UNRAID_API_KEY": "test-key", "UNRAID_HOST": "tower.local"}


def _env(**overrides: str) -> dict[str, str]:
    merged = dict(MINIMAL_ENV, **overrides)
    return {k: v for k, v in merged.items() if v is not None}  # type: ignore[comparison-overlap]


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
class TestDefaults:
    def test_defaults(self) -> None:
        s = Settings.from_env(MINIMAL_ENV)
        assert s.api_key == "test-key"
        assert s.host == "tower.local"
        assert s.api_url == "http://tower.local/graphql"
        assert s.allow_writes is False
        assert s.verify_ssl is True
        assert s.timeout == 30
        assert s.max_response_bytes == 40000
        assert s.transport == "stdio"
        assert s.log_level == "INFO"


# ---------------------------------------------------------------------------
# URL derivation
# ---------------------------------------------------------------------------
class TestUrlDerivation:
    def test_url_from_host(self) -> None:
        s = Settings.from_env({"UNRAID_API_KEY": "k", "UNRAID_HOST": "192.168.1.10"})
        assert s.api_url == "http://192.168.1.10/graphql"

    def test_url_override_wins(self) -> None:
        s = Settings.from_env(
            {
                "UNRAID_API_KEY": "k",
                "UNRAID_HOST": "tower.local",
                "UNRAID_API_URL": "https://custom:8443/gql",
            }
        )
        assert s.api_url == "https://custom:8443/gql"


# ---------------------------------------------------------------------------
# Boolean parsing
# ---------------------------------------------------------------------------
class TestBoolParsing:
    @pytest.mark.parametrize("val", ["true", "True", "TRUE", "1", "yes", "on"])
    def test_truthy(self, val: str) -> None:
        assert _parse_bool(val, "TEST_VAR") is True

    @pytest.mark.parametrize("val", ["false", "False", "FALSE", "0", "no", "off", ""])
    def test_falsy(self, val: str) -> None:
        assert _parse_bool(val, "TEST_VAR") is False

    def test_invalid_names_variable(self) -> None:
        with pytest.raises(ValueError, match="UNRAID_ALLOW_WRITES"):
            Settings.from_env(_env(UNRAID_ALLOW_WRITES="maybe"))


# ---------------------------------------------------------------------------
# Required fields
# ---------------------------------------------------------------------------
class TestRequired:
    def test_missing_api_key(self) -> None:
        with pytest.raises(ValueError, match="UNRAID_API_KEY"):
            Settings.from_env({"UNRAID_HOST": "tower.local"})

    def test_missing_host_and_url(self) -> None:
        with pytest.raises(ValueError, match="UNRAID_API_URL|UNRAID_HOST"):
            Settings.from_env({"UNRAID_API_KEY": "k"})


# ---------------------------------------------------------------------------
# verify_ssl path passthrough
# ---------------------------------------------------------------------------
class TestVerifySsl:
    def test_path_passthrough(self) -> None:
        s = Settings.from_env(_env(UNRAID_VERIFY_SSL="/etc/ssl/certs/ca.pem"))
        assert s.verify_ssl == "/etc/ssl/certs/ca.pem"

    def test_bool_true(self) -> None:
        s = Settings.from_env(_env(UNRAID_VERIFY_SSL="true"))
        assert s.verify_ssl is True

    def test_bool_false(self) -> None:
        s = Settings.from_env(_env(UNRAID_VERIFY_SSL="false"))
        assert s.verify_ssl is False


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------
class TestTransport:
    def test_bad_transport_rejected(self) -> None:
        with pytest.raises(ValueError, match="UNRAID_TRANSPORT"):
            Settings.from_env(_env(UNRAID_TRANSPORT="grpc"))

    def test_http_accepted(self) -> None:
        s = Settings.from_env(_env(UNRAID_TRANSPORT="http"))
        assert s.transport == "http"


# ---------------------------------------------------------------------------
# Import side-effects
# ---------------------------------------------------------------------------
class TestImportSideEffects:
    def test_no_import_side_effects(self) -> None:
        """Importing the module must not read os.environ or fail."""
        import importlib

        # Force re-import
        import unraid_mcp.settings as mod

        importlib.reload(mod)
        # If we get here, no exception was raised at import time.

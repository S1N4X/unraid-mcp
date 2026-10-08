"""Tests for unraid_mcp.settings."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

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

    def test_repr_omits_api_key(self) -> None:
        s = Settings.from_env({**MINIMAL_ENV, "UNRAID_API_KEY": "repr-secret-value"})
        assert "repr-secret-value" not in repr(s)
        assert "api_key" not in repr(s)


# ---------------------------------------------------------------------------
# UNRAID_LOG_LEVEL
# ---------------------------------------------------------------------------
class TestLogLevel:
    @pytest.mark.parametrize(
        "level", ["debug", "INFO", " Warning ", "WARN", "ERROR", "critical", "fatal"]
    )
    def test_standard_levels_accepted(self, level: str) -> None:
        s = Settings.from_env({**MINIMAL_ENV, "UNRAID_LOG_LEVEL": level})
        assert s.log_level == level.strip().upper()

    @pytest.mark.parametrize("blank", ["", "   "])
    def test_blank_level_means_default(self, blank: str) -> None:
        assert Settings.from_env({**MINIMAL_ENV, "UNRAID_LOG_LEVEL": blank}).log_level == "INFO"

    @pytest.mark.parametrize("level", ["verbose", "10", "WARNINGS"])
    def test_invalid_level_refused(self, level: str) -> None:
        with pytest.raises(ValueError, match="UNRAID_LOG_LEVEL"):
            Settings.from_env({**MINIMAL_ENV, "UNRAID_LOG_LEVEL": level})


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


# ---------------------------------------------------------------------------
# UNRAID_API_KEY_FILE
# ---------------------------------------------------------------------------
HOST_ENV = {"UNRAID_HOST": "tower.local"}
MakeSecret = Callable[..., str]


def _file_error(path: str) -> str:
    with pytest.raises(ValueError) as excinfo:
        Settings.from_env({**HOST_ENV, "UNRAID_API_KEY_FILE": path})
    return str(excinfo.value)


class TestApiKeyFile:
    def test_file_key_stripped(self, make_secret_file: MakeSecret) -> None:
        path = make_secret_file("  key\n")
        s = Settings.from_env({**HOST_ENV, "UNRAID_API_KEY_FILE": path})
        assert s.api_key == "key"

    def test_empty_file_var_means_unset(self) -> None:
        s = Settings.from_env({**HOST_ENV, "UNRAID_API_KEY": "env-key", "UNRAID_API_KEY_FILE": ""})
        assert s.api_key == "env-key"

    def test_both_set_refused(self, make_secret_file: MakeSecret) -> None:
        path = make_secret_file("file-secret-value")
        with pytest.raises(ValueError) as excinfo:
            Settings.from_env(
                {**HOST_ENV, "UNRAID_API_KEY": "env-secret-value", "UNRAID_API_KEY_FILE": path}
            )
        msg = str(excinfo.value)
        assert "UNRAID_API_KEY " in msg
        assert "UNRAID_API_KEY_FILE" in msg
        assert "ambiguous" in msg
        assert "env-secret-value" not in msg
        assert "file-secret-value" not in msg

    @pytest.mark.parametrize("mode", [0o644, 0o400])
    def test_wrong_mode_refused(self, make_secret_file: MakeSecret, mode: int) -> None:
        path = make_secret_file("secret", mode=mode)
        msg = _file_error(path)
        assert msg.startswith("UNRAID_API_KEY_FILE:")
        assert "0600" in msg
        assert f"0{mode:o}" in msg
        assert "secret" not in msg.replace(path, "")

    def test_wrong_owner_refused(
        self, make_secret_file: MakeSecret, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path = make_secret_file("secret")
        monkeypatch.setattr(os, "geteuid", lambda: os.getuid() + 1)
        msg = _file_error(path)
        assert msg.startswith("UNRAID_API_KEY_FILE:")
        assert "owned by uid" in msg

    def test_missing_file_refused(self, tmp_path: Path) -> None:
        msg = _file_error(str(tmp_path / "absent"))
        assert msg.startswith("UNRAID_API_KEY_FILE:")
        assert "missing" in msg

    def test_directory_refused(self, tmp_path: Path) -> None:
        d = tmp_path / "keydir"
        d.mkdir(mode=0o700)
        msg = _file_error(str(d))
        assert msg.startswith("UNRAID_API_KEY_FILE:")
        assert "not a regular file" in msg

    @pytest.mark.parametrize("content", ["", "  \n\t  "])
    def test_empty_file_refused(self, make_secret_file: MakeSecret, content: str) -> None:
        path = make_secret_file(content, name="empty")
        msg = _file_error(path)
        assert msg.startswith("UNRAID_API_KEY_FILE:")
        assert "empty" in msg

    def test_invalid_utf8_refused(self, make_secret_file: MakeSecret) -> None:
        path = make_secret_file("placeholder", name="binkey")
        Path(path).write_bytes(b"\xffsecret")
        msg = _file_error(path)
        assert msg.startswith("UNRAID_API_KEY_FILE:")
        assert "UTF-8" in msg
        assert "secret" not in msg
        assert "\\xff" not in msg
        assert "\xff" not in msg

    @pytest.mark.parametrize("value", ["relative/key", "abc123"])
    def test_relative_path_refused_not_echoed(self, value: str) -> None:
        msg = _file_error(value)
        assert msg.startswith("UNRAID_API_KEY_FILE:")
        assert "absolute" in msg
        assert value not in msg

    def test_absolute_looking_secret_not_echoed(self) -> None:
        # A secret pasted into the *_FILE var that happens to start with "/"
        # passes the absolute-path check; the refusal must still not echo it.
        value = "/Ab3_9xQwErTyUiOpAsDfGhJkLzXcVbNm0123456789-_"
        msg = _file_error(value)
        assert msg.startswith("UNRAID_API_KEY_FILE:")
        assert "missing" in msg
        assert value not in msg
        assert value[1:] not in msg

    def test_whitespace_env_key_is_unset(self) -> None:
        with pytest.raises(ValueError, match="required"):
            Settings.from_env({**HOST_ENV, "UNRAID_API_KEY": "   "})

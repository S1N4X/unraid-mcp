"""Tests for unraid_mcp.http_auth (port of pfsense-mcp src/http-auth.test.ts + extras)."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
from collections.abc import Callable
from ipaddress import IPv4Address, ip_network
from pathlib import Path
from typing import Any

import pytest

from unraid_mcp.http_auth import (
    ALLOWED_HOSTS_REQUIRED_REFUSAL,
    AUTH_CHALLENGE,
    ENV_TOKEN_REFUSAL,
    FLAG_IGNORED_WARNING,
    NO_TOKEN_REFUSAL,
    OPEN_CLIENTS_WARNING,
    TOKEN_CHARSET_REFUSAL,
    TOKEN_TOO_SHORT_REFUSAL,
    UNAUTHENTICATED_NON_LOOPBACK_REFUSAL,
    UNAUTHENTICATED_WARNING,
    AuthGuard,
    HttpAuthConfig,
    HttpAuthConfigError,
    check_bearer,
    client_allowed,
    describe_http_auth,
    host_allowed,
    load_http_auth_config,
    normalize_ip,
    parse_allowed_clients,
    parse_allowed_hosts,
    parse_allowed_origins,
)

MakeSecret = Callable[..., str]

# 32 random bytes, base64url → exactly 43 characters (the minimum).
TOKEN = secrets.token_urlsafe(32)
DIGEST = hashlib.sha256(TOKEN.encode()).digest()

LOGGER = "unraid_mcp.http_auth"


def _refusal(env: dict[str, str]) -> str:
    """Run the loader, assert it refuses, and assert the token is not echoed."""
    with pytest.raises(HttpAuthConfigError) as excinfo:
        load_http_auth_config(env)
    msg = str(excinfo.value)
    assert TOKEN not in msg
    return msg


def test_token_fixture_is_minimum_length() -> None:
    assert len(TOKEN) == 43


# ---------------------------------------------------------------------------
# load_http_auth_config — ported cases
# ---------------------------------------------------------------------------
class TestLoader:
    def test_refuses_without_token(self) -> None:
        assert _refusal({}) == NO_TOKEN_REFUSAL
        assert _refusal({"MCP_AUTH_TOKEN_FILE": ""}) == NO_TOKEN_REFUSAL

    def test_refuses_env_token_alone_or_with_file(self, make_secret_file: MakeSecret) -> None:
        assert _refusal({"MCP_AUTH_TOKEN": TOKEN}) == ENV_TOKEN_REFUSAL
        env = {"MCP_AUTH_TOKEN": TOKEN, "MCP_AUTH_TOKEN_FILE": make_secret_file(TOKEN)}
        assert _refusal(env) == ENV_TOKEN_REFUSAL

    def test_empty_env_token_is_unset(self, make_secret_file: MakeSecret) -> None:
        config = load_http_auth_config(
            {"MCP_AUTH_TOKEN": "", "MCP_AUTH_TOKEN_FILE": make_secret_file(TOKEN)}
        )
        assert config.token_digest is not None

    def test_keeps_only_digest_of_trimmed_token(self, make_secret_file: MakeSecret) -> None:
        config = load_http_auth_config({"MCP_AUTH_TOKEN_FILE": make_secret_file(f"{TOKEN}\n  \n")})
        assert config.token_digest == DIGEST
        assert TOKEN not in repr(config)
        assert TOKEN not in describe_http_auth(config)

    def test_refuses_non_0600_file(self, make_secret_file: MakeSecret) -> None:
        msg = _refusal({"MCP_AUTH_TOKEN_FILE": make_secret_file(TOKEN, 0o644)})
        assert "MCP_AUTH_TOKEN_FILE" in msg
        assert "0600" in msg

    def test_refuses_missing_file(self, tmp_path: Path) -> None:
        msg = _refusal({"MCP_AUTH_TOKEN_FILE": str(tmp_path / "absent")})
        assert "MCP_AUTH_TOKEN_FILE" in msg

    def test_enforces_minimum_length(self, make_secret_file: MakeSecret) -> None:
        short = TOKEN[:42]
        msg = _refusal({"MCP_AUTH_TOKEN_FILE": make_secret_file(short)})
        assert msg == TOKEN_TOO_SHORT_REFUSAL
        assert short not in msg
        config = load_http_auth_config({"MCP_AUTH_TOKEN_FILE": make_secret_file(TOKEN)})
        assert config.token_digest is not None

    @pytest.mark.parametrize(
        "bad",
        [f"{TOKEN[:20]} {TOKEN[20:]}", f"{TOKEN[:20]}!{TOKEN[20:]}"],
        ids=["space", "bang"],
    )
    def test_refuses_bad_charset(self, make_secret_file: MakeSecret, bad: str) -> None:
        assert len(bad) >= 43
        msg = _refusal({"MCP_AUTH_TOKEN_FILE": make_secret_file(bad)})
        assert msg == TOKEN_CHARSET_REFUSAL
        assert bad not in msg
        assert TOKEN[:20] not in msg

    @pytest.mark.parametrize("env", [{"MCP_HOST": "127.0.0.1"}, {}], ids=["127.0.0.1", "unset"])
    def test_unauthenticated_loopback(self, env: dict[str, str]) -> None:
        config = load_http_auth_config({**env, "MCP_ALLOW_UNAUTHENTICATED": "1"})
        assert config.token_digest is None
        assert UNAUTHENTICATED_WARNING in config.warnings

    @pytest.mark.parametrize("host", ["::1", "localhost"])
    def test_unauthenticated_other_loopback_binds(self, host: str) -> None:
        config = load_http_auth_config({"MCP_HOST": host, "MCP_ALLOW_UNAUTHENTICATED": "1"})
        assert config.token_digest is None

    @pytest.mark.parametrize("host", ["0.0.0.0", "10.10.10.78", "127.0.0.2"])
    def test_unauthenticated_non_loopback_refused(self, host: str) -> None:
        env = {"MCP_HOST": host, "MCP_ALLOW_UNAUTHENTICATED": "1"}
        assert _refusal(env) == UNAUTHENTICATED_NON_LOOPBACK_REFUSAL

    def test_bad_flag_value_refused(self) -> None:
        msg = _refusal({"MCP_ALLOW_UNAUTHENTICATED": "true"})
        assert "MCP_ALLOW_UNAUTHENTICATED" in msg

    def test_bad_flag_value_sanitised(self) -> None:
        msg = _refusal({"MCP_ALLOW_UNAUTHENTICATED": "yes\x1b[31m" + "x" * 100})
        assert "\x1b" not in msg
        # json.dumps escapes the "…" marker as \u2026; the value is capped at 32 chars.
        assert "[truncated]" in msg
        assert "x" * 33 not in msg

    def test_flag_zero_is_off(self) -> None:
        assert _refusal({"MCP_ALLOW_UNAUTHENTICATED": "0"}) == NO_TOKEN_REFUSAL

    def test_token_wins_over_flag_and_warns(self, make_secret_file: MakeSecret) -> None:
        config = load_http_auth_config(
            {"MCP_AUTH_TOKEN_FILE": make_secret_file(TOKEN), "MCP_ALLOW_UNAUTHENTICATED": "1"}
        )
        assert config.token_digest is not None
        ignored = [
            w for w in config.warnings if "MCP_ALLOW_UNAUTHENTICATED" in w and "ignored" in w
        ]
        assert ignored == [FLAG_IGNORED_WARNING]

    def test_loopback_defaults(self, make_secret_file: MakeSecret) -> None:
        config = load_http_auth_config({"MCP_AUTH_TOKEN_FILE": make_secret_file(TOKEN)})
        assert config.bind_host == "127.0.0.1"
        assert config.port == 8000
        assert config.allowed_hosts == ("localhost", "127.0.0.1", "[::1]")
        assert config.allowed_origins == ()
        assert config.allowed_clients is None
        assert OPEN_CLIENTS_WARNING not in config.warnings
        assert config.warnings == ()

    @pytest.mark.parametrize("port", ["abc", "70000", "-1", "80.0", "123456"])
    def test_bad_port_refused(self, make_secret_file: MakeSecret, port: str) -> None:
        msg = _refusal({"MCP_AUTH_TOKEN_FILE": make_secret_file(TOKEN), "MCP_PORT": port})
        assert "MCP_PORT" in msg

    def test_port_with_inner_newline_refused(self, make_secret_file: MakeSecret) -> None:
        # Outer whitespace is trimmed (""-means-unset rule); an inner newline is not.
        env = {"MCP_AUTH_TOKEN_FILE": make_secret_file(TOKEN), "MCP_PORT": "80\n00"}
        assert "MCP_PORT" in _refusal(env)

    @pytest.mark.parametrize("host", ["0.0.0.0", "::"])
    def test_wildcard_bind_requires_hosts(self, make_secret_file: MakeSecret, host: str) -> None:
        env = {"MCP_HOST": host, "MCP_AUTH_TOKEN_FILE": make_secret_file(TOKEN)}
        assert _refusal(env) == ALLOWED_HOSTS_REQUIRED_REFUSAL

    def test_open_clients_warning(self, make_secret_file: MakeSecret) -> None:
        config = load_http_auth_config(
            {
                "MCP_HOST": "0.0.0.0",
                "MCP_AUTH_TOKEN_FILE": make_secret_file(TOKEN),
                "MCP_ALLOWED_HOSTS": "10.10.10.78",
            }
        )
        assert config.allowed_hosts == ("10.10.10.78",)
        assert OPEN_CLIENTS_WARNING in config.warnings

    def test_clients_parsed_and_warning_dropped(self, make_secret_file: MakeSecret) -> None:
        config = load_http_auth_config(
            {
                "MCP_HOST": "0.0.0.0",
                "MCP_AUTH_TOKEN_FILE": make_secret_file(TOKEN),
                "MCP_ALLOWED_HOSTS": "10.10.10.78",
                "MCP_ALLOWED_CLIENTS": "192.168.0.240, 10.10.10.0/24",
            }
        )
        assert config.allowed_clients == (
            ip_network("192.168.0.240/32"),
            ip_network("10.10.10.0/24"),
        )
        assert OPEN_CLIENTS_WARNING not in config.warnings

    def test_specific_bind_defaults_hosts(self, make_secret_file: MakeSecret) -> None:
        config = load_http_auth_config(
            {"MCP_HOST": "10.10.10.78", "MCP_AUTH_TOKEN_FILE": make_secret_file(TOKEN)}
        )
        assert config.allowed_hosts == ("10.10.10.78",)

    def test_origins_parsed(self, make_secret_file: MakeSecret) -> None:
        config = load_http_auth_config(
            {
                "MCP_AUTH_TOKEN_FILE": make_secret_file(TOKEN),
                "MCP_ALLOWED_ORIGINS": "https://ok.example",
            }
        )
        assert config.allowed_origins == ("https://ok.example",)

    def test_defaults_to_os_environ(
        self, make_secret_file: MakeSecret, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for name in list(os.environ):
            if name.startswith(("MCP_", "FASTMCP_")):
                monkeypatch.delenv(name)
        monkeypatch.setenv("MCP_AUTH_TOKEN_FILE", make_secret_file(TOKEN))
        monkeypatch.setenv("MCP_PORT", "9123")
        config = load_http_auth_config()
        assert config.port == 9123
        assert config.token_digest == DIGEST


# ---------------------------------------------------------------------------
# load_http_auth_config — token file hardening (extras)
# ---------------------------------------------------------------------------
class TestTokenFile:
    def test_wrong_owner_refused(
        self, make_secret_file: MakeSecret, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path = make_secret_file(TOKEN)
        monkeypatch.setattr(os, "geteuid", lambda: os.getuid() + 1)
        msg = _refusal({"MCP_AUTH_TOKEN_FILE": path})
        assert msg.startswith("http auth: MCP_AUTH_TOKEN_FILE:")
        assert "owned by uid" in msg

    def test_directory_refused(self, tmp_path: Path) -> None:
        d = tmp_path / "dir"
        d.mkdir(mode=0o700)
        msg = _refusal({"MCP_AUTH_TOKEN_FILE": str(d)})
        assert "not a regular file" in msg

    @pytest.mark.parametrize("content", ["", "  \n\t\n"])
    def test_empty_file_refused(self, make_secret_file: MakeSecret, content: str) -> None:
        msg = _refusal({"MCP_AUTH_TOKEN_FILE": make_secret_file(content)})
        assert "MCP_AUTH_TOKEN_FILE" in msg
        assert "empty" in msg

    def test_absolute_looking_token_not_echoed(self) -> None:
        # A token pasted into MCP_AUTH_TOKEN_FILE with a leading "/" passes the
        # absolute-path check; the refusal must still not echo the value.
        value = "/" + TOKEN
        msg = _refusal({"MCP_AUTH_TOKEN_FILE": value})
        assert msg.startswith("http auth: MCP_AUTH_TOKEN_FILE:")
        assert "missing" in msg
        assert value not in msg

    def test_token_as_path_refused_not_echoed(self) -> None:
        msg = _refusal({"MCP_AUTH_TOKEN_FILE": TOKEN})
        assert "MCP_AUTH_TOKEN_FILE" in msg
        assert "absolute" in msg


# ---------------------------------------------------------------------------
# "" / whitespace means unset (extras)
# ---------------------------------------------------------------------------
class TestEmptyMeansUnset:
    @pytest.mark.parametrize("blank", ["", "   ", "\t\n"])
    def test_all_vars_blank(self, make_secret_file: MakeSecret, blank: str) -> None:
        config = load_http_auth_config(
            {
                "MCP_AUTH_TOKEN_FILE": make_secret_file(TOKEN),
                "MCP_HOST": blank,
                "FASTMCP_HOST": blank,
                "MCP_PORT": blank,
                "FASTMCP_PORT": blank,
                "MCP_AUTH_TOKEN": blank,
                "MCP_ALLOW_UNAUTHENTICATED": blank,
                "MCP_ALLOWED_CLIENTS": blank,
                "MCP_ALLOWED_HOSTS": blank,
                "MCP_ALLOWED_ORIGINS": blank,
            }
        )
        assert config.bind_host == "127.0.0.1"
        assert config.port == 8000
        assert config.allowed_clients is None
        assert config.allowed_hosts == ("localhost", "127.0.0.1", "[::1]")
        assert config.allowed_origins == ()
        assert config.warnings == ()

    @pytest.mark.parametrize("blank", ["", "  "])
    def test_blank_token_file_refused(self, blank: str) -> None:
        assert _refusal({"MCP_AUTH_TOKEN_FILE": blank}) == NO_TOKEN_REFUSAL

    def test_values_are_trimmed(self, make_secret_file: MakeSecret) -> None:
        config = load_http_auth_config(
            {
                "MCP_AUTH_TOKEN_FILE": f"  {make_secret_file(TOKEN)}  ",
                "MCP_HOST": " 10.10.10.78 ",
                "MCP_PORT": " 9000 ",
            }
        )
        assert config.bind_host == "10.10.10.78"
        assert config.port == 9000


# ---------------------------------------------------------------------------
# Bind and port precedence (extras)
# ---------------------------------------------------------------------------
class TestBindAndPort:
    def test_fastmcp_fallback(self, make_secret_file: MakeSecret) -> None:
        config = load_http_auth_config(
            {
                "MCP_AUTH_TOKEN_FILE": make_secret_file(TOKEN),
                "FASTMCP_HOST": "10.10.10.78",
                "FASTMCP_PORT": "8123",
            }
        )
        assert config.bind_host == "10.10.10.78"
        assert config.port == 8123

    def test_mcp_vars_beat_fastmcp(self, make_secret_file: MakeSecret) -> None:
        config = load_http_auth_config(
            {
                "MCP_AUTH_TOKEN_FILE": make_secret_file(TOKEN),
                "MCP_HOST": "10.10.10.78",
                "FASTMCP_HOST": "0.0.0.0",
                "MCP_PORT": "9000",
                "FASTMCP_PORT": "8000",
            }
        )
        assert config.bind_host == "10.10.10.78"
        assert config.port == 9000

    def test_invalid_fastmcp_port_named(self, make_secret_file: MakeSecret) -> None:
        msg = _refusal({"MCP_AUTH_TOKEN_FILE": make_secret_file(TOKEN), "FASTMCP_PORT": "nope"})
        assert "FASTMCP_PORT" in msg
        assert "MCP_PORT" not in msg.replace("FASTMCP_PORT", "")

    def test_wildcard_from_fastmcp_host_requires_hosts(self, make_secret_file: MakeSecret) -> None:
        env = {"FASTMCP_HOST": "0.0.0.0", "MCP_AUTH_TOKEN_FILE": make_secret_file(TOKEN)}
        assert _refusal(env) == ALLOWED_HOSTS_REQUIRED_REFUSAL

    def test_hostname_bind_defaults_hosts(self, make_secret_file: MakeSecret) -> None:
        config = load_http_auth_config(
            {"MCP_HOST": "Tower.LAN", "MCP_AUTH_TOKEN_FILE": make_secret_file(TOKEN)}
        )
        assert config.allowed_hosts == ("tower.lan",)
        assert OPEN_CLIENTS_WARNING in config.warnings


# ---------------------------------------------------------------------------
# Invalid list entries through the loader (extras)
# ---------------------------------------------------------------------------
class TestLoaderListErrors:
    @pytest.mark.parametrize(
        ("var", "value"),
        [
            ("MCP_ALLOWED_CLIENTS", "10.0.0.0/33"),
            ("MCP_ALLOWED_HOSTS", "10.10.10.78:8000"),
            ("MCP_ALLOWED_ORIGINS", "https://ok.example/"),
        ],
    )
    def test_bad_entry_names_variable(
        self, make_secret_file: MakeSecret, var: str, value: str
    ) -> None:
        env = {"MCP_AUTH_TOKEN_FILE": make_secret_file(TOKEN), var: value}
        assert var in _refusal(env)


# ---------------------------------------------------------------------------
# normalize_ip / client allowlist
# ---------------------------------------------------------------------------
class TestNormalizeIp:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("::ffff:192.168.0.240", "192.168.0.240"),
            ("::FFFF:10.0.0.1", "10.0.0.1"),
            ("::ffff:0a0a:0a01", "10.10.10.1"),
            ("FD00::1", "fd00::1"),
            ("192.168.0.1", "192.168.0.1"),
        ],
    )
    def test_normalises(self, raw: str, expected: str) -> None:
        assert str(normalize_ip(raw)) == expected

    @pytest.mark.parametrize("raw", ["fe80::1%eth0", "garbage", "", "127.1", "010.0.0.1"])
    def test_rejects(self, raw: str) -> None:
        assert normalize_ip(raw) is None


class TestClientAllowed:
    clients = parse_allowed_clients("192.168.0.240,10.10.10.0/24,fd00::/8")

    @pytest.mark.parametrize(
        "addr", ["192.168.0.240", "::ffff:192.168.0.240", "10.10.10.79", "fd12::1"]
    )
    def test_allows(self, addr: str) -> None:
        assert client_allowed(self.clients, addr) is True

    @pytest.mark.parametrize(
        "addr", ["10.10.11.1", "fe80::1", "127.0.0.1", "::1", None, "", "garbage", "fd00::1%eth0"]
    )
    def test_refuses(self, addr: str | None) -> None:
        assert client_allowed(self.clients, addr) is False

    def test_mapped_allowlist_entry(self) -> None:
        mapped = parse_allowed_clients("::ffff:192.168.0.240")
        assert client_allowed(mapped, "192.168.0.240") is True

    def test_host_bits_ignored(self) -> None:
        nets = parse_allowed_clients("10.10.10.5/24")
        assert nets == (ip_network("10.10.10.0/24"),)


class TestParseAllowedClientsRefusals:
    @pytest.mark.parametrize(
        "value",
        [
            "192.168.0.300",
            "10.0.0.0/33",
            "fd00::/129",
            "fe80::1%eth0",
            "abc",
            "10.0.0.0/8/1",
            "10.0.0.0/",
            "10.0.0.0/ 8",
            "10.0.0.0/0x8",
            "10.0.0.0/1234",
            ",",
            " , ",
        ],
    )
    def test_refuses(self, value: str) -> None:
        with pytest.raises(HttpAuthConfigError, match="MCP_ALLOWED_CLIENTS"):
            parse_allowed_clients(value)


# ---------------------------------------------------------------------------
# Host allowlist
# ---------------------------------------------------------------------------
class TestAllowedHosts:
    def test_canonicalises(self) -> None:
        assert parse_allowed_hosts("10.10.10.79, Example.LAN ,::1") == (
            "10.10.10.79",
            "example.lan",
            "[::1]",
        )

    def test_dedupes(self) -> None:
        assert parse_allowed_hosts("a.lan, A.LAN, [0::1], ::1") == ("a.lan", "[::1]")

    @pytest.mark.parametrize("value", ["10.10.10.79:8000", "[::1]:8000", "tower:80"])
    def test_refuses_port(self, value: str) -> None:
        with pytest.raises(HttpAuthConfigError, match="no port"):
            parse_allowed_hosts(value)

    @pytest.mark.parametrize(
        "value",
        [
            "http://x",
            "a/b",
            "user@host",
            "127.1",
            "0x7f.0.0.1",
            "fe80::1%eth0",
            "a..b",
            "host.",
            "[::1",
            "[not-ip]",
            "[1.2.3.4]",
            "[:::1]",
            "Kexample",
        ],
    )
    def test_refuses(self, value: str) -> None:
        with pytest.raises(HttpAuthConfigError, match="MCP_ALLOWED_HOSTS"):
            parse_allowed_hosts(value)

    @pytest.mark.parametrize("value", [",", " , "])
    def test_refuses_empty_list(self, value: str) -> None:
        with pytest.raises(HttpAuthConfigError, match="lists no hosts"):
            parse_allowed_hosts(value)


class TestHostAllowed:
    @pytest.mark.parametrize("header", ["10.10.10.79:8000", "10.10.10.79"])
    def test_true(self, header: str) -> None:
        assert host_allowed(header, ("10.10.10.79",)) is True

    @pytest.mark.parametrize(
        "header",
        [
            "evil.example:8000",
            "10.10.10.79@evil.example",
            "evil.example/10.10.10.79",
            None,
            "",
            "10.10.10.79\n",
            "10.10.10.79:99999",
            "10.10.10.79:",
            "10.10.10.79:80:80",
            "10.10.10.79:+80",
        ],
    )
    def test_false(self, header: str | None) -> None:
        assert host_allowed(header, ("10.10.10.79",)) is False

    def test_loopback_port_agnostic_case_insensitive(self) -> None:
        loopback = ("localhost", "127.0.0.1", "[::1]")
        assert host_allowed("LOCALHOST:1234", loopback) is True
        assert host_allowed("[::1]:8000", loopback) is True
        assert host_allowed("[::1]", loopback) is True
        assert host_allowed("[0:0::1]:8000", loopback) is True

    @pytest.mark.parametrize(
        "header", ["127.1", "0x7f.0.0.1", "::1", "[::1]x", "[::1", "[::1]:", "127.0.0.01"]
    )
    def test_loopback_aliases_refused(self, header: str) -> None:
        assert host_allowed(header, ("localhost", "127.0.0.1", "[::1]")) is False


# ---------------------------------------------------------------------------
# Origin allowlist
# ---------------------------------------------------------------------------
class TestAllowedOrigins:
    def test_accepts_exact(self) -> None:
        assert parse_allowed_origins(
            "https://ok.example, http://10.0.0.1:8080, http://[::1]:3000"
        ) == (
            "https://ok.example",
            "http://10.0.0.1:8080",
            "http://[::1]:3000",
        )

    def test_dedupes(self) -> None:
        assert parse_allowed_origins("https://ok.example,https://ok.example") == (
            "https://ok.example",
        )

    @pytest.mark.parametrize(
        "value",
        [
            "https://ok.example/",
            "null",
            "ok.example",
            "https://ok.example/path",
            "HTTPS://ok.example",
            "https://OK.example",
            "https://ok.example:443",
            "http://ok.example:80",
            "http://ok.example:0",
            "http://ok.example:08080",
            "http://ok.example:70000",
            "ftp://ok.example",
            "https://127.1",
            "http://[0:0::1]:3000",
            "https://ok.\nexample",
        ],
    )
    def test_refuses(self, value: str) -> None:
        with pytest.raises(HttpAuthConfigError, match="MCP_ALLOWED_ORIGINS"):
            parse_allowed_origins(value)


# ---------------------------------------------------------------------------
# check_bearer
# ---------------------------------------------------------------------------
class TestCheckBearer:
    @pytest.mark.parametrize("header", [None, ""])
    def test_missing(self, header: str | None) -> None:
        assert check_bearer(header, DIGEST) == "missing"

    @pytest.mark.parametrize(
        "header", [f"Bearer {TOKEN}", f"bearer {TOKEN}", f"Bearer   {TOKEN}", f"BEARER {TOKEN} "]
    )
    def test_ok(self, header: str) -> None:
        assert check_bearer(header, DIGEST) == "ok"

    @pytest.mark.parametrize(
        "header",
        [f"Bearer {TOKEN[1:]}", f"Bearer {TOKEN}x", f"Bearer {'A' * 43}", "Bearer short"],
    )
    def test_invalid(self, header: str) -> None:
        assert check_bearer(header, DIGEST) == "invalid"

    @pytest.mark.parametrize(
        "header",
        [
            f"Basic {TOKEN}",
            f"Token {TOKEN}",
            "Bearer",
            f"Bearer {TOKEN} extra",
            f"Bearer {TOKEN}\n",
            f"Bearer\t{TOKEN}",
            "Bearer " + "K" * 43,
            "Bearer " + "ſ" * 43,
        ],
    )
    def test_malformed(self, header: str) -> None:
        assert check_bearer(header, DIGEST) == "malformed"


# ---------------------------------------------------------------------------
# describe_http_auth
# ---------------------------------------------------------------------------
class TestDescribe:
    def test_authenticated(self, make_secret_file: MakeSecret) -> None:
        config = load_http_auth_config(
            {
                "MCP_HOST": "0.0.0.0",
                "MCP_PORT": "8000",
                "MCP_AUTH_TOKEN_FILE": make_secret_file(TOKEN),
                "MCP_ALLOWED_HOSTS": "10.10.10.79",
                "MCP_ALLOWED_CLIENTS": "192.168.0.240, 10.10.10.0/24",
            }
        )
        text = describe_http_auth(config)
        assert "bearer token required" in text
        assert "bind 0.0.0.0:8000" in text
        assert "192.168.0.240" in text
        assert "10.10.10.0/24" in text
        assert "10.10.10.79" in text
        assert "none (any Origin refused)" in text
        assert TOKEN not in text
        assert DIGEST.hex() not in text

    def test_unauthenticated(self) -> None:
        config = load_http_auth_config({"MCP_ALLOW_UNAUTHENTICATED": "1"})
        text = describe_http_auth(config)
        assert "DISABLED" in text
        assert "clients: any" in text


# ---------------------------------------------------------------------------
# AuthGuard
# ---------------------------------------------------------------------------
def _config(**overrides: Any) -> HttpAuthConfig:
    base: dict[str, Any] = {
        "bind_host": "0.0.0.0",
        "port": 8000,
        "token_digest": DIGEST,
        "allowed_clients": parse_allowed_clients("192.168.0.240,10.10.10.0/24"),
        "allowed_hosts": ("10.10.10.78",),
        "allowed_origins": ("https://ok.example",),
        "warnings": (),
    }
    base.update(overrides)
    return HttpAuthConfig(**base)


def _scope(
    *,
    type_: str = "http",
    method: str = "POST",
    path: str = "/mcp",
    raw_path: bytes | None = None,
    client: tuple[str, int] | None = ("192.168.0.240", 50000),
    headers: list[tuple[str, str]] | None = None,
    token: str | None = TOKEN,
) -> dict[str, Any]:
    hdrs = [("host", "10.10.10.78:8000")] if headers is None else list(headers)
    if token is not None:
        hdrs.append(("authorization", f"Bearer {token}"))
    scope: dict[str, Any] = {
        "type": type_,
        "path": path,
        "raw_path": path.encode() if raw_path is None else raw_path,
        "query_string": b"",
        "headers": [(k.encode("latin-1"), v.encode("latin-1")) for k, v in hdrs],
        "client": client,
    }
    if type_ == "http":
        scope["method"] = method
    return scope


class Recorder:
    """Downstream app + receive/send recorders for one guard invocation."""

    def __init__(self) -> None:
        self.app_calls: list[dict[str, Any]] = []
        self.receive_calls = 0
        self.sent: list[dict[str, Any]] = []

    async def app(self, scope: Any, receive: Any, send: Any) -> None:
        self.app_calls.append(scope)
        if scope["type"] == "http":
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

    async def receive(self) -> dict[str, Any]:
        self.receive_calls += 1
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(self, message: dict[str, Any]) -> None:
        self.sent.append(message)

    @property
    def status(self) -> int:
        return int(self.sent[0]["status"])

    @property
    def headers(self) -> dict[bytes, list[bytes]]:
        out: dict[bytes, list[bytes]] = {}
        for k, v in self.sent[0]["headers"]:
            out.setdefault(k, []).append(v)
        return out

    @property
    def body(self) -> bytes:
        return bytes(self.sent[1]["body"])


async def _run(scope: dict[str, Any], config: HttpAuthConfig | None = None) -> Recorder:
    rec = Recorder()
    guard = AuthGuard(rec.app, config or _config())
    await guard(scope, rec.receive, rec.send)
    return rec


def _warnings(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == LOGGER and r.levelno == logging.WARNING]


def _assert_rejected(rec: Recorder, status: int) -> None:
    assert rec.app_calls == []
    assert rec.receive_calls == 0
    assert len(rec.sent) == 2
    assert rec.status == status
    message = "Forbidden" if status == 403 else "Unauthorized"
    expected = {"jsonrpc": "2.0", "error": {"code": -32000, "message": message}, "id": None}
    assert json.loads(rec.body) == expected
    assert rec.body == json.dumps(expected, separators=(",", ":")).encode()
    headers = rec.headers
    assert headers[b"content-type"] == [b"application/json"]
    assert headers[b"content-length"] == [str(len(rec.body)).encode()]
    if status == 401:
        assert headers[b"www-authenticate"] == [AUTH_CHALLENGE.encode()]
        assert AUTH_CHALLENGE == 'Bearer realm="unraid-mcp"'
    else:
        assert b"www-authenticate" not in headers
    assert rec.sent[1]["type"] == "http.response.body"


def _assert_passed(rec: Recorder) -> None:
    assert len(rec.app_calls) == 1
    assert rec.status == 200


class TestAuthGuardPasses:
    async def test_valid_request_passes(self, caplog: pytest.LogCaptureFixture) -> None:
        caplog.set_level(logging.WARNING, logger=LOGGER)
        rec = await _run(_scope())
        _assert_passed(rec)
        assert _warnings(caplog) == []

    async def test_cidr_and_mapped_peers_pass(self) -> None:
        _assert_passed(await _run(_scope(client=("10.10.10.5", 1))))
        _assert_passed(await _run(_scope(client=("::ffff:192.168.0.240", 1))))

    async def test_allowed_origin_passes(self) -> None:
        headers = [("host", "10.10.10.78"), ("origin", "https://ok.example")]
        _assert_passed(await _run(_scope(headers=headers)))

    @pytest.mark.parametrize("method", ["GET", "HEAD"])
    async def test_health_exempt(self, method: str) -> None:
        _assert_passed(await _run(_scope(method=method, path="/health", token=None)))

    async def test_health_still_checks_client_host_origin(self) -> None:
        rec = await _run(_scope(method="GET", path="/health", token=None, client=("1.2.3.4", 1)))
        _assert_rejected(rec, 403)
        rec = await _run(
            _scope(method="GET", path="/health", token=None, headers=[("host", "evil")])
        )
        _assert_rejected(rec, 403)

    async def test_lifespan_passes_through(self) -> None:
        rec = Recorder()
        guard = AuthGuard(rec.app, _config())
        scope = {"type": "lifespan"}
        await guard(scope, rec.receive, rec.send)
        assert rec.app_calls == [scope]
        assert rec.sent == []

    async def test_unauthenticated_config_passes_without_token(self) -> None:
        config = _config(
            bind_host="127.0.0.1",
            token_digest=None,
            allowed_clients=None,
            allowed_hosts=("localhost", "127.0.0.1", "[::1]"),
            allowed_origins=(),
        )
        scope = _scope(client=("127.0.0.1", 1), headers=[("host", "localhost:8000")], token=None)
        _assert_passed(await _run(scope, config))

    async def test_no_client_allowlist_any_peer(self) -> None:
        rec = await _run(_scope(client=("8.8.8.8", 1)), _config(allowed_clients=None))
        _assert_passed(rec)

    async def test_raw_path_none_falls_back_to_path(self) -> None:
        scope = _scope(method="GET", path="/health", token=None)
        scope["raw_path"] = None
        _assert_passed(await _run(scope))
        scope = _scope(method="GET", path="/mcp", token=None)
        scope["raw_path"] = None
        _assert_rejected(await _run(scope), 401)

    async def test_health_with_query_string_raw_path(self) -> None:
        scope = _scope(method="GET", path="/health", raw_path=b"/health?x=1", token=None)
        _assert_passed(await _run(scope))


class TestAuthGuardRejects:
    async def test_client_not_allowed(self, caplog: pytest.LogCaptureFixture) -> None:
        caplog.set_level(logging.WARNING, logger=LOGGER)
        rec = await _run(_scope(client=("10.10.11.1", 1)))
        _assert_rejected(rec, 403)
        [record] = _warnings(caplog)
        assert record.getMessage() == "http: 403 client not allowed from 10.10.11.1 POST /mcp"

    @pytest.mark.parametrize(
        "template",
        ["/{t}", "/mcp/{t}", "/{t}?x=1", "/{pct}", "/" + "a" * 70 + "/{t}"],
    )
    async def test_path_borne_token_redacted_in_log(
        self, caplog: pytest.LogCaptureFixture, template: str
    ) -> None:
        caplog.set_level(logging.WARNING, logger=LOGGER)
        token = "Ab0-_~.+/" * 5 + "xyz="  # 49 b64token chars
        pct = token.replace("+", "%2B").replace("/", "%2F")
        raw = template.format(t=token, pct=pct).encode()
        scope = _scope(method="GET", raw_path=raw, token=None, client=("10.10.11.1", 1))
        rec = await _run(scope)
        _assert_rejected(rec, 403)
        [record] = _warnings(caplog)
        msg = record.getMessage()
        assert msg.startswith("http: 403 client not allowed from 10.10.11.1 GET /")
        assert "<redacted>" in msg
        for fragment in (token, token[:16], token[-16:], pct[:16]):
            assert fragment not in caplog.text

    async def test_missing_client_refused_when_allowlist_set(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level(logging.WARNING, logger=LOGGER)
        rec = await _run(_scope(client=None))
        _assert_rejected(rec, 403)
        [record] = _warnings(caplog)
        assert "from unknown" in record.getMessage()

    async def test_host_not_allowed(self, caplog: pytest.LogCaptureFixture) -> None:
        caplog.set_level(logging.WARNING, logger=LOGGER)
        rec = await _run(_scope(headers=[("host", "evil.example")]))
        _assert_rejected(rec, 403)
        [record] = _warnings(caplog)
        msg = record.getMessage()
        assert msg.startswith("http: 403 host not allowed from 192.168.0.240 POST /mcp")
        assert msg.endswith('host="evil.example"')

    async def test_missing_host(self, caplog: pytest.LogCaptureFixture) -> None:
        caplog.set_level(logging.WARNING, logger=LOGGER)
        rec = await _run(_scope(headers=[]))
        _assert_rejected(rec, 403)
        [record] = _warnings(caplog)
        assert record.getMessage().endswith("host=(none)")

    async def test_duplicate_host(self, caplog: pytest.LogCaptureFixture) -> None:
        caplog.set_level(logging.WARNING, logger=LOGGER)
        headers = [("host", "10.10.10.78"), ("host", "10.10.10.78")]
        rec = await _run(_scope(headers=headers))
        _assert_rejected(rec, 403)
        [record] = _warnings(caplog)
        assert "host not allowed" in record.getMessage()

    @pytest.mark.parametrize(
        "origins",
        [["https://evil.example"], [""], ["https://ok.example", "https://ok.example"], ["null"]],
    )
    async def test_origin_not_allowed(
        self, caplog: pytest.LogCaptureFixture, origins: list[str]
    ) -> None:
        caplog.set_level(logging.WARNING, logger=LOGGER)
        headers = [("host", "10.10.10.78")] + [("origin", o) for o in origins]
        rec = await _run(_scope(headers=headers))
        _assert_rejected(rec, 403)
        [record] = _warnings(caplog)
        assert record.getMessage().startswith("http: 403 origin not allowed from 192.168.0.240")
        assert "origin=" in record.getMessage()

    async def test_missing_token(self, caplog: pytest.LogCaptureFixture) -> None:
        caplog.set_level(logging.WARNING, logger=LOGGER)
        rec = await _run(_scope(token=None))
        _assert_rejected(rec, 401)
        [record] = _warnings(caplog)
        assert record.getMessage() == "http: 401 missing bearer token from 192.168.0.240 POST /mcp"

    async def test_malformed_token(self, caplog: pytest.LogCaptureFixture) -> None:
        caplog.set_level(logging.WARNING, logger=LOGGER)
        headers = [("host", "10.10.10.78"), ("authorization", f"Basic {TOKEN}")]
        rec = await _run(_scope(headers=headers, token=None))
        _assert_rejected(rec, 401)
        [record] = _warnings(caplog)
        assert record.getMessage().startswith("http: 401 malformed bearer token")
        assert TOKEN not in caplog.text

    async def test_invalid_token(self, caplog: pytest.LogCaptureFixture) -> None:
        caplog.set_level(logging.WARNING, logger=LOGGER)
        near_miss = TOKEN[:-1] + ("A" if TOKEN[-1] != "A" else "B")
        rec = await _run(_scope(token=near_miss))
        _assert_rejected(rec, 401)
        [record] = _warnings(caplog)
        assert record.getMessage().startswith("http: 401 invalid bearer token")
        assert near_miss not in caplog.text
        assert near_miss[:20] not in caplog.text

    async def test_duplicate_authorization_is_malformed(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level(logging.WARNING, logger=LOGGER)
        headers = [("host", "10.10.10.78"), ("authorization", f"Bearer {TOKEN}")]
        rec = await _run(_scope(headers=headers, token=TOKEN))
        _assert_rejected(rec, 401)
        [record] = _warnings(caplog)
        assert record.getMessage().startswith("http: 401 malformed bearer token")

    async def test_websocket_refused(self, caplog: pytest.LogCaptureFixture) -> None:
        caplog.set_level(logging.WARNING, logger=LOGGER)
        rec = Recorder()
        guard = AuthGuard(rec.app, _config())
        await guard(_scope(type_="websocket", path="/mcp"), rec.receive, rec.send)
        assert rec.app_calls == []
        assert rec.receive_calls == 0
        assert rec.sent == [{"type": "websocket.close", "code": 1008}]
        [record] = _warnings(caplog)
        assert record.getMessage().startswith("http: 403 websocket refused from 192.168.0.240")

    @pytest.mark.parametrize(
        ("method", "raw_path"),
        [
            ("GET", b"/%68ealth"),
            ("GET", b"//health"),
            ("GET", b"/health/"),
            ("GET", b"/HEALTH"),
            ("POST", b"/health"),
            ("OPTIONS", b"/health"),
            ("GET", b"/nope"),
        ],
    )
    async def test_health_exemption_is_exact(self, method: str, raw_path: bytes) -> None:
        scope = _scope(method=method, path="/health", raw_path=raw_path, token=None)
        _assert_rejected(await _run(scope), 401)

    async def test_check_order_client_first(self, caplog: pytest.LogCaptureFixture) -> None:
        caplog.set_level(logging.WARNING, logger=LOGGER)
        rec = await _run(_scope(client=("10.10.11.1", 1), headers=[("host", "evil")], token=None))
        _assert_rejected(rec, 403)
        [record] = _warnings(caplog)
        assert "client not allowed" in record.getMessage()
        assert "host not allowed" not in caplog.text

    async def test_check_order_host_before_origin_and_token(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level(logging.WARNING, logger=LOGGER)
        headers = [("host", "evil"), ("origin", "https://evil.example")]
        rec = await _run(_scope(headers=headers, token=None))
        _assert_rejected(rec, 403)
        [record] = _warnings(caplog)
        assert "host not allowed" in record.getMessage()

    async def test_check_order_origin_before_token(self, caplog: pytest.LogCaptureFixture) -> None:
        caplog.set_level(logging.WARNING, logger=LOGGER)
        headers = [("host", "10.10.10.78"), ("origin", "https://evil.example")]
        rec = await _run(_scope(headers=headers, token=None))
        _assert_rejected(rec, 403)
        [record] = _warnings(caplog)
        assert "origin not allowed" in record.getMessage()


class TestAuthGuardLogging:
    async def test_mapped_peer_logged_as_ipv4(self, caplog: pytest.LogCaptureFixture) -> None:
        caplog.set_level(logging.WARNING, logger=LOGGER)
        await _run(_scope(client=("::ffff:10.10.11.1", 1)))
        [record] = _warnings(caplog)
        assert "from 10.10.11.1 " in record.getMessage()
        assert "::ffff" not in record.getMessage()

    async def test_non_ip_peer_sanitised(self, caplog: pytest.LogCaptureFixture) -> None:
        caplog.set_level(logging.WARNING, logger=LOGGER)
        await _run(_scope(client=("sock\x1b[2Jpeer", 1)))
        [record] = _warnings(caplog)
        assert "\x1b" not in record.getMessage()
        assert "sock[2Jpeer" in record.getMessage()

    async def test_correct_token_bad_host_not_logged(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level(logging.DEBUG)
        rec = await _run(_scope(headers=[("host", "evil.example")], token=TOKEN))
        _assert_rejected(rec, 403)
        assert len(_warnings(caplog)) == 1
        assert TOKEN not in caplog.text
        assert "Bearer" not in caplog.text

    async def test_near_miss_token_not_logged(self, caplog: pytest.LogCaptureFixture) -> None:
        caplog.set_level(logging.DEBUG)
        near_miss = "x" + TOKEN[1:]
        rec = await _run(_scope(token=near_miss))
        _assert_rejected(rec, 401)
        assert len(_warnings(caplog)) == 1
        assert near_miss not in caplog.text
        assert TOKEN[1:] not in caplog.text

    async def test_host_escape_stripped(self, caplog: pytest.LogCaptureFixture) -> None:
        caplog.set_level(logging.WARNING, logger=LOGGER)
        await _run(_scope(headers=[("host", "evil\x1b[31m.example")]))
        [record] = _warnings(caplog)
        assert "\x1b" not in record.getMessage()
        assert "evil[31m.example" in record.getMessage()

    async def test_long_path_truncated(self, caplog: pytest.LogCaptureFixture) -> None:
        caplog.set_level(logging.WARNING, logger=LOGGER)
        # "!" is outside the b64token charset, so this long path is truncated, not redacted.
        path = "/" + "ab!" * 70
        await _run(_scope(path=path, token=None))
        [record] = _warnings(caplog)
        assert "…[truncated]" in record.getMessage()
        assert "ab!" * 30 not in record.getMessage()
        # A long all-charset path is token-like: redacted whole, never logged.
        caplog.clear()
        path = "/" + "a" * 200
        await _run(_scope(path=path, token=None))
        [record] = _warnings(caplog)
        assert record.getMessage().endswith(" /<redacted>")
        assert "a" * 100 not in record.getMessage()

    async def test_success_logs_nothing(self, caplog: pytest.LogCaptureFixture) -> None:
        caplog.set_level(logging.DEBUG, logger=LOGGER)
        await _run(_scope())
        assert [r for r in caplog.records if r.name == LOGGER] == []


def test_normalize_ip_returns_address_type() -> None:
    assert normalize_ip("::ffff:0a0a:0a01") == IPv4Address("10.10.10.1")

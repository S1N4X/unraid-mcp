"""Tests for unraid_mcp.errors."""

from __future__ import annotations

import json

from unraid_mcp.errors import (
    ConfirmationRequiredError,
    ConnectionFailedError,
    IntrospectionDisabledError,
    InvalidParamsError,
    NotFoundError,
    NotImplementedActionError,
    UnauthorizedError,
    UnknownActionError,
    UnraidError,
    UpstreamError,
    WriteDisabledError,
)


class TestUnraidError:
    def test_to_dict_basic(self) -> None:
        err = UnraidError("something broke")
        d = err.to_dict()
        assert d["code"] == "unraid_error"
        assert d["message"] == "something broke"
        assert "hint" not in d
        assert "details" not in d

    def test_to_dict_with_hint(self) -> None:
        err = UnraidError("broke", hint="try this")
        d = err.to_dict()
        assert d["hint"] == "try this"

    def test_to_dict_with_details(self) -> None:
        err = UnraidError("broke", details={"key": "val"})
        d = err.to_dict()
        assert d["details"] == {"key": "val"}

    def test_str_is_message(self) -> None:
        err = UnraidError("my message")
        assert str(err) == "my message"


class TestSubclassCodes:
    def test_unauthorized(self) -> None:
        assert UnauthorizedError("x").to_dict()["code"] == "unauthorized"

    def test_not_found(self) -> None:
        assert NotFoundError("x").to_dict()["code"] == "not_found"

    def test_introspection_disabled(self) -> None:
        assert IntrospectionDisabledError("x").to_dict()["code"] == "introspection_disabled"

    def test_upstream(self) -> None:
        assert UpstreamError("x").to_dict()["code"] == "upstream_error"

    def test_connection_failed(self) -> None:
        assert ConnectionFailedError("x").to_dict()["code"] == "connection_failed"

    def test_write_disabled(self) -> None:
        assert WriteDisabledError("x").to_dict()["code"] == "write_disabled"

    def test_confirmation_required(self) -> None:
        assert ConfirmationRequiredError("x").to_dict()["code"] == "confirmation_required"

    def test_not_implemented_action(self) -> None:
        assert NotImplementedActionError("x").to_dict()["code"] == "not_implemented"

    def test_unknown_action(self) -> None:
        assert UnknownActionError("x").to_dict()["code"] == "unknown_action"

    def test_invalid_params(self) -> None:
        assert InvalidParamsError("x").to_dict()["code"] == "invalid_params"


class TestClientPayload:
    def test_payload_redacts_secret_details(self) -> None:
        err = UpstreamError(
            "boom",
            hint="h",
            details={"api_key": "SECRET123", "nested": [{"token": "abc"}], "safe": 1},
        )
        payload = err.to_client_payload()
        assert payload["code"] == "upstream_error"
        assert payload["hint"] == "h"
        assert payload["details"]["api_key"] == "***REDACTED***"
        assert payload["details"]["nested"][0]["token"] == "***REDACTED***"
        assert payload["details"]["safe"] == 1
        # to_dict stays the raw, in-process form
        assert err.to_dict()["details"]["api_key"] == "SECRET123"

    def test_client_text_is_compact_json(self) -> None:
        err = WriteDisabledError("off", hint="Set UNRAID_ALLOW_WRITES=1 to enable.")
        text = err.to_client_text()
        assert json.loads(text) == {
            "code": "write_disabled",
            "message": "off",
            "hint": "Set UNRAID_ALLOW_WRITES=1 to enable.",
        }
        assert " " not in text.split('"hint"')[0]  # compact separators

    def test_client_text_without_details_has_no_details_key(self) -> None:
        assert "details" not in json.loads(UnraidError("x").to_client_text())

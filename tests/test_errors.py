"""Tests for unraid_mcp.errors."""

from __future__ import annotations

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

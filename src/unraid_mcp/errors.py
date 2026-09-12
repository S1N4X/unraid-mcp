"""Structured error hierarchy for the Unraid MCP server."""

from __future__ import annotations

from typing import Any


class UnraidError(Exception):
    """Base error with structured MCP error data."""

    code: str = "unraid_error"

    def __init__(
        self,
        message: str,
        *,
        hint: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.hint:
            d["hint"] = self.hint
        if self.details:
            d["details"] = self.details
        return d


class UnauthorizedError(UnraidError):
    code = "unauthorized"


class NotFoundError(UnraidError):
    code = "not_found"


class IntrospectionDisabledError(UnraidError):
    code = "introspection_disabled"


class UpstreamError(UnraidError):
    code = "upstream_error"


class ConnectionFailedError(UnraidError):
    code = "connection_failed"


class WriteDisabledError(UnraidError):
    code = "write_disabled"


class ConfirmationRequiredError(UnraidError):
    code = "confirmation_required"


class NotImplementedActionError(UnraidError):
    code = "not_implemented"


class UnknownActionError(UnraidError):
    code = "unknown_action"


class InvalidParamsError(UnraidError):
    code = "invalid_params"

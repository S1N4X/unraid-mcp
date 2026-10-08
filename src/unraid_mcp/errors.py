"""Structured error hierarchy for the Unraid MCP server."""

from __future__ import annotations

import json
from typing import Any

from unraid_mcp.redaction import redact


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

    def to_client_payload(self) -> dict[str, Any]:
        """:meth:`to_dict` with ``details`` passed through :func:`redact`.

        This is the form that leaves the process (MCP tool error text).
        """
        d = self.to_dict()
        if "details" in d:
            d["details"] = redact(d["details"])
        return d

    def to_client_text(self) -> str:
        """Compact JSON of :meth:`to_client_payload`, sent as the tool error text."""
        return json.dumps(self.to_client_payload(), separators=(",", ":"), default=str)


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

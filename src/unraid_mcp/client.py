"""GraphQL client with retries, error mapping, and secret redaction."""

from __future__ import annotations

import asyncio
import logging
import random
import re
from typing import Any

import httpx
from graphql import parse as gql_parse

from unraid_mcp.errors import (
    ConnectionFailedError,
    IntrospectionDisabledError,
    NotFoundError,
    UnauthorizedError,
    UpstreamError,
)
from unraid_mcp.settings import Settings

logger = logging.getLogger(__name__)

# Exposed at module level so tests can patch it.
_sleep = asyncio.sleep

_RETRYABLE_STATUS = frozenset({502, 503, 504})
_MAX_RETRIES = 2
_BASE_DELAY = 0.5

_SECRET_RE = re.compile(r"(key|token|secret|password|apikey)", re.IGNORECASE)

# Timeout profiles: name -> read-timeout override
_PROFILES: dict[str, int] = {
    "disk": 90,
    "logs": 90,
}


def _redact(obj: Any, *, _depth: int = 0) -> Any:
    """Recursively redact sensitive values in dicts/lists."""
    if _depth > 20:
        return obj
    if isinstance(obj, dict):
        return {
            k: "***REDACTED***" if _SECRET_RE.search(k) else _redact(v, _depth=_depth + 1)
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_redact(v, _depth=_depth + 1) for v in obj]
    return obj


def _is_mutation(document: str) -> bool:
    """Return True if *document* starts a mutation operation."""
    try:
        doc = gql_parse(document)
    except Exception:
        return False
    for defn in doc.definitions:
        if hasattr(defn, "operation") and defn.operation.value == "mutation":  # type: ignore[union-attr,unused-ignore]
            return True
    return False


def _map_graphql_error(error: dict[str, Any]) -> Exception:
    """Map a GraphQL error dict to our error hierarchy."""
    message = error.get("message", "Unknown GraphQL error")
    code = ""
    extensions = error.get("extensions")
    if isinstance(extensions, dict):
        code = extensions.get("code", "")

    if code in {"UNAUTHENTICATED", "FORBIDDEN"}:
        return UnauthorizedError(message, hint="Check API key roles.")
    if code in {"NOT_FOUND", "BAD_USER_INPUT"}:
        return NotFoundError(message)
    if code == "GRAPHQL_VALIDATION_FAILED":
        return UpstreamError(message, hint="Query validation failed upstream.")
    if code == "INTROSPECTION_DISABLED":
        return IntrospectionDisabledError(message)
    return UpstreamError(message, details={"extensions": extensions})


class UnraidClient:
    """Async GraphQL client for the Unraid API."""

    def __init__(
        self,
        settings: Settings,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._settings = settings
        verify: bool | str
        if isinstance(settings.verify_ssl, str):
            verify = settings.verify_ssl
        else:
            verify = settings.verify_ssl

        self._api_url = settings.api_url
        kw: dict[str, Any] = {
            "headers": {"X-API-Key": settings.api_key},
            "timeout": httpx.Timeout(
                float(settings.timeout),
                connect=5.0,
            ),
            "verify": verify,
        }
        if transport is not None:
            kw["transport"] = transport
        self._http = httpx.AsyncClient(**kw)

    async def close(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> UnraidClient:
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()

    async def execute(
        self,
        document: str,
        variables: dict[str, Any] | None = None,
        profile: str | None = None,
    ) -> Any:
        """Execute a GraphQL operation, with retries for non-mutations."""
        mutation = _is_mutation(document)
        max_retries = 0 if mutation else _MAX_RETRIES

        timeout_override: httpx.Timeout | None = None
        if profile and profile in _PROFILES:
            timeout_override = httpx.Timeout(
                float(_PROFILES[profile]),
                connect=5.0,
            )

        payload: dict[str, Any] = {"query": document}
        if variables:
            payload["variables"] = variables

        last_exc: Exception | None = None
        for attempt in range(max_retries + 1):
            try:
                response = await self._http.post(
                    self._api_url,
                    json=payload,
                    timeout=timeout_override,
                )
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                last_exc = ConnectionFailedError(
                    str(exc), hint="Check UNRAID_HOST and network connectivity."
                )
                if attempt < max_retries:
                    delay = _BASE_DELAY * (2**attempt) + random.uniform(0, 0.1)
                    await _sleep(delay)
                    continue
                raise last_exc from exc

            if response.status_code in {401, 403}:
                raise UnauthorizedError(
                    f"HTTP {response.status_code}",
                    hint="Check API key roles and permissions.",
                )

            if response.status_code == 304:
                return {"idempotent": True}

            if response.status_code in _RETRYABLE_STATUS and attempt < max_retries:
                delay = _BASE_DELAY * (2**attempt) + random.uniform(0, 0.1)
                await _sleep(delay)
                continue

            if response.status_code >= 400:
                # Raw HTTP error bodies are truncated to 200 chars but not
                # scanned for secrets (_redact only handles dicts/lists).
                raise UpstreamError(
                    f"HTTP {response.status_code}",
                    details={"body": response.text[:200]},
                )

            try:
                body = response.json()
            except Exception as exc:
                raise UpstreamError(
                    "Malformed JSON response",
                    details={"body": response.text[:200]},
                ) from exc

            errors = body.get("errors")
            if errors:
                raise _map_graphql_error(errors[0])

            return body.get("data")

        if last_exc is not None:
            raise last_exc
        # Should not be reachable
        raise UpstreamError("Exhausted retries with no response")  # pragma: no cover

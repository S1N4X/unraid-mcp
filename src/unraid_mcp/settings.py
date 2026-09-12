"""Configuration for the Unraid MCP server."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass


def _parse_bool(value: str, var: str) -> bool:
    """Parse a boolean-ish string, raising ValueError naming *var* on failure."""
    normalised = value.strip().lower()
    if normalised in {"true", "1", "yes", "on"}:
        return True
    if normalised in {"false", "0", "no", "off", ""}:
        return False
    msg = f"Invalid boolean value for {var}: {value!r}"
    raise ValueError(msg)


@dataclass(frozen=True)
class Settings:
    """Immutable server settings, typically built from environment variables."""

    host: str
    api_key: str
    api_url: str
    allow_writes: bool
    verify_ssl: bool | str
    timeout: int
    max_response_bytes: int
    transport: str
    log_level: str

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        """Construct :class:`Settings` from environment variables.

        Parameters
        ----------
        env:
            A mapping to read instead of :data:`os.environ`.  Useful for
            testing without mutating the real environment.
        """
        if env is None:
            env = os.environ

        api_key = env.get("UNRAID_API_KEY", "")
        if not api_key:
            msg = "UNRAID_API_KEY is required"
            raise ValueError(msg)

        api_url = env.get("UNRAID_API_URL", "")
        host = env.get("UNRAID_HOST", "")
        if api_url:
            pass  # explicit URL wins
        elif host:
            api_url = f"http://{host}/graphql"
        else:
            msg = "Either UNRAID_API_URL or UNRAID_HOST must be set"
            raise ValueError(msg)

        allow_writes = _parse_bool(env.get("UNRAID_ALLOW_WRITES", "false"), "UNRAID_ALLOW_WRITES")

        raw_verify = env.get("UNRAID_VERIFY_SSL", "true")
        try:
            verify_ssl: bool | str = _parse_bool(raw_verify, "UNRAID_VERIFY_SSL")
        except ValueError:
            # Non-empty, non-bool string → treat as CA-bundle path.
            verify_ssl = raw_verify

        timeout = int(env.get("UNRAID_TIMEOUT", "30"))
        max_response_bytes = int(env.get("UNRAID_MAX_RESPONSE_BYTES", "40000"))

        transport = env.get("UNRAID_TRANSPORT", "stdio").lower()
        if transport not in {"stdio", "http"}:
            msg = f"UNRAID_TRANSPORT must be 'stdio' or 'http', got {transport!r}"
            raise ValueError(msg)

        log_level = env.get("UNRAID_LOG_LEVEL", "INFO").upper()

        return cls(
            host=host,
            api_key=api_key,
            api_url=api_url,
            allow_writes=allow_writes,
            verify_ssl=verify_ssl,
            timeout=timeout,
            max_response_bytes=max_response_bytes,
            transport=transport,
            log_level=log_level,
        )

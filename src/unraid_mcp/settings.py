"""Configuration for the Unraid MCP server."""

from __future__ import annotations

import logging
import os
import stat
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

# Every name logging accepts, aliases included (WARN, FATAL, NOTSET); NOTSET is kept
# because logging.basicConfig accepts it and the pre-validation server started with it.
_LOG_LEVELS = tuple(logging.getLevelNamesMapping())


def _parse_bool(value: str, var: str) -> bool:
    """Parse a boolean-ish string, raising ValueError naming *var* on failure."""
    normalised = value.strip().lower()
    if normalised in {"true", "1", "yes", "on"}:
        return True
    if normalised in {"false", "0", "no", "off", ""}:
        return False
    msg = f"Invalid boolean value for {var}: {value!r}"
    raise ValueError(msg)


def read_key_file(path: str) -> str:
    """Read a secret from *path*, refusing anything but a private regular file.

    The file must be an absolute path to a regular file with mode 0600, owned
    by the effective uid, containing non-empty UTF-8 text.  Surrounding
    whitespace is stripped.  Raises :class:`ValueError` on any failure; error
    messages never include the path, file content, or underlying exception
    text (a secret pasted into a ``*_FILE`` variable may start with ``/``).
    Callers prefix the variable name.
    """
    if not os.path.isabs(path):
        # Do not echo the value: it may be a secret pasted into a *_FILE var.
        msg = "key path must be absolute (value not echoed)"
        raise ValueError(msg)
    try:
        st = os.stat(path)
    except OSError:
        msg = "key unreadable: file is missing or not statable"
        raise ValueError(msg) from None
    if not stat.S_ISREG(st.st_mode):
        msg = "key invalid: path is not a regular file"
        raise ValueError(msg)
    mode = stat.S_IMODE(st.st_mode)
    if mode != 0o600:
        msg = f"key mode: file must be 0600, found 0{mode:o}"
        raise ValueError(msg)
    euid = os.geteuid()
    if st.st_uid != euid:
        msg = f"key owner: file must be owned by uid {euid}"
        raise ValueError(msg)
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        msg = "key unreadable: file could not be read as UTF-8 text"
        raise ValueError(msg) from None
    key = text.strip()
    if not key:
        msg = "key empty: file contains no key material"
        raise ValueError(msg)
    return key


@dataclass(frozen=True)
class Settings:
    """Immutable server settings, typically built from environment variables."""

    host: str
    api_key: str = field(repr=False)
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

        # "" (or whitespace) means unset for both key sources.
        key_env = env.get("UNRAID_API_KEY", "").strip()
        key_file = env.get("UNRAID_API_KEY_FILE", "").strip()
        if key_env and key_file:
            msg = (
                "UNRAID_API_KEY and UNRAID_API_KEY_FILE are both set (ambiguous)"
                " — set only one; UNRAID_API_KEY_FILE is preferred"
            )
            raise ValueError(msg)
        if key_file:
            try:
                api_key = read_key_file(key_file)
            except ValueError as exc:
                msg = f"UNRAID_API_KEY_FILE: {exc}"
                raise ValueError(msg) from None
        elif key_env:
            api_key = key_env
        else:
            msg = "UNRAID_API_KEY_FILE (preferred) or UNRAID_API_KEY is required"
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

        # "" (or whitespace) means unset, like the key vars.
        log_level = env.get("UNRAID_LOG_LEVEL", "").strip().upper() or "INFO"
        if log_level not in _LOG_LEVELS:
            msg = (
                f"UNRAID_LOG_LEVEL must be one of {', '.join(_LOG_LEVELS)}, got {log_level[:32]!r}"
            )
            raise ValueError(msg)

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

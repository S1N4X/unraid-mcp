"""Secret redaction for data that leaves the process.

Two complementary mechanisms:

* :func:`redact` masks dict values whose *key* names a secret (segment and
  substring matching, see :func:`is_secret_key`).
* :func:`scrub_text` masks known secret *values* and bearer tokens inside free
  text such as truncated upstream HTTP bodies.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from typing import Any

REDACTED = "***REDACTED***"
MAX_DEPTH = 20

# A key is sensitive when any of its segments (split on non-alphanumerics and
# camelCase boundaries, lowercased) is one of these words.
SECRET_SEGMENTS = frozenset(
    {
        "key",
        "keys",
        "apikey",
        "apikeys",
        "token",
        "tokens",
        "secret",
        "secrets",
        "password",
        "passwords",
        "passwd",
        "pwd",
        "authorization",
        "auth",
        "cookie",
        "cookies",
        "session",
        "credential",
        "credentials",
        "bearer",
    }
)

# A key is also sensitive when, lowercased with non-alphanumerics removed, it
# contains one of these unambiguous words anywhere ("dbpassword", "xapikey").
# Short ambiguous words (key, auth, pwd) stay segment-only so "keyword",
# "turkey" and "author" are not masked.
SECRET_SUBSTRINGS = (
    "password",
    "passwd",
    "secret",
    "apikey",
    "accesskey",
    "privatekey",
    "sshkey",
    "token",
    "credential",
    "authorization",
    "cookie",
    "bearer",
    "session",
)

# Configured secrets shorter than this are not scrubbed by value from client
# error text: replacing a one-letter test key would corrupt every message.
MIN_SCRUB_LEN = 8

_NON_ALNUM_RE = re.compile(r"[^a-z0-9]")
_SEGMENT_RE = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+")
_BEARER_RE = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")


def key_segments(key: str) -> list[str]:
    """Split *key* into lowercase word segments (``"xApiKey"`` -> x/api/key)."""
    return [m.group(0).lower() for m in _SEGMENT_RE.finditer(key)]


def is_secret_key(key: Any) -> bool:
    """True when ``str(key)`` names a secret.

    Either a segment is in :data:`SECRET_SEGMENTS`, or the lowercased key with
    non-alphanumerics removed contains a word from :data:`SECRET_SUBSTRINGS`.
    """
    text = str(key)
    if any(seg in SECRET_SEGMENTS for seg in key_segments(text)):
        return True
    flat = _NON_ALNUM_RE.sub("", text.lower())
    return any(word in flat for word in SECRET_SUBSTRINGS)


def redact(obj: Any, *, _depth: int = 0) -> Any:
    """Recursively redact sensitive values in dicts/lists.

    A dict value is replaced by ``***REDACTED***`` when its key is a secret
    key (:func:`is_secret_key`).  Only keys are inspected here; free text is
    handled by :func:`scrub_text`.  Subtrees nested deeper than
    :data:`MAX_DEPTH` are replaced wholesale (fail closed).
    """
    if _depth > MAX_DEPTH:
        return REDACTED
    if isinstance(obj, dict):
        return {
            k: REDACTED if is_secret_key(k) else redact(v, _depth=_depth + 1)
            for k, v in obj.items()
        }
    if isinstance(obj, list | tuple):
        return [redact(v, _depth=_depth + 1) for v in obj]
    return obj


def scrub_text(text: str, secrets: Iterable[str] = ()) -> str:
    """Mask known secret values and bearer tokens inside free text.

    Every non-empty string in *secrets* is replaced by ``***REDACTED***``;
    ``Bearer <token>`` becomes ``Bearer ***REDACTED***``.
    """
    for secret in secrets:
        if secret:
            text = text.replace(secret, REDACTED)
    return _BEARER_RE.sub(f"Bearer {REDACTED}", text)


def value_secrets(*values: str | None) -> list[str]:
    """Secret values to pass to :func:`scrub_text` for JSON-encoded text.

    Each value of at least :data:`MIN_SCRUB_LEN` characters is returned, plus
    its JSON-escaped form when that differs (so it is also found inside a
    ``json.dumps`` payload).
    """
    out: list[str] = []
    for value in values:
        if not value or len(value) < MIN_SCRUB_LEN:
            continue
        out.append(value)
        escaped = json.dumps(value)[1:-1]
        if escaped != value:
            out.append(escaped)
    return out

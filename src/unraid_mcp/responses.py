"""Response shaping: JSON encoding, list capping, and truncation markers."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any


def _default_serializer(obj: object) -> Any:
    if isinstance(obj, datetime):
        return obj.isoformat()
    return str(obj)


def to_json(obj: Any) -> str:
    """Compact JSON with datetime→isoformat, fallback to str."""
    return json.dumps(obj, separators=(",", ":"), default=_default_serializer)


def cap_list(
    items: list[Any],
    limit: int | None = None,
    *,
    default: int = 20,
    byte_budget: int | None = None,
) -> dict[str, Any]:
    """Cap *items* to *limit* (<=0 means all), then trim to *byte_budget*.

    Always keeps at least 1 item if the input is non-empty.
    Returns ``{"items": kept, "_meta": {...}}``.
    """
    total = len(items)
    effective_limit = limit if limit is not None else default

    kept = list(items) if effective_limit <= 0 else list(items[:effective_limit])

    truncated = len(kept) < total

    # Enforce byte budget by dropping trailing items (but never below 1).
    if byte_budget is not None and kept:
        while len(kept) > 1:
            payload = to_json({"items": kept})
            if len(payload.encode()) <= byte_budget:
                break
            kept.pop()
            truncated = True
        # After the loop, check the single-item case — still report truncated
        # but keep the item regardless.
        if len(kept) == 1:
            payload = to_json({"items": kept})
            if len(payload.encode()) > byte_budget:
                truncated = True

    meta: dict[str, Any] = {
        "total": total,
        "returned": len(kept),
        "limit": effective_limit,
        "truncated": truncated,
    }
    if truncated:
        meta["hint"] = "Use 'limit' parameter to paginate."

    return {"items": kept, "_meta": meta}


def finalize(result: Any, byte_budget: int) -> Any:
    """Return *result* if its JSON representation fits *byte_budget*.

    Otherwise return a valid-JSON truncation marker.
    """
    encoded = to_json(result)
    if len(encoded.encode()) <= byte_budget:
        return result

    return {
        "response_truncated": True,
        "hint": "Response exceeded byte budget. Narrow your query or use 'limit'.",
    }

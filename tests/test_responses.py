"""Tests for unraid_mcp.responses."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from unraid_mcp.responses import cap_list, finalize, to_json


# ---------------------------------------------------------------------------
# to_json
# ---------------------------------------------------------------------------
class TestToJson:
    def test_compact(self) -> None:
        assert to_json({"a": 1}) == '{"a":1}'

    def test_datetime_isoformat(self) -> None:
        dt = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)
        result = to_json({"ts": dt})
        assert dt.isoformat() in result

    def test_default_str_fallback(self) -> None:
        result = to_json({"val": object()})
        parsed = json.loads(result)
        assert isinstance(parsed["val"], str)


# ---------------------------------------------------------------------------
# cap_list — count limit
# ---------------------------------------------------------------------------
class TestCapListCount:
    def test_default_limit(self) -> None:
        items = list(range(30))
        result = cap_list(items)
        assert len(result["items"]) == 20
        assert result["_meta"]["total"] == 30
        assert result["_meta"]["returned"] == 20
        assert result["_meta"]["truncated"] is True

    def test_explicit_limit(self) -> None:
        items = list(range(10))
        result = cap_list(items, 5)
        assert len(result["items"]) == 5
        assert result["_meta"]["truncated"] is True

    def test_limit_zero_returns_all(self) -> None:
        items = list(range(50))
        result = cap_list(items, 0)
        assert len(result["items"]) == 50
        assert result["_meta"]["truncated"] is False

    def test_negative_limit_returns_all(self) -> None:
        items = list(range(50))
        result = cap_list(items, -1)
        assert len(result["items"]) == 50
        assert result["_meta"]["truncated"] is False

    def test_no_truncation(self) -> None:
        items = list(range(5))
        result = cap_list(items, 10)
        assert result["_meta"]["truncated"] is False
        assert "hint" not in result["_meta"]


# ---------------------------------------------------------------------------
# cap_list — byte budget
# ---------------------------------------------------------------------------
class TestCapListByteBudget:
    def test_byte_budget_trims(self) -> None:
        items = [{"data": "x" * 100} for _ in range(10)]
        result = cap_list(items, 0, byte_budget=300)
        assert len(result["items"]) >= 1
        assert result["_meta"]["truncated"] is True

    def test_byte_budget_keeps_at_least_one(self) -> None:
        items = [{"data": "x" * 10000}]
        result = cap_list(items, 0, byte_budget=10)
        assert len(result["items"]) == 1
        assert result["_meta"]["truncated"] is True

    def test_truncated_hint_present(self) -> None:
        items = list(range(30))
        result = cap_list(items)
        assert result["_meta"]["truncated"] is True
        assert "hint" in result["_meta"]


# ---------------------------------------------------------------------------
# finalize
# ---------------------------------------------------------------------------
class TestFinalize:
    def test_under_budget_passes_through(self) -> None:
        data = {"key": "value"}
        assert finalize(data, 100000) == data

    def test_over_budget_returns_marker(self) -> None:
        data = {"key": "x" * 100000}
        result = finalize(data, 100)
        assert isinstance(result, dict)
        assert result["response_truncated"] is True
        # Marker itself must be valid JSON
        json.loads(to_json(result))

    def test_marker_is_valid_json(self) -> None:
        data = {"big": list(range(10000))}
        result = finalize(data, 50)
        serialized = to_json(result)
        parsed = json.loads(serialized)
        assert parsed["response_truncated"] is True

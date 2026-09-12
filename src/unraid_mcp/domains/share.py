"""Share domain: list and get shares."""

from __future__ import annotations

from typing import Any

from unraid_mcp.registry import Action, list_shape, no_variables, require_str
from unraid_mcp.responses import finalize

_LIST_QUERY = """\
query {
  shares {
    id name free used size comment cache color
  }
}
"""

_GET_QUERY = """\
query {
  shares {
    id name free used size
    include exclude cache nameOrig comment
    allocator splitLevel floor cow color luksStatus
  }
}
"""


def _get_shape(data: Any, params: dict[str, Any], budget: int) -> Any:
    """Find a share by name from the shares list."""
    name = params.get("name", "")
    if isinstance(data, dict):
        shares = data.get("shares")
        if isinstance(shares, list):
            for share in shares:
                if isinstance(share, dict) and share.get("name") == name:
                    return finalize(share, budget)
    return finalize(data, budget)


def _get_variables(params: dict[str, Any]) -> dict[str, Any] | None:
    require_str(params, "name")
    return None  # The API has no single-share query; we filter client-side.


ACTIONS: dict[tuple[str, str], Action] = {
    ("share", "list"): Action(
        doc="List all user shares.",
        document=_LIST_QUERY,
        variables=no_variables,
        shape=list_shape("shares"),
    ),
    ("share", "get"): Action(
        doc="Get details for a single share by name.",
        document=_GET_QUERY,
        variables=_get_variables,
        shape=_get_shape,
    ),
}

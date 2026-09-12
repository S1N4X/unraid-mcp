"""Logs domain: list log files and read log content."""

from __future__ import annotations

from typing import Any

from unraid_mcp.registry import Action, identity_shape, list_shape, no_variables, require_str

_LIST_QUERY = """\
query {
  logFiles {
    name path size modifiedAt
  }
}
"""

_READ_QUERY = """\
query ($path: String!, $lines: Int, $startLine: Int) {
  logFile(path: $path, lines: $lines, startLine: $startLine) {
    path content totalLines startLine
  }
}
"""


def _read_variables(params: dict[str, Any]) -> dict[str, Any] | None:
    v: dict[str, Any] = {"path": require_str(params, "path")}
    lines = params.get("lines")
    if lines is not None:
        v["lines"] = int(lines)
    start = params.get("startLine")
    if start is not None:
        v["startLine"] = int(start)
    return v


ACTIONS: dict[tuple[str, str], Action] = {
    ("logs", "list"): Action(
        doc="List available log files.",
        document=_LIST_QUERY,
        variables=no_variables,
        shape=list_shape("logFiles"),
    ),
    ("logs", "read"): Action(
        doc="Read contents of a log file.",
        document=_READ_QUERY,
        variables=_read_variables,
        shape=identity_shape,
        profile="logs",
    ),
}

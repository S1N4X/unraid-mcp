"""Array domain: status, disks, parity, and array mutations."""

from __future__ import annotations

from typing import Any

from unraid_mcp.registry import (
    Action,
    identity_shape,
    list_shape,
    no_variables,
)

_STATUS_QUERY = """\
query {
  array {
    id state
    capacity { kilobytes { free used total } disks { free used total } }
    parityCheckStatus { status progress errors correcting paused running }
  }
}
"""

_DISKS_QUERY = """\
query {
  array {
    disks {
      id idx name device size status rotational temp
      numReads numWrites numErrors
      fsSize fsFree fsUsed type fsType color
    }
    parities {
      id idx name device size status rotational temp
      numReads numWrites numErrors type color
    }
    caches {
      id idx name device size status rotational temp
      fsSize fsFree fsUsed type fsType color
    }
  }
}
"""

_PARITY_HISTORY_QUERY = """\
query {
  parityHistory {
    date duration speed status errors correcting
  }
}
"""

_SET_STATE_MUTATION = """\
mutation ($input: ArrayStateInput!) {
  array { setState(input: $input) { id state } }
}
"""

_PARITY_START_MUTATION = """\
mutation ($correct: Boolean!) {
  parityCheck { start(correct: $correct) }
}
"""

_PARITY_PAUSE_MUTATION = """\
mutation {
  parityCheck { pause }
}
"""

_PARITY_RESUME_MUTATION = """\
mutation {
  parityCheck { resume }
}
"""

_PARITY_CANCEL_MUTATION = """\
mutation {
  parityCheck { cancel }
}
"""


def _start_variables(params: dict[str, Any]) -> dict[str, Any] | None:
    return {"input": {"desiredState": "START"}}


def _stop_variables(params: dict[str, Any]) -> dict[str, Any] | None:
    return {"input": {"desiredState": "STOP"}}


def _parity_start_variables(params: dict[str, Any]) -> dict[str, Any] | None:
    correct = params.get("correct", False)
    if isinstance(correct, str):
        correct = correct.lower() in {"true", "1", "yes"}
    return {"correct": correct}


ACTIONS: dict[tuple[str, str], Action] = {
    ("array", "status"): Action(
        doc="Array state, capacity, and parity check status.",
        document=_STATUS_QUERY,
        variables=no_variables,
        shape=identity_shape,
    ),
    ("array", "disks"): Action(
        doc="All array disks (data, parity, cache).",
        document=_DISKS_QUERY,
        variables=no_variables,
        shape=identity_shape,
        profile="disk",
    ),
    ("array", "parity_history"): Action(
        doc="Historical parity check results.",
        document=_PARITY_HISTORY_QUERY,
        variables=no_variables,
        shape=list_shape("parityHistory"),
    ),
    ("array", "start"): Action(
        doc="Start the array.",
        document=_SET_STATE_MUTATION,
        variables=_start_variables,
        shape=identity_shape,
        writes=True,
    ),
    ("array", "stop"): Action(
        doc="Stop the array.",
        document=_SET_STATE_MUTATION,
        variables=_stop_variables,
        shape=identity_shape,
        writes=True,
        destructive=True,
    ),
    ("array", "parity_start"): Action(
        doc="Start a parity check.",
        document=_PARITY_START_MUTATION,
        variables=_parity_start_variables,
        shape=identity_shape,
        writes=True,
    ),
    ("array", "parity_pause"): Action(
        doc="Pause a running parity check.",
        document=_PARITY_PAUSE_MUTATION,
        variables=no_variables,
        shape=identity_shape,
        writes=True,
    ),
    ("array", "parity_resume"): Action(
        doc="Resume a paused parity check.",
        document=_PARITY_RESUME_MUTATION,
        variables=no_variables,
        shape=identity_shape,
        writes=True,
    ),
    ("array", "parity_cancel"): Action(
        doc="Cancel a running parity check.",
        document=_PARITY_CANCEL_MUTATION,
        variables=no_variables,
        shape=identity_shape,
        writes=True,
    ),
}

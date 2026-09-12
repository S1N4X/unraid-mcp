"""VM domain: list, get, and lifecycle mutations."""

from __future__ import annotations

from typing import Any

from unraid_mcp.errors import InvalidParamsError, NotFoundError
from unraid_mcp.registry import (
    Action,
    id_variables,
    identity_shape,
    no_variables,
)
from unraid_mcp.responses import finalize

_LIST_QUERY = """\
query {
  vms {
    domains { id name state uuid }
  }
}
"""

_START_MUTATION = """\
mutation ($id: PrefixedID!) {
  vm { start(id: $id) }
}
"""

_STOP_MUTATION = """\
mutation ($id: PrefixedID!) {
  vm { stop(id: $id) }
}
"""

_PAUSE_MUTATION = """\
mutation ($id: PrefixedID!) {
  vm { pause(id: $id) }
}
"""

_RESUME_MUTATION = """\
mutation ($id: PrefixedID!) {
  vm { resume(id: $id) }
}
"""

_REBOOT_MUTATION = """\
mutation ($id: PrefixedID!) {
  vm { reboot(id: $id) }
}
"""


def _list_shape(data: Any, params: dict[str, Any], budget: int) -> Any:
    """Shape vm.list — extract domains from vms."""
    if isinstance(data, dict):
        vms = data.get("vms")
        if isinstance(vms, dict):
            domains = vms.get("domains")
            if isinstance(domains, list):
                from unraid_mcp.responses import cap_list, finalize

                limit = params.get("limit")
                if isinstance(limit, str):
                    limit = int(limit)
                return finalize(cap_list(domains, limit, byte_budget=budget), budget)
    return identity_shape(data, params, budget)


def _get_variables(params: dict[str, Any]) -> dict[str, Any] | None:
    """Require at least one of id or name for vm.get."""
    if not params.get("id") and not params.get("name"):
        raise InvalidParamsError(
            "Required parameter 'id' or 'name' (string) is missing.",
        )
    return None  # The API has no single-VM query; we filter client-side.


def _get_shape(data: Any, params: dict[str, Any], budget: int) -> Any:
    """Find a single VM by id or name from the domains list."""
    target_id = params.get("id", "")
    target_name = params.get("name", "")
    if isinstance(data, dict):
        vms = data.get("vms")
        if isinstance(vms, dict):
            domains = vms.get("domains")
            if isinstance(domains, list):
                for vm in domains:
                    if isinstance(vm, dict):
                        if target_id and vm.get("id") == target_id:
                            return finalize(vm, budget)
                        if target_name and vm.get("name") == target_name:
                            return finalize(vm, budget)
    label = target_id or target_name
    raise NotFoundError(f"VM '{label}' not found.")


ACTIONS: dict[tuple[str, str], Action] = {
    ("vm", "list"): Action(
        doc="List all VMs.",
        document=_LIST_QUERY,
        variables=no_variables,
        shape=_list_shape,
    ),
    ("vm", "get"): Action(
        doc="Get a single VM by id or name.",
        document=_LIST_QUERY,
        variables=_get_variables,
        shape=_get_shape,
    ),
    ("vm", "start"): Action(
        doc="Start a VM.",
        document=_START_MUTATION,
        variables=id_variables,
        shape=identity_shape,
        writes=True,
    ),
    ("vm", "stop"): Action(
        doc="Stop (graceful shutdown) a VM.",
        document=_STOP_MUTATION,
        variables=id_variables,
        shape=identity_shape,
        writes=True,
    ),
    ("vm", "pause"): Action(
        doc="Pause a VM.",
        document=_PAUSE_MUTATION,
        variables=id_variables,
        shape=identity_shape,
        writes=True,
    ),
    ("vm", "resume"): Action(
        doc="Resume a paused VM.",
        document=_RESUME_MUTATION,
        variables=id_variables,
        shape=identity_shape,
        writes=True,
    ),
    ("vm", "reboot"): Action(
        doc="Reboot a VM.",
        document=_REBOOT_MUTATION,
        variables=id_variables,
        shape=identity_shape,
        writes=True,
    ),
}

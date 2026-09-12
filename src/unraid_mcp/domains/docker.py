"""Docker domain: containers, networks, logs, and container mutations."""

from __future__ import annotations

from typing import Any

from unraid_mcp.registry import (
    Action,
    ActionContext,
    ShapeFn,
    id_variables,
    identity_shape,
    no_variables,
    require_str,
)
from unraid_mcp.responses import cap_list, finalize

_LIST_QUERY = """\
query {
  docker {
    containers {
      id names image state status autoStart
      iconUrl webUiUrl isUpdateAvailable
    }
  }
}
"""

_GET_QUERY = """\
query ($id: PrefixedID!) {
  docker {
    container(id: $id) {
      id names image imageId command created
      ports { ip privatePort publicPort type }
      state status autoStart
      hostConfig { networkMode }
      iconUrl webUiUrl projectUrl supportUrl registryUrl
      isUpdateAvailable isOrphaned
    }
  }
}
"""

_LOGS_QUERY = """\
query ($id: PrefixedID!, $tail: Int) {
  docker {
    logs(id: $id, tail: $tail) {
      containerId
      lines { timestamp message }
      cursor
    }
  }
}
"""

_NETWORKS_QUERY = """\
query {
  docker {
    networks {
      id name driver scope enableIPv6 internal attachable
    }
  }
}
"""

_PORT_CONFLICTS_QUERY = """\
query {
  docker {
    portConflicts {
      containerPorts {
        privatePort type
        containers { id name }
      }
      lanPorts {
        lanIpPort publicPort type
        containers { id name }
      }
    }
  }
}
"""

_UPDATE_STATUS_QUERY = """\
query {
  docker {
    containerUpdateStatuses {
      name updateStatus
    }
  }
}
"""

_START_MUTATION = """\
mutation ($id: PrefixedID!) {
  docker { start(id: $id) { id names state status } }
}
"""

_STOP_MUTATION = """\
mutation ($id: PrefixedID!) {
  docker { stop(id: $id) { id names state status } }
}
"""

_PAUSE_MUTATION = """\
mutation ($id: PrefixedID!) {
  docker { pause(id: $id) { id names state status } }
}
"""

_UNPAUSE_MUTATION = """\
mutation ($id: PrefixedID!) {
  docker { unpause(id: $id) { id names state status } }
}
"""


def _logs_variables(params: dict[str, Any]) -> dict[str, Any] | None:
    v: dict[str, Any] = {"id": require_str(params, "id")}
    tail = params.get("tail")
    if tail is not None:
        v["tail"] = int(tail)
    return v


def _unwrap_docker(data: Any) -> Any:
    """Unwrap the docker wrapper from query results."""
    if isinstance(data, dict):
        docker = data.get("docker")
        if isinstance(docker, dict):
            return docker
    return data


def _docker_list_shape(key: str) -> ShapeFn:
    """Shape function that unwraps docker.{key} then caps the list."""

    def _shape(data: Any, params: dict[str, Any], budget: int) -> Any:
        inner = _unwrap_docker(data)
        if isinstance(inner, dict):
            items = inner.get(key)
            if isinstance(items, list):
                limit = params.get("limit")
                if isinstance(limit, str):
                    limit = int(limit)
                return finalize(cap_list(items, limit, byte_budget=budget), budget)
        return finalize(data, budget)

    return _shape


def _get_shape(data: Any, params: dict[str, Any], budget: int) -> Any:
    """Shape docker.get — unwrap the container from docker.container."""
    inner = _unwrap_docker(data)
    if isinstance(inner, dict):
        return finalize(inner.get("container"), budget)
    return finalize(data, budget)


async def _restart_run(ctx: ActionContext, params: dict[str, Any]) -> Any:
    """docker.restart = stop then start (no restart mutation in the API)."""
    container_id = require_str(params, "id")
    variables = {"id": container_id}
    await ctx.client.execute(_STOP_MUTATION, variables)
    data = await ctx.client.execute(_START_MUTATION, variables)
    return identity_shape(data, params, ctx.settings.max_response_bytes)


ACTIONS: dict[tuple[str, str], Action] = {
    ("docker", "list"): Action(
        doc="List all Docker containers.",
        document=_LIST_QUERY,
        variables=no_variables,
        shape=_docker_list_shape("containers"),
    ),
    ("docker", "get"): Action(
        doc="Get details for a single container by ID.",
        document=_GET_QUERY,
        variables=id_variables,
        shape=_get_shape,
    ),
    ("docker", "logs"): Action(
        doc="Container log lines.",
        document=_LOGS_QUERY,
        variables=_logs_variables,
        shape=identity_shape,
        profile="logs",
    ),
    ("docker", "networks"): Action(
        doc="Docker networks.",
        document=_NETWORKS_QUERY,
        variables=no_variables,
        shape=_docker_list_shape("networks"),
    ),
    ("docker", "port_conflicts"): Action(
        doc="Port conflicts between containers.",
        document=_PORT_CONFLICTS_QUERY,
        variables=no_variables,
        shape=identity_shape,
    ),
    ("docker", "update_status"): Action(
        doc="Update availability for all containers.",
        document=_UPDATE_STATUS_QUERY,
        variables=no_variables,
        shape=identity_shape,
    ),
    ("docker", "start"): Action(
        doc="Start a container.",
        document=_START_MUTATION,
        variables=id_variables,
        shape=identity_shape,
        writes=True,
    ),
    ("docker", "stop"): Action(
        doc="Stop a container.",
        document=_STOP_MUTATION,
        variables=id_variables,
        shape=identity_shape,
        writes=True,
    ),
    ("docker", "restart"): Action(
        doc="Restart a container (stop + start; no API restart mutation).",
        document=_STOP_MUTATION,
        variables=id_variables,
        shape=identity_shape,
        run=_restart_run,
        writes=True,
    ),
    ("docker", "pause"): Action(
        doc="Pause a container.",
        document=_PAUSE_MUTATION,
        variables=id_variables,
        shape=identity_shape,
        writes=True,
    ),
    ("docker", "unpause"): Action(
        doc="Unpause a container.",
        document=_UNPAUSE_MUTATION,
        variables=id_variables,
        shape=identity_shape,
        writes=True,
    ),
}

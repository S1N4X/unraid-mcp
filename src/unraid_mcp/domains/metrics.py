"""Metrics domain: CPU, memory, temperature, network, UPS."""

from __future__ import annotations

from unraid_mcp.registry import Action, identity_shape, no_variables

_CPU_QUERY = """\
query {
  metrics {
    cpu {
      id percentTotal
      cpus { percentTotal percentUser percentSystem percentIdle }
    }
  }
}
"""

_MEMORY_QUERY = """\
query {
  metrics {
    memory {
      id total used free available active buffcache
      percentTotal swapTotal swapUsed swapFree percentSwapTotal
    }
  }
}
"""

_TEMPERATURE_QUERY = """\
query {
  metrics {
    temperature {
      id
      sensors {
        id name type location
        current { value unit timestamp status }
        warning critical
      }
      summary { average warningCount criticalCount }
    }
  }
}
"""

_NETWORK_QUERY = """\
query {
  metrics {
    network {
      id name operstate
      bytesReceived bytesSent packetsReceived packetsSent
      receiveErrors transmitErrors
      rxSec txSec utilizationPercent lastUpdated
    }
  }
}
"""

_UPS_QUERY = """\
query {
  upsDevices {
    id name model status
    battery { chargeLevel estimatedRuntime health }
    power { inputVoltage outputVoltage loadPercentage nominalPower currentPower }
  }
}
"""

ACTIONS: dict[tuple[str, str], Action] = {
    ("metrics", "cpu"): Action(
        doc="CPU utilization metrics.",
        document=_CPU_QUERY,
        variables=no_variables,
        shape=identity_shape,
    ),
    ("metrics", "memory"): Action(
        doc="Memory utilization metrics.",
        document=_MEMORY_QUERY,
        variables=no_variables,
        shape=identity_shape,
    ),
    ("metrics", "temperature"): Action(
        doc="Temperature sensor readings.",
        document=_TEMPERATURE_QUERY,
        variables=no_variables,
        shape=identity_shape,
    ),
    ("metrics", "network"): Action(
        doc="Network interface metrics.",
        document=_NETWORK_QUERY,
        variables=no_variables,
        shape=identity_shape,
    ),
    ("metrics", "ups"): Action(
        doc="UPS device status.",
        document=_UPS_QUERY,
        variables=no_variables,
        shape=identity_shape,
    ),
}

"""System domain: read-only server information."""

from __future__ import annotations

from unraid_mcp.registry import Action, identity_shape, list_shape, no_variables

_INFO_QUERY = """\
query {
  info {
    os { hostname platform distro release kernel arch uptime }
    cpu { manufacturer brand cores threads speed }
    memory { layout { size type clockSpeed manufacturer } }
    baseboard { manufacturer model }
    system { manufacturer model }
    versions { core { unraid api kernel } }
  }
}
"""

_VERSIONS_QUERY = """\
query {
  info {
    versions {
      core { unraid api kernel }
      packages { openssl node docker php nginx git }
    }
  }
}
"""

_VARS_QUERY = """\
query {
  vars {
    id version name timeZone comment security workgroup
    useSsl port portssl useSsh portssh
    regTy regState regTo
    mdState mdNumDisks mdNumDisabled mdNumInvalid mdNumMissing
    sbName sbVersion sbClean sbSynced sbSyncErrs
  }
}
"""

_SERVER_QUERY = """\
query {
  server {
    id name status lanip localurl
  }
}
"""

_TIME_QUERY = """\
query {
  systemTime {
    currentTime timeZone useNtp ntpServers
  }
}
"""

_PLUGINS_QUERY = """\
query {
  plugins {
    name version
  }
}
"""

ACTIONS: dict[tuple[str, str], Action] = {
    ("system", "info"): Action(
        doc="Server hardware and OS information.",
        document=_INFO_QUERY,
        variables=no_variables,
        shape=identity_shape,
    ),
    ("system", "versions"): Action(
        doc="Unraid, API, kernel and package versions.",
        document=_VERSIONS_QUERY,
        variables=no_variables,
        shape=identity_shape,
    ),
    ("system", "vars"): Action(
        doc="Server variables (registration, array state, etc.).",
        document=_VARS_QUERY,
        variables=no_variables,
        shape=identity_shape,
    ),
    ("system", "server"): Action(
        doc="Server identity and status.",
        document=_SERVER_QUERY,
        variables=no_variables,
        shape=identity_shape,
    ),
    ("system", "time"): Action(
        doc="Current system time and NTP configuration.",
        document=_TIME_QUERY,
        variables=no_variables,
        shape=identity_shape,
    ),
    ("system", "plugins"): Action(
        doc="Installed plugins list.",
        document=_PLUGINS_QUERY,
        variables=no_variables,
        shape=list_shape("plugins"),
    ),
}

"""Notification domain: overview, list, archive, unread, archive_all."""

from __future__ import annotations

from typing import Any

from unraid_mcp.registry import (
    Action,
    id_variables,
    identity_shape,
    no_variables,
)

_OVERVIEW_QUERY = """\
query {
  notifications {
    overview {
      unread { info warning alert total }
      archive { info warning alert total }
    }
  }
}
"""

_LIST_QUERY = """\
query ($filter: NotificationFilter!) {
  notifications {
    list(filter: $filter) {
      id title subject description importance link type
      timestamp formattedTimestamp
    }
  }
}
"""

_ARCHIVE_MUTATION = """\
mutation ($id: PrefixedID!) {
  archiveNotification(id: $id) {
    id title subject importance type
  }
}
"""

_UNREAD_MUTATION = """\
mutation ($id: PrefixedID!) {
  unreadNotification(id: $id) {
    id title subject importance type
  }
}
"""

_ARCHIVE_ALL_MUTATION = """\
mutation {
  archiveAll {
    unread { info warning alert total }
    archive { info warning alert total }
  }
}
"""


def _list_variables(params: dict[str, Any]) -> dict[str, Any] | None:
    importance = params.get("importance")
    ntype = params.get("type", "UNREAD")
    offset = int(params.get("offset", 0))
    limit = int(params.get("limit", 20))
    filt: dict[str, Any] = {"type": ntype, "offset": offset, "limit": limit}
    if importance:
        filt["importance"] = importance
    return {"filter": filt}


ACTIONS: dict[tuple[str, str], Action] = {
    ("notification", "overview"): Action(
        doc="Notification counts by importance.",
        document=_OVERVIEW_QUERY,
        variables=no_variables,
        shape=identity_shape,
    ),
    ("notification", "list"): Action(
        doc="List notifications (filterable by type/importance).",
        document=_LIST_QUERY,
        variables=_list_variables,
        shape=identity_shape,
    ),
    ("notification", "archive"): Action(
        doc="Archive a notification by ID.",
        document=_ARCHIVE_MUTATION,
        variables=id_variables,
        shape=identity_shape,
        writes=True,
    ),
    ("notification", "unread"): Action(
        doc="Mark a notification as unread.",
        document=_UNREAD_MUTATION,
        variables=id_variables,
        shape=identity_shape,
        writes=True,
    ),
    ("notification", "archive_all"): Action(
        doc="Archive all notifications.",
        document=_ARCHIVE_ALL_MUTATION,
        variables=no_variables,
        shape=identity_shape,
        writes=True,
    ),
}

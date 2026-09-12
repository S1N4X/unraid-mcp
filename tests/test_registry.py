"""Registry tests: action set matches SPEC section 3, flags are consistent."""

from __future__ import annotations

from unraid_mcp.registry import get_actions

# Hardcoded from SPEC.md section 3.
EXPECTED_ACTIONS: set[tuple[str, str]] = {
    # system (reads only)
    ("system", "info"),
    ("system", "versions"),
    ("system", "vars"),
    ("system", "server"),
    ("system", "time"),
    ("system", "plugins"),
    # array
    ("array", "status"),
    ("array", "disks"),
    ("array", "parity_history"),
    ("array", "start"),
    ("array", "stop"),
    ("array", "parity_start"),
    ("array", "parity_pause"),
    ("array", "parity_resume"),
    ("array", "parity_cancel"),
    # docker
    ("docker", "list"),
    ("docker", "get"),
    ("docker", "logs"),
    ("docker", "networks"),
    ("docker", "port_conflicts"),
    ("docker", "update_status"),
    ("docker", "start"),
    ("docker", "stop"),
    ("docker", "restart"),
    ("docker", "pause"),
    ("docker", "unpause"),
    # vm
    ("vm", "list"),
    ("vm", "get"),
    ("vm", "start"),
    ("vm", "stop"),
    ("vm", "pause"),
    ("vm", "resume"),
    ("vm", "reboot"),
    # share (reads only)
    ("share", "list"),
    ("share", "get"),
    # notification
    ("notification", "overview"),
    ("notification", "list"),
    ("notification", "archive"),
    ("notification", "unread"),
    ("notification", "archive_all"),
    # metrics (reads only)
    ("metrics", "cpu"),
    ("metrics", "memory"),
    ("metrics", "temperature"),
    ("metrics", "network"),
    ("metrics", "ups"),
    # logs (reads only)
    ("logs", "list"),
    ("logs", "read"),
    # health (reads only)
    ("health", "ping"),
    ("health", "schema_check"),
    ("health", "capabilities"),
}


class TestRegistryCompleteness:
    def test_action_set_matches_spec(self) -> None:
        actions = get_actions()
        actual = set(actions.keys())
        assert actual == EXPECTED_ACTIONS

    def test_every_action_has_doc(self) -> None:
        for key, act in get_actions().items():
            assert act.doc, f"{key[0]}.{key[1]} missing doc string"

    def test_implemented_actions_have_document_or_run(self) -> None:
        for key, act in get_actions().items():
            if act.implemented:
                assert act.document or act.run is not None, (
                    f"{key[0]}.{key[1]} is implemented but has no document or run"
                )

    def test_destructive_implies_writes(self) -> None:
        for key, act in get_actions().items():
            if act.destructive:
                assert act.writes, f"{key[0]}.{key[1]} is destructive but writes=False"

    def test_not_implemented_has_reason(self) -> None:
        for key, act in get_actions().items():
            if not act.implemented:
                assert act.reason, f"{key[0]}.{key[1]} not implemented but no reason given"

"""Contract tests: every registered GraphQL document validates against the SDL snapshot."""

from __future__ import annotations

import re

import pytest
from graphql import build_schema, validate
from graphql import parse as gql_parse

from unraid_mcp.domains.health import load_snapshot_schema
from unraid_mcp.registry import get_actions

_SDL = load_snapshot_schema()
_SCHEMA = build_schema(_SDL)

# Fields that must never be selected (secrets / CSRF tokens).
_SENSITIVE_FIELDS = {"apikey", "csrfToken", "key", "clientSecret"}

_actions = get_actions()
_doc_actions = [(k, v) for k, v in sorted(_actions.items()) if v.document]


@pytest.mark.parametrize(
    "key,action",
    _doc_actions,
    ids=[f"{k[0]}.{k[1]}" for k, _ in _doc_actions],
)
class TestContractValidation:
    def test_document_validates(self, key: tuple[str, str], action: object) -> None:
        act = _actions[key]
        doc = gql_parse(act.document)
        errors = validate(_SCHEMA, doc)
        assert not errors, f"{key[0]}.{key[1]} validation errors: {errors}"

    def test_operation_type_matches_writes(self, key: tuple[str, str], action: object) -> None:
        act = _actions[key]
        doc = gql_parse(act.document)
        for defn in doc.definitions:
            if hasattr(defn, "operation"):
                is_mutation = defn.operation.value == "mutation"
                if act.writes:
                    assert is_mutation, (
                        f"{key[0]}.{key[1]} is flagged writes=True but document is not a mutation"
                    )
                else:
                    assert not is_mutation, (
                        f"{key[0]}.{key[1]} is flagged writes=False but document is a mutation"
                    )

    def test_no_sensitive_fields(self, key: tuple[str, str], action: object) -> None:
        act = _actions[key]
        # Simple text scan for sensitive field names as top-level tokens.
        # We parse each word from the document body.
        words = set(re.findall(r"\b(\w+)\b", act.document))
        found = words & _SENSITIVE_FIELDS
        assert not found, f"{key[0]}.{key[1]} selects sensitive field(s): {found}"

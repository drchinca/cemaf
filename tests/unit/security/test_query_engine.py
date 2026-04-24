"""Unit tests for cemaf.security.query_engine."""

from __future__ import annotations

from typing import Any

import pytest

from cemaf.core.enums import MemoryScope
from cemaf.core.types import Confidence
from cemaf.memory.base import MemoryItem
from cemaf.security.mappings import DictMappingProvider
from cemaf.security.query_engine import Predicate, PredicateSet, QueryEngine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_item(
    key: str = "k",
    scope: MemoryScope = MemoryScope.PROJECT,
    scope_path: str | None = None,
    value: dict | None = None,
) -> MemoryItem:
    return MemoryItem(
        scope=scope,
        key=key,
        value=value or {},
        confidence=Confidence(1.0),
        scope_path=scope_path,
    )


def _make_engine(roles: list[str], direct_access: list[dict] | None = None) -> QueryEngine:
    data: dict[str, Any] = {
        "users": {
            "user": {
                "type": "user",
                "attributes": {},
                "roles": roles,
                "direct_access": direct_access or [],
            }
        },
        "teams": {},
    }
    return QueryEngine(DictMappingProvider(data))


# ---------------------------------------------------------------------------
# Predicate + PredicateSet basics
# ---------------------------------------------------------------------------


def test_predicate_set_starts_empty() -> None:
    ps = PredicateSet()
    assert ps.predicates == ()
    assert ps.to_sql() == ""
    assert ps.to_params() == ()


def test_predicate_set_append_is_immutable() -> None:
    ps = PredicateSet()
    p = Predicate(sql="scope = ANY($1)", params=(["project"],), description="test")
    ps2 = ps.append(p)

    # Original unchanged
    assert ps.predicates == ()
    assert len(ps2.predicates) == 1


def test_to_sql_single_predicate() -> None:
    p = Predicate(sql="scope = ANY($1)", params=(["project"],))
    ps = PredicateSet(predicates=(p,))
    assert ps.to_sql() == "scope = ANY($1)"


def test_to_sql_renumbers_placeholders() -> None:
    p1 = Predicate(sql="scope = ANY($1)", params=(["project"],))
    p2 = Predicate(sql="scope_path LIKE $1", params=("/intel/%",))
    ps = PredicateSet(predicates=(p1, p2))

    sql = ps.to_sql(offset=1)
    # After renumbering: first pred uses $1, second uses $2
    assert "$1" in sql
    assert "$2" in sql
    # Both predicates joined by AND
    assert " AND " in sql


def test_to_sql_with_offset() -> None:
    p = Predicate(sql="scope = ANY($1)", params=(["session"],))
    ps = PredicateSet(predicates=(p,))
    sql = ps.to_sql(offset=5)
    assert "$5" in sql
    assert "$1" not in sql


def test_to_params_flat_order() -> None:
    p1 = Predicate(sql="scope = ANY($1)", params=(["project", "session"],))
    p2 = Predicate(sql="scope_path LIKE $1", params=("/intel/%",))
    ps = PredicateSet(predicates=(p1, p2))
    params = ps.to_params()
    assert params == (["project", "session"], "/intel/%")


# ---------------------------------------------------------------------------
# filter() — Python-side evaluation
# ---------------------------------------------------------------------------


def test_filter_matches_scope_predicate_python() -> None:
    p = Predicate(sql="scope = ANY($1)", params=(["project"],))
    ps = PredicateSet(predicates=(p,))

    items = [
        make_item(key="a", scope=MemoryScope.PROJECT),
        make_item(key="b", scope=MemoryScope.SESSION),
    ]
    result = ps.filter(items)
    assert len(result) == 1
    assert result[0].key == "a"


def test_filter_scope_path_like_python() -> None:
    p = Predicate(sql="scope_path LIKE $1", params=("/intel/%",))
    ps = PredicateSet(predicates=(p,))

    items = [
        make_item(key="intel", scope_path="/intel/ops"),
        make_item(key="finance", scope_path="/finance/q4"),
        make_item(key="no_path", scope_path=None),
    ]
    result = ps.filter(items)
    assert len(result) == 1
    assert result[0].key == "intel"


def test_filter_value_neq_all_python() -> None:
    p = Predicate(sql="value_json->>'status' != ALL($1::text[])", params=(["deleted", "archived"],))
    ps = PredicateSet(predicates=(p,))

    items = [
        make_item(key="active", value={"status": "active"}),
        make_item(key="deleted", value={"status": "deleted"}),
        make_item(key="archived", value={"status": "archived"}),
    ]
    result = ps.filter(items)
    assert len(result) == 1
    assert result[0].key == "active"


def test_filter_value_eq_python() -> None:
    p = Predicate(sql="value_json->>'env' = $1", params=("prod",))
    ps = PredicateSet(predicates=(p,))

    items = [
        make_item(key="prod_item", value={"env": "prod"}),
        make_item(key="dev_item", value={"env": "dev"}),
    ]
    result = ps.filter(items)
    assert len(result) == 1
    assert result[0].key == "prod_item"


def test_filter_unknown_predicate_passes_conservatively() -> None:
    """Unrecognised SQL templates include all items (conservative)."""
    p = Predicate(sql="some_unknown_condition($1)", params=("x",))
    ps = PredicateSet(predicates=(p,))

    items = [make_item(key="a"), make_item(key="b")]
    result = ps.filter(items)
    assert len(result) == 2


# ---------------------------------------------------------------------------
# QueryEngine.build_predicates
# ---------------------------------------------------------------------------


def test_build_predicates_produces_scope_predicate() -> None:
    """A READER principal should get an allowed-scopes predicate."""
    engine = _make_engine(roles=["READER"])
    pset = engine.build_predicates("user", intent="read")
    assert len(pset.predicates) >= 1
    scope_preds = [p for p in pset.predicates if "scope = ANY" in p.sql]
    assert len(scope_preds) == 1


def test_build_predicates_system_gets_all_scopes() -> None:
    from cemaf.security.rbac import ROLE_SYSTEM  # noqa: PLC0415

    engine = _make_engine(roles=[ROLE_SYSTEM])
    pset = engine.build_predicates("user", intent="read")
    scope_preds = [p for p in pset.predicates if "scope = ANY" in p.sql]
    assert len(scope_preds) == 1
    # All MemoryScope values present
    allowed = scope_preds[0].params[0]
    assert set(allowed) == {s.value for s in MemoryScope}


def test_build_predicates_with_base_scope_restriction() -> None:
    """When base_scope is set, only that scope appears in the predicate."""
    engine = _make_engine(roles=["READER"])
    pset = engine.build_predicates("user", base_scope=MemoryScope.SESSION, intent="read")
    scope_preds = [p for p in pset.predicates if "scope = ANY" in p.sql]
    assert len(scope_preds) == 1
    assert scope_preds[0].params[0] == ["session"]


def test_build_predicates_direct_access_adds_path_predicate() -> None:
    engine = _make_engine(
        roles=[],
        direct_access=[{"scope": "project", "scope_path_prefix": "/intel/", "actions": ["read"]}],
    )
    pset = engine.build_predicates("user", intent="read")
    path_preds = [p for p in pset.predicates if "scope_path LIKE" in p.sql]
    assert len(path_preds) == 1
    assert path_preds[0].params[0] == "/intel/%"


def test_build_predicates_with_extra_filters() -> None:
    engine = _make_engine(roles=["READER"])
    pset = engine.build_predicates("user", intent="read", extra_filters={"env": "prod"})
    value_eq_preds = [p for p in pset.predicates if "= $" in p.sql and "value_json" in p.sql]
    assert len(value_eq_preds) >= 1
    assert value_eq_preds[-1].params[0] == "prod"


# ---------------------------------------------------------------------------
# SQL injection safety
# ---------------------------------------------------------------------------


def test_no_sql_injection_in_sql_string() -> None:
    """Dangerous strings are in params, not in the SQL fragment."""
    evil = "'; DROP TABLE audit_log; --"
    p = Predicate(
        sql="value_json->>'field' = $1",
        params=(evil,),
        description="injection test",
    )
    ps = PredicateSet(predicates=(p,))

    sql = ps.to_sql()
    # The evil string must NOT appear in the SQL template
    assert evil not in sql
    # It must appear in the params
    assert ps.to_params() == (evil,)


def test_no_sql_injection_from_extra_filters() -> None:
    """extra_filters values travel via params, not the SQL string."""
    engine = _make_engine(roles=["READER"])
    evil = "'; DROP TABLE users; --"
    pset = engine.build_predicates("user", intent="read", extra_filters={"field": evil})

    sql_full = pset.to_sql()
    assert evil not in sql_full

    all_params = pset.to_params()
    # The evil value appears as a parameter
    assert any(evil == str(param) for param in all_params if not isinstance(param, list))

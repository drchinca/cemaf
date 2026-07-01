"""Unit tests for cemaf.security.mappings."""

from __future__ import annotations

import sys
from typing import Any

import pytest

from cemaf.core.enums import MemoryScope
from cemaf.security.mappings import (
    DictMappingProvider,
    Principal,
    ScopeAccess,
    YAMLMappingProvider,
)

# ---------------------------------------------------------------------------
# Test data
# ---------------------------------------------------------------------------

_DATA: dict[str, Any] = {
    "users": {
        "alice": {
            "type": "user",
            "attributes": {"clearance": "SECRET", "department": "intel"},
            "roles": ["WRITER"],
            "direct_access": [
                {
                    "scope": "project",
                    "scope_path_prefix": "/intel/",
                    "actions": ["read", "write"],
                    "abac_conditions": {"clearance": "SECRET"},
                }
            ],
        },
        "bob": {
            "type": "user",
            "attributes": {"clearance": "UNCLASSIFIED"},
            "roles": ["READER"],
            "direct_access": [],
        },
        "charlie": {
            "type": "service",
            "attributes": {},
            "roles": [],
            "direct_access": [],
        },
    },
    "teams": {
        "intel_ops": {
            "members": ["alice", "charlie"],
            "roles": ["SCOPE_ADMIN"],
        },
        "public": {
            "members": ["bob"],
            "roles": ["READER"],
        },
    },
}


@pytest.fixture
def provider() -> DictMappingProvider:
    return DictMappingProvider(_DATA)


# ---------------------------------------------------------------------------
# get_principal
# ---------------------------------------------------------------------------


def test_dict_provider_get_principal(provider: DictMappingProvider) -> None:
    p = provider.get_principal("alice")
    assert p is not None
    assert isinstance(p, Principal)
    assert p.id == "alice"
    assert p.type == "user"
    assert p.attributes["clearance"] == "SECRET"


def test_dict_provider_get_principal_unknown(provider: DictMappingProvider) -> None:
    assert provider.get_principal("nobody") is None


def test_dict_provider_get_principal_service(provider: DictMappingProvider) -> None:
    p = provider.get_principal("charlie")
    assert p is not None
    assert p.type == "service"


# ---------------------------------------------------------------------------
# get_roles
# ---------------------------------------------------------------------------


def test_dict_provider_user_roles(provider: DictMappingProvider) -> None:
    """Alice's own direct roles are returned."""
    roles = provider.get_roles("bob")
    # Bob has READER directly and inherits READER from 'public' team
    assert "READER" in roles


def test_dict_provider_team_roles_inherited(provider: DictMappingProvider) -> None:
    """Alice inherits SCOPE_ADMIN from intel_ops team membership."""
    roles = provider.get_roles("alice")
    assert "WRITER" in roles  # direct role
    assert "SCOPE_ADMIN" in roles  # inherited from intel_ops


def test_dict_provider_team_roles_inherited_service(provider: DictMappingProvider) -> None:
    """Charlie (service) inherits SCOPE_ADMIN from intel_ops membership."""
    roles = provider.get_roles("charlie")
    assert "SCOPE_ADMIN" in roles


def test_dict_provider_roles_unknown_user(provider: DictMappingProvider) -> None:
    roles = provider.get_roles("ghost")
    assert roles == frozenset()


# ---------------------------------------------------------------------------
# get_direct_access
# ---------------------------------------------------------------------------


def test_dict_provider_direct_access(provider: DictMappingProvider) -> None:
    accesses = provider.get_direct_access("alice")
    assert len(accesses) == 1
    sa = accesses[0]
    assert isinstance(sa, ScopeAccess)
    assert sa.scope == MemoryScope.PROJECT
    assert sa.scope_path_prefix == "/intel/"
    assert "read" in sa.actions
    assert "write" in sa.actions
    assert sa.abac_conditions["clearance"] == "SECRET"


def test_dict_provider_direct_access_empty(provider: DictMappingProvider) -> None:
    accesses = provider.get_direct_access("bob")
    assert accesses == ()


def test_dict_provider_direct_access_none_scope() -> None:
    """scope=None (absent) means all scopes."""
    data: dict[str, Any] = {
        "users": {
            "admin": {
                "type": "user",
                "attributes": {},
                "roles": [],
                "direct_access": [
                    {"actions": ["read", "write", "delete"]}  # no scope key
                ],
            }
        },
        "teams": {},
    }
    p = DictMappingProvider(data)
    accesses = p.get_direct_access("admin")
    assert len(accesses) == 1
    assert accesses[0].scope is None


def test_dict_provider_direct_access_invalid_scope_skipped() -> None:
    """An unrecognised scope string should be silently skipped."""
    data: dict[str, Any] = {
        "users": {
            "user_x": {
                "type": "user",
                "attributes": {},
                "roles": [],
                "direct_access": [
                    {"scope": "nonexistent_scope", "actions": ["read"]},
                    {"scope": "project", "actions": ["read"]},
                ],
            }
        },
        "teams": {},
    }
    p = DictMappingProvider(data)
    accesses = p.get_direct_access("user_x")
    # Only the valid 'project' entry should survive
    assert len(accesses) == 1
    assert accesses[0].scope == MemoryScope.PROJECT


# ---------------------------------------------------------------------------
# YAMLMappingProvider — import failure
# ---------------------------------------------------------------------------


def test_yaml_provider_raises_without_pyyaml(tmp_path: Any) -> None:
    """If pyyaml is not installed, YAMLMappingProvider raises ImportError with hint."""
    yaml_file = tmp_path / "mappings.yaml"
    yaml_file.write_text("users: {}\nteams: {}\n")

    provider_yaml = YAMLMappingProvider(str(yaml_file))

    # Simulate missing pyyaml by temporarily making 'yaml' unimportable
    original_yaml = sys.modules.get("yaml")
    sys.modules["yaml"] = None  # type: ignore[assignment]
    try:
        with pytest.raises(ImportError, match="pyyaml"):
            provider_yaml.get_principal("alice")
    finally:
        if original_yaml is None:
            sys.modules.pop("yaml", None)
        else:
            sys.modules["yaml"] = original_yaml
        # Reset lazy delegate so a subsequent real test isn't affected
        provider_yaml._delegate = None


def test_yaml_provider_loads_if_pyyaml_available(tmp_path: Any) -> None:
    """YAMLMappingProvider delegates to DictMappingProvider after loading YAML."""
    pytest.importorskip("yaml")

    import yaml as _yaml  # noqa: PLC0415

    yaml_content = _yaml.dump(_DATA)
    yaml_file = tmp_path / "mappings.yaml"
    yaml_file.write_text(yaml_content)

    yp = YAMLMappingProvider(str(yaml_file))
    p = yp.get_principal("alice")
    assert p is not None
    assert p.id == "alice"
    roles = yp.get_roles("alice")
    assert "WRITER" in roles

"""
Bring-your-own-mappings RBAC/ABAC module.

Define your team/user -> role/scope access mappings as a Python dict
or YAML file.  Zero database required for basic use.

Data format expected by DictMappingProvider::

    {
        "users": {
            "alice": {
                "type": "user",
                "attributes": {"clearance": "SECRET"},
                "roles": ["WRITER"],
                "direct_access": [
                    {
                        "scope": "project",
                        "scope_path_prefix": "/intel/",
                        "actions": ["read", "write"]
                    }
                ]
            }
        },
        "teams": {
            "intel_ops": {
                "members": ["alice", "bob"],
                "roles": ["READER"]
            }
        }
    }
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

from cemaf.core.enums import MemoryScope

# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Principal:
    """An authenticated entity (user, team, or service)."""

    id: str
    type: Literal["user", "team", "service"]
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ScopeAccess:
    """
    Grants a principal access to a particular scope (or all scopes).

    Fields
    ------
    scope:
        MemoryScope this grant applies to.  ``None`` means all scopes.
    scope_path_prefix:
        If set, limits access to items whose ``scope_path`` starts with
        this prefix (e.g. ``"/intel/"``).
    actions:
        Frozenset of allowed actions, e.g. ``frozenset({"read", "write"})``.
    abac_conditions:
        Attribute-based conditions that must be satisfied.  Each key maps to
        either a scalar equality check or a dict with ``"$exclude"`` for
        exclusion.  Example: ``{"clearance": "SECRET"}``.
    """

    scope: MemoryScope | None
    scope_path_prefix: str | None
    actions: frozenset[str]
    abac_conditions: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class MappingProvider(Protocol):
    """Contract for any mapping backend (dict, YAML, database, etc.)."""

    def get_principal(self, principal_id: str) -> Principal | None:
        """Return the Principal for *principal_id*, or None if unknown."""
        ...

    def get_roles(self, principal_id: str) -> frozenset[str]:
        """
        Return the union of direct roles and roles inherited from team
        membership for *principal_id*.
        """
        ...

    def get_direct_access(self, principal_id: str) -> tuple[ScopeAccess, ...]:
        """Return explicit ScopeAccess grants for *principal_id*."""
        ...


# ---------------------------------------------------------------------------
# DictMappingProvider
# ---------------------------------------------------------------------------


class DictMappingProvider:
    """
    In-process MappingProvider backed by a plain Python dict.

    Suitable for unit tests, small teams, and configuration-file-driven
    deployments where a database is overkill.
    """

    def __init__(self, data: dict[str, Any]) -> None:
        self._users: dict[str, Any] = data.get("users", {})
        self._teams: dict[str, Any] = data.get("teams", {})

    # ------------------------------------------------------------------
    # MappingProvider implementation
    # ------------------------------------------------------------------

    def get_principal(self, principal_id: str) -> Principal | None:
        if principal_id not in self._users:
            return None
        raw = self._users[principal_id]
        return Principal(
            id=principal_id,
            type=raw.get("type", "user"),
            attributes=dict(raw.get("attributes", {})),
        )

    def get_roles(self, principal_id: str) -> frozenset[str]:
        """Merge the user's own roles with roles from all teams they belong to."""
        user_data = self._users.get(principal_id, {})
        roles: set[str] = set(user_data.get("roles", []))

        # Inherit roles from every team where this user is a member
        for team_data in self._teams.values():
            members: list[str] = team_data.get("members", [])
            if principal_id in members:
                roles.update(team_data.get("roles", []))

        return frozenset(roles)

    def get_direct_access(self, principal_id: str) -> tuple[ScopeAccess, ...]:
        user_data = self._users.get(principal_id, {})
        raw_entries: list[dict[str, Any]] = user_data.get("direct_access", [])
        result: list[ScopeAccess] = []

        for entry in raw_entries:
            scope_raw: str | None = entry.get("scope")
            scope: MemoryScope | None = None
            if scope_raw is not None:
                try:
                    scope = MemoryScope(scope_raw)
                except ValueError:
                    # Unknown scope string — skip this entry rather than crash
                    continue

            actions: frozenset[str] = frozenset(entry.get("actions", []))
            scope_path_prefix: str | None = entry.get("scope_path_prefix")
            abac_conditions: dict[str, Any] = dict(entry.get("abac_conditions", {}))

            result.append(
                ScopeAccess(
                    scope=scope,
                    scope_path_prefix=scope_path_prefix,
                    actions=actions,
                    abac_conditions=abac_conditions,
                )
            )

        return tuple(result)


# ---------------------------------------------------------------------------
# YAMLMappingProvider
# ---------------------------------------------------------------------------


class YAMLMappingProvider:
    """
    MappingProvider that reads mappings from a YAML file.

    The file is loaded lazily on first method call.  The YAML structure must
    match the format expected by DictMappingProvider.

    Requires ``pyyaml`` to be installed.  Raises ``ImportError`` with a
    helpful install hint if it is not available.
    """

    def __init__(self, path: str) -> None:
        self._path = path
        self._delegate: DictMappingProvider | None = None

    # ------------------------------------------------------------------
    # Lazy loader
    # ------------------------------------------------------------------

    def _load(self) -> DictMappingProvider:
        if self._delegate is not None:
            return self._delegate

        try:
            import yaml  # noqa: PLC0415
        except ImportError as exc:
            raise ImportError(
                "pyyaml is required to use YAMLMappingProvider. "
                "Install it with: pip install 'cemaf[security-yaml]' or pip install pyyaml>=6.0"
            ) from exc

        with open(self._path) as fh:
            raw: dict[str, Any] = yaml.safe_load(fh) or {}

        self._delegate = DictMappingProvider(raw)
        return self._delegate

    # ------------------------------------------------------------------
    # MappingProvider implementation (delegates to DictMappingProvider)
    # ------------------------------------------------------------------

    def get_principal(self, principal_id: str) -> Principal | None:
        return self._load().get_principal(principal_id)

    def get_roles(self, principal_id: str) -> frozenset[str]:
        return self._load().get_roles(principal_id)

    def get_direct_access(self, principal_id: str) -> tuple[ScopeAccess, ...]:
        return self._load().get_direct_access(principal_id)

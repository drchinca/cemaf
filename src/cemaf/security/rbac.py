"""
RBAC/ABAC enforcer for memory scope access control.

RBACEnforcer: role-based access control with optional ABAC attribute conditions.
MappingBasedRBACEnforcer: alias for RBACEnforcer (for compatibility).
RBACMemoryStore: decorator that enforces RBAC on any MemoryStore.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from cemaf.core.enums import MemoryScope
from cemaf.memory.base import MemoryItem, MemoryStore
from cemaf.security.mappings import MappingProvider, ScopeAccess

if TYPE_CHECKING:
    from cemaf.audit.protocols import AuditLog


# ---------------------------------------------------------------------------
# Role constants
# ---------------------------------------------------------------------------

ROLE_READER = "READER"
ROLE_WRITER = "WRITER"
ROLE_SCOPE_ADMIN = "SCOPE_ADMIN"
ROLE_SYSTEM = "SYSTEM"

_ITEM_LEVEL_ACTIONS: frozenset[str] = frozenset({"read", "write", "delete"})

_ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    ROLE_READER: frozenset({"read"}),
    ROLE_WRITER: frozenset({"read", "write", "delete"}),
    ROLE_SCOPE_ADMIN: frozenset({"read", "write", "delete", "list", "admin"}),
    ROLE_SYSTEM: frozenset({"read", "write", "delete", "list", "admin", "bypass"}),
}


# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------


class PermissionDeniedError(Exception):
    """Raised when a principal lacks permission for an action on a scope."""

    def __init__(
        self,
        principal_id: str,
        action: str,
        scope: str,
        reason: str = "",
    ) -> None:
        self.principal_id = principal_id
        self.action = action
        self.scope = scope
        self.reason = reason
        detail = f"Principal '{principal_id}' cannot '{action}' on scope '{scope}'"
        if reason:
            detail += f": {reason}"
        super().__init__(detail)


# ---------------------------------------------------------------------------
# RBACEnforcer
# ---------------------------------------------------------------------------


class RBACEnforcer:
    """
    Evaluate whether a principal may perform *action* on *scope*.

    Resolution order:
    1. SYSTEM role -> always permitted.
    2. Role-based permissions from ``_ROLE_PERMISSIONS``.
    3. Direct-access grants with optional scope-path prefix and ABAC checks.
    """

    def __init__(self, mapping_provider: MappingProvider) -> None:
        self._provider = mapping_provider

    def can(
        self,
        principal_id: str,
        action: str,
        scope: MemoryScope,
        scope_path: str | None = None,
    ) -> bool:
        """
        Return True if *principal_id* is allowed to perform *action* on *scope*.

        Args:
            principal_id: The identity being checked.
            action: One of ``"read"``, ``"write"``, ``"delete"``, ``"list"``,
                    ``"admin"``, ``"bypass"``.
            scope: The MemoryScope to check against.
            scope_path: Hierarchical scope path for path-prefix checks.
        """
        roles = self._provider.get_roles(principal_id)

        # SYSTEM bypasses every check
        if ROLE_SYSTEM in roles:
            return True

        # Role-level check
        for role in roles:
            perms = _ROLE_PERMISSIONS.get(role, frozenset())
            if action in perms:
                return True

        # Direct-access grants
        principal = self._provider.get_principal(principal_id)
        attributes: dict[str, Any] = principal.attributes if principal is not None else {}

        for grant in self._provider.get_direct_access(principal_id):
            if not self._grant_matches(grant, action, scope, scope_path, attributes):
                continue
            return True

        return False

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _grant_matches(
        grant: ScopeAccess,
        action: str,
        scope: MemoryScope,
        scope_path: str | None,
        attributes: dict[str, Any],
    ) -> bool:
        """
        Return True if *grant* permits *action* on *scope* for the given
        principal attributes.

        Scope-path prefix semantics:
        - For item-level actions (``read``, ``write``, ``delete``), the
          item's ``scope_path`` must start with the grant prefix.
        - For ``list`` (and ``admin``/``bypass``), a grant with a
          ``scope_path_prefix`` permits access to the scope as a whole;
          results are post-filtered by ``list_by_scope`` in
          ``RBACMemoryStore``.
        """
        # Action check
        if action not in grant.actions:
            return False

        # Scope check (None grant scope = all scopes)
        if grant.scope is not None and grant.scope != scope:
            return False

        # Scope-path prefix check — only enforced for item-level actions
        if (
            grant.scope_path_prefix is not None
            and action in _ITEM_LEVEL_ACTIONS
            and (scope_path is None or not scope_path.startswith(grant.scope_path_prefix))
        ):
            return False

        # ABAC conditions
        for attr_key, expected in grant.abac_conditions.items():
            actual = attributes.get(attr_key)
            if actual != expected:
                return False

        return True


# Alias for explicit naming
MappingBasedRBACEnforcer = RBACEnforcer


# ---------------------------------------------------------------------------
# RBACMemoryStore — decorator
# ---------------------------------------------------------------------------


class RBACMemoryStore(MemoryStore):
    """
    MemoryStore decorator that enforces RBAC on every operation.

    Wraps *inner* and checks permissions via *enforcer* before delegating.
    Access denials are logged to *audit_log* (if provided) as ACCESS_DENIED
    AuditEntry records.

    ``cleanup_expired()`` is a system operation and skips RBAC checks.

    Redaction:
        If *inner* has a redaction hook, it is copied so that items read
        through this wrapper are also redacted.
    """

    def __init__(
        self,
        inner: MemoryStore,
        enforcer: RBACEnforcer,
        principal_id: str,
        audit_log: AuditLog | None = None,
    ) -> None:
        super().__init__()
        self._inner = inner
        self._enforcer = enforcer
        self._principal_id = principal_id
        self._audit_log = audit_log

        # Propagate inner store's redaction hook if present
        if inner._redaction_hook is not None:
            self.set_redaction_hook(inner._redaction_hook)

    # ------------------------------------------------------------------
    # MemoryStore ABC implementation
    # ------------------------------------------------------------------

    async def get(self, scope: MemoryScope, key: str) -> MemoryItem | None:
        self._check("read", scope, key)
        item = await self._inner.get(scope, key)
        return self._apply_redaction(item)

    async def set(self, item: MemoryItem) -> None:
        self._check("write", item.scope, item.key)
        await self._inner.set(item)

    async def delete(self, scope: MemoryScope, key: str) -> bool:
        self._check("delete", scope, key)
        return await self._inner.delete(scope, key)

    async def list_by_scope(self, scope: MemoryScope) -> tuple[MemoryItem, ...]:
        self._check("list", scope)

        items = await self._inner.list_by_scope(scope)

        # Apply redaction to every item
        redacted: list[MemoryItem] = []
        for item in items:
            r = self._apply_redaction(item)
            if r is not None:
                redacted.append(r)

        # Scope-path prefix filtering: if principal has any direct_access
        # grant with a scope_path_prefix for this scope, exclude items
        # whose scope_path does not start with that prefix.
        allowed_prefixes = self._collect_path_prefixes(scope)
        if allowed_prefixes:
            redacted = [item for item in redacted if self._item_within_prefixes(item, allowed_prefixes)]

        return tuple(redacted)

    async def cleanup_expired(self) -> int:
        """Delegate cleanup to inner store — no RBAC check (system operation)."""
        return await self._inner.cleanup_expired()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _check(self, action: str, scope: MemoryScope, key: str = "") -> None:
        """Raise PermissionDeniedError (and log to audit) if access is denied."""
        if not self._enforcer.can(self._principal_id, action, scope):
            self._record_denial(action, scope, key)
            raise PermissionDeniedError(
                principal_id=self._principal_id,
                action=action,
                scope=scope.value,
            )

    def _record_denial(self, action: str, scope: MemoryScope, key: str) -> None:
        """Append an ACCESS_DENIED audit entry (fire-and-forget, sync-safe)."""
        if self._audit_log is None:
            return

        import asyncio  # noqa: PLC0415

        # Import lazily to avoid potential circular at module parse time.
        from cemaf.audit.models import AuditEntry, AuditEntryType  # noqa: PLC0415

        entry = AuditEntry.create(
            type=AuditEntryType.ACCESS_DENIED,
            run_id="security",
            source=self._principal_id,
            payload={
                "action": action,
                "scope": scope.value,
                "key": key,
            },
        )

        # Schedule the coroutine if an event loop is running; otherwise
        # create a task so callers don't need to be async themselves.
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is not None and loop.is_running():
            loop.create_task(self._audit_log.append(entry))
        else:
            # Best-effort synchronous path (tests without a running loop)
            import threading  # noqa: PLC0415

            def _run() -> None:
                asyncio.run(self._audit_log.append(entry))  # type: ignore[union-attr]

            t = threading.Thread(target=_run, daemon=True)
            t.start()
            t.join(timeout=2.0)

    def _collect_path_prefixes(self, scope: MemoryScope) -> list[str]:
        """Return scope_path_prefix values from direct_access grants for *scope*."""
        prefixes: list[str] = []
        for grant in self._enforcer._provider.get_direct_access(self._principal_id):
            if grant.scope_path_prefix is None:
                continue
            if grant.scope is None or grant.scope == scope:
                prefixes.append(grant.scope_path_prefix)
        return prefixes

    @staticmethod
    def _item_within_prefixes(item: MemoryItem, prefixes: list[str]) -> bool:
        """Return True if item.scope_path starts with any of *prefixes*."""
        if item.scope_path is None:
            return False
        return any(item.scope_path.startswith(p) for p in prefixes)

"""Governance descriptions and authorized DocSource export boundaries for OKF."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from cemaf.core.enums import MemoryScope
from cemaf.docs_api.index import DocEntry, DocEntryKind
from cemaf.docs_api.protocols import DocSource
from cemaf.security.mappings import MappingProvider
from cemaf.security.rbac import ScopeAuthorizer


@dataclass(frozen=True)
class GovernanceDocSource:
    """Describe explicitly selected identities and grants from a MappingProvider.

    These can be sensitive. Wrap this source in GovernedDocSource for restricted
    export. Importing the descriptions never changes the mapping provider.
    """

    provider: MappingProvider
    principal_ids: tuple[str, ...]

    @property
    def name(self) -> str:
        return "governance"

    def load(self) -> Iterable[DocEntry]:
        roles_seen: set[str] = set()
        for principal_id in sorted(set(self.principal_ids)):
            principal = self.provider.get_principal(principal_id)
            if principal is None:
                raise ValueError("Cannot describe an unknown principal")
            roles = sorted(self.provider.get_roles(principal_id))
            yield DocEntry(
                id=f"principal:{principal_id}",
                kind=DocEntryKind.SPEC,
                title=f"Principal {principal_id}",
                body="An identity described by the mapping provider. This document grants no access.",
                source=self.name,
                metadata={
                    "okf_type": "Principal",
                    "principal_type": principal.type,
                    "attributes": principal.attributes,
                    "related_ids": [f"role:{role}" for role in roles],
                },
            )
            for role in roles:
                if role in roles_seen:
                    continue
                roles_seen.add(role)
                yield DocEntry(
                    id=f"role:{role}",
                    kind=DocEntryKind.SPEC,
                    title=f"Role {role}",
                    body=(
                        "Role membership reported by the mapping provider. "
                        "Runtime authorization defines its permissions."
                    ),
                    source=self.name,
                    metadata={"okf_type": "Role"},
                )
            for index, grant in enumerate(self.provider.get_direct_access(principal_id)):
                yield DocEntry(
                    id=f"grant:{principal_id}:{index}",
                    kind=DocEntryKind.SPEC,
                    title=f"Access grant {index} for {principal_id}",
                    body="A descriptive snapshot of a direct-access grant, including ABAC conditions. "
                    "RBACEnforcer and the current MappingProvider remain the enforcement authority.",
                    source=self.name,
                    metadata={
                        "okf_type": "Access Policy",
                        "related_ids": [f"principal:{principal_id}"],
                        "scope": grant.scope.value if grant.scope is not None else None,
                        "scope_path_prefix": grant.scope_path_prefix,
                        "actions": sorted(grant.actions),
                        "abac_conditions": grant.abac_conditions,
                    },
                )


@dataclass(frozen=True)
class GovernedDocSource:
    """All-or-nothing disclosure using caller-owned scope bindings and policy.

    Authorization is checked on each load. Document metadata cannot assign its
    own privileges or scope. Rejecting the whole source avoids disclosing a
    partial document whose prose might refer to a denied entry.
    """

    source: DocSource
    authorizer: ScopeAuthorizer
    principal_id: str
    bindings: Mapping[str, tuple[MemoryScope, str]]

    @property
    def name(self) -> str:
        return f"governed:{self.source.name}"

    def load(self) -> Iterable[DocEntry]:
        entries = tuple(self.source.load())
        for entry in entries:
            binding = self.bindings.get(entry.id)
            if binding is None or not self.authorizer.can(
                self.principal_id, "read", binding[0], scope_path=binding[1]
            ):
                raise PermissionError("OKF source disclosure denied")
        return entries

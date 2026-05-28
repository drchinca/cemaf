"""Core — the bottom of the import graph. Types, enums, Result, utilities.

Every other CEMAF module can import from `core`; `core` imports from nothing
else in this project. That makes it the safe place for primitives that
cross package boundaries without creating cycles.

Key exports:
- **NewType IDs**: `AgentID`, `NodeID`, `RunID`, `ToolID`, `TokenCount`,
  `Confidence`. Stringly-typed domain identifiers are an anti-pattern —
  use these so mypy catches cross-slot mistakes.
- **Enums**: `MemoryScope`, `NodeType`, `RunStatus`, `AgentStatus`,
  `ToolRiskLevel`, `Priority`, `ExclusionReason`, `VerificationStatus`,
  `ContextArtifactType`.
- **Result[T]**: the canonical success/failure wrapper used by `Tool.execute`,
  moderation, evals, and anywhere we want to return structured errors
  without raising.
- **Domain**: `DomainContext`, `ProvenanceChain`, `ProvenanceLink`,
  `SourceReference` — the primitives for cross-run provenance.
- **Execution**: `CancellationToken` for cooperative cancellation.
- **Constants**: `DEFAULT_MAX_RETRIES`, `DEFAULT_TIMEOUT_SECONDS`,
  `MAX_CONTEXT_TOKENS`, `MAX_PARALLEL_NODES`.
- **Utilities**: `utc_now()`, `generate_id()` — use these (not `datetime.now()`
  and not `uuid.uuid4()` directly) for testability and determinism.

Rule: `core` is the only package allowed module-level singletons for
constants. Anything behavioral (registry, manager, controller) lives in a
feature package, not here.
"""

from cemaf.core.constants import (
    DEFAULT_MAX_RETRIES,
    DEFAULT_TIMEOUT_SECONDS,
    MAX_CONTEXT_TOKENS,
)
from cemaf.core.domain import DomainContext
from cemaf.core.enums import (
    AgentStatus,
    ContextArtifactType,
    ExclusionReason,
    MemoryScope,
    NodeType,
    Priority,
    RunStatus,
    VerificationStatus,
)
from cemaf.core.execution import (
    CancellationToken,
    CancelledException,
    ExecutionContext,
    TimeoutException,
    with_cancellation,
    with_execution_context,
    with_timeout,
)
from cemaf.core.provenance import ProvenanceChain, ProvenanceLink, SourceReference
from cemaf.core.provider_registry import ProviderRegistry
from cemaf.core.registry import BaseRegistry, RegistryError
from cemaf.core.result import Result
from cemaf.core.storage import InMemoryStorage, StorageEntry
from cemaf.core.types import (
    JSON,
    AgentID,
    Confidence,
    DomainID,
    FinishReason,
    LLMProvider,
    NodeID,
    ProjectID,
    ProvenanceID,
    RunID,
    SkillID,
    TenantID,
    TokenCount,
    ToolID,
)
from cemaf.core.utils import generate_id, json_dumps, safe_json, truncate, utc_now

__all__ = [
    # Types
    "JSON",
    "AgentID",
    "Confidence",
    "DomainID",
    "NodeID",
    "ProjectID",
    "ProvenanceID",
    "RunID",
    "SkillID",
    "TenantID",
    "TokenCount",
    "ToolID",
    "FinishReason",
    "LLMProvider",
    # Enums
    "AgentStatus",
    "ContextArtifactType",
    "ExclusionReason",
    "MemoryScope",
    "NodeType",
    "Priority",
    "RunStatus",
    "VerificationStatus",
    # Provenance
    "ProvenanceChain",
    "ProvenanceLink",
    "SourceReference",
    # Domain
    "DomainContext",
    # Constants
    "DEFAULT_MAX_RETRIES",
    "DEFAULT_TIMEOUT_SECONDS",
    "MAX_CONTEXT_TOKENS",
    # Registry
    "BaseRegistry",
    "ProviderRegistry",
    "RegistryError",
    # Result
    "Result",
    # Storage
    "InMemoryStorage",
    "StorageEntry",
    # Execution
    "CancellationToken",
    "CancelledException",
    "TimeoutException",
    "ExecutionContext",
    "with_cancellation",
    "with_timeout",
    "with_execution_context",
    # Utils
    "utc_now",
    "generate_id",
    "safe_json",
    "json_dumps",
    "truncate",
]

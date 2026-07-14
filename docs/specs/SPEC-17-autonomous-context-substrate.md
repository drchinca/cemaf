---
title: Production-Grade Autonomous Context Substrate
spec_id: SPEC-17
status: Draft
last_reviewed: 2026-07-13
owner: drchinca
depends_on:
  - SPEC-00
  - SPEC-04
  - SPEC-05
  - SPEC-06
  - SPEC-11
  - SPEC-14
  - SPEC-15
  - SPEC-16
---

# SPEC-17: Production-Grade Autonomous Context Substrate

> Defines the normative, vendor-neutral contract CEMAF must satisfy for huge-
> context, long-running, autonomous, data-intensive work. It owns durable
> execution coordination, context/artifact manifests, runnable-work claims,
> adapter/profile capability declarations, evidence bundles, and claim scope.
> It does not require any named database, queue, object store, search engine,
> vector store, or warehouse.

## Contents

- [1. Context](#1-context)
- [2. Interface Contract (MDE)](#2-interface-contract-mde)
- [3. Invariants (DbC)](#3-invariants-dbc)
- [4. Acceptance Criteria (BDD)](#4-acceptance-criteria-bdd)
- [5. Out of Scope](#5-out-of-scope)
- [6. Dependencies And Reconciliation](#6-dependencies-and-reconciliation)
- [7. Correctness Properties](#7-correctness-properties)
- [8. Eval Criteria](#8-eval-criteria)
- [9. Observability Contract](#9-observability-contract)
- [10. Test And Evidence Coverage](#10-test-and-evidence-coverage)
- [11. Graduation And Implementation Order](#11-graduation-and-implementation-order)

## 1. Context

CEMAF already has useful primitives for DAG execution, immutable context
patches, provenance, memory, recovery, replay, moderation, evaluation, budgets,
citations, eventing, and local checkpointing. Those primitives do not yet form
one production contract for work that outlives a process, references data far
larger than a model window, or runs autonomously for days.

The current local disposable-worker proof demonstrates worker replacement,
fencing, atomic file replacement, replay, and a local idempotent effect. It does
not yet demonstrate automatic abandoned-work discovery, lease renewal, one
atomic checkpoint/journal/outbox transaction, bounded bulk-data references,
distributed fairness, a production authority, or current multi-day evidence.

This spec turns eight product pillars into one verifiable substrate contract:

1. durable execution;
2. huge-context management;
3. big-data separation;
4. distributed scheduling;
5. deterministic auditability;
6. safe autonomy;
7. backend portability;
8. reproducible evidence.

The architecture has three planes:

```text
                          disposable workers
                                 │
                       DurableRunCoordinator
                                 │
                                 ▼
                    ┌────────────────────────┐
                    │ RuntimeAuthority       │
                    │ task / lease / fence   │
                    │ checkpoint / journal   │
                    │ transactional outbox   │
                    └───────────┬────────────┘
                                │ committed records
                    ┌───────────┴────────────┐
                    ▼                        ▼
             Artifact plane          CompanionRuntime
          context/data references   wake-ups/outbox/projections
                    │                        │
                    └──── optional conformant adapters ────
```

`DAGExecutor` continues to own DAG semantics. `DurableRunCoordinator` owns the
attempt lifecycle. `RuntimeAuthority` owns authoritative commit semantics.
`CompanionRuntime` owns deterministic background movement of committed work and
records. None is a supervisor agent.

## 2. Interface Contract (MDE)

All models are frozen and serializable through canonical sorted-key JSON.
All protocols are `@runtime_checkable`. Concrete modules are listed with each
contract; implementation may be split further without changing the public
surface.

Snippets assume postponed annotation evaluation and elide imports. Names such
as `TaskTransition`, `JournalEvent`, `OutboxEffect`, `ResumeState`, and
`ExecutionResult` are existing or subordinate models whose complete schemas
must be frozen in the owning module before implementation; they are not loose
`dict[str, Any]` extension points.

### 2.1 Identities and enums

Primitive IDs used by three or more packages are additions to
`cemaf.core.types`. Feature enums live in their owning modules
(`tools.effects`, `config.production_profile`, and `evidence.models`); they are
collected here only to make the shared vocabulary reviewable.

```python
ProfileID = NewType("ProfileID", str)
EvidenceID = NewType("EvidenceID", str)
ManifestID = NewType("ManifestID", str)
ArtifactID = NewType("ArtifactID", str)
AttemptID = NewType("AttemptID", str)
InvariantID = NewType("InvariantID", str)

class Pillar(StrEnum):
    DURABLE_EXECUTION = "durable_execution"
    HUGE_CONTEXT = "huge_context"
    BIG_DATA = "big_data"
    DISTRIBUTED_SCHEDULING = "distributed_scheduling"
    AUDITABILITY = "auditability"
    SAFE_AUTONOMY = "safe_autonomy"
    BACKEND_PORTABILITY = "backend_portability"
    EVIDENCE = "evidence"

class AdapterRole(StrEnum):
    RUNTIME_AUTHORITY = "runtime_authority"
    ARTIFACT_PLANE = "artifact_plane"
    RETRIEVAL_PROJECTION = "retrieval_projection"
    ANALYTICS_PROJECTION = "analytics_projection"
    WAKEUP_TRANSPORT = "wakeup_transport"
    EFFECT_DESTINATION = "effect_destination"

class AdapterMaturity(StrEnum):
    EXPERIMENTAL = "experimental"
    CONFORMANT = "conformant"
    PRODUCTION_VALIDATED = "production_validated"

class ClaimScope(StrEnum):
    CORE_CONTRACT = "core_contract"
    ADAPTER = "adapter"
    PRODUCTION_PROFILE = "production_profile"
    INDUSTRY_STANDARD = "industry_standard"

class PillarStatus(StrEnum):
    SPECIFIED = "specified"
    IMPLEMENTED = "implemented"
    LOCALLY_PROVEN = "locally_proven"
    PROFILE_VALIDATED = "profile_validated"
    PORTABLE = "portable"

class EffectMode(StrEnum):
    PURE = "pure"
    IDEMPOTENT = "idempotent"
    OUTBOXED = "outboxed"
    UNSAFE = "unsafe"

class EvidenceVerdict(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    INCOMPLETE = "incomplete"
    STALE = "stale"
```

`TaskID`, `NodeID`, `CorrelationID`, `TokenBudget`, and `SecurityLevel` remain
owned by SPEC-00/SPEC-11. SPEC-17 references them and does not redefine them.

### 2.2 Context and artifact manifests

New modules: `cemaf.context.manifest` and `cemaf.persistence.artifacts`.

```python
@dataclass(frozen=True, slots=True)
class ContentDigest:
    algorithm: str                 # initially "sha256"
    digest: str

@dataclass(frozen=True, slots=True)
class ArtifactRef:
    tenant_id: str
    artifact_id: ArtifactID
    version: str
    locator: str                   # no embedded credential
    digest: ContentDigest | None
    immutable_snapshot_id: str | None
    logical_bytes: int
    media_type: str
    schema_ref: str | None
    security_level: SecurityLevel
    created_at: datetime
    metadata: tuple[tuple[str, str], ...] = ()

@dataclass(frozen=True, slots=True)
class ContextManifest:
    tenant_id: str
    task_id: TaskID
    manifest_id: ManifestID
    version: int
    parent_manifest_id: ManifestID | None
    artifact_refs: tuple[ArtifactRef, ...]
    patch_ids: tuple[str, ...]
    logical_bytes: int
    compiler_compatibility: str
    created_at: datetime
    content_hash: ContentDigest

@dataclass(frozen=True, slots=True)
class ExcludedContextRef:
    ref_id: str
    reason: str                    # security | budget | relevance | missing | policy

@dataclass(frozen=True, slots=True)
class WorkingContextReceipt:
    tenant_id: str
    task_id: TaskID
    node_id: NodeID
    manifest_id: ManifestID
    manifest_hash: ContentDigest
    compiler_id: str
    compiler_version: str
    policy_version: str
    selected_ref_ids: tuple[str, ...]
    excluded: tuple[ExcludedContextRef, ...]
    token_budget: int
    actual_tokens: int
    rendered_content_hash: ContentDigest
    created_at: datetime

@runtime_checkable
class ArtifactRegistry(Protocol):
    async def register(self, ref: ArtifactRef) -> None: ...
    async def head(self, artifact_id: ArtifactID, version: str) -> ArtifactRef: ...
    async def authorize(
        self,
        *,
        ref: ArtifactRef,
        tenant_id: str,
        principal_id: str,
        clearance: SecurityLevel,
    ) -> bool: ...
```

`ArtifactRegistry` owns identity, integrity, authorization, and lifecycle
metadata. Bulk-byte transfer remains an adapter/application data-plane concern.
An `ArtifactRef` is immutable only when it has a digest or an immutable backend
snapshot ID. Live-task reachability bindings are authority records committed
with the checkpoint; they are not a second write to `ArtifactRegistry`.

The existing `persistence.ArtifactStore` and `ContextArtifact` remain the
small, inline, project-domain artifact API. They are not reused for bulk data
because `ContextArtifact.content` is inline. `ArtifactRegistry` is the narrow
reference/integrity seam for external large-object planes, housed in the same
`persistence` concern rather than a competing top-level package.

### 2.3 Durable execution

New modules: `cemaf.persistence.runtime` for authoritative models/protocols,
`cemaf.orchestration.durable` for the executor-facing coordinator, and
`cemaf.orchestration.companion` for application-lifetime background
composition. This keeps storage semantics in `persistence` and DAG lifecycle in
`orchestration` without adding a generic top-level package.

```python
@dataclass(frozen=True, slots=True)
class ExecutionScope:
    tenant_id: str
    principal_id: str
    clearance: SecurityLevel
    correlation_id: CorrelationID

@dataclass(frozen=True, slots=True)
class AttemptLease:
    tenant_id: str
    task_id: TaskID
    attempt_id: AttemptID
    holder_id: str
    fencing_token: int
    acquired_at: datetime
    expires_at: datetime

@dataclass(frozen=True, slots=True)
class CheckpointEnvelope:
    schema_version: str
    tenant_id: str
    task_id: TaskID
    attempt_id: AttemptID
    manifest_id: ManifestID
    control_state: JSON
    completed_node_ids: tuple[NodeID, ...]
    pending_node_ids: tuple[NodeID, ...]
    fencing_token: int
    byte_size: int
    content_hash: ContentDigest
    created_at: datetime

@dataclass(frozen=True, slots=True)
class NodeCommit:
    checkpoint: CheckpointEnvelope
    task_transition: TaskTransition
    context_manifest: ContextManifest
    journal_events: tuple[JournalEvent, ...]
    outbox_effects: tuple[OutboxEffect, ...]
    artifact_bindings: tuple[ArtifactRef, ...]
    working_context_receipt: WorkingContextReceipt | None

@dataclass(frozen=True, slots=True)
class ClaimRequest:
    worker_id: str
    tenant_ids: tuple[str, ...]
    worker_capabilities: frozenset[str]
    locality_hints: tuple[str, ...]
    max_items: int = 1

@runtime_checkable
class DurabilityUnitOfWork(Protocol):
    async def assert_fence(self) -> None: ...
    async def transition_task(self, transition: TaskTransition) -> None: ...
    async def save_manifest(self, manifest: ContextManifest) -> None: ...
    async def save_checkpoint(self, checkpoint: CheckpointEnvelope) -> None: ...
    async def append_journal(self, events: tuple[JournalEvent, ...]) -> None: ...
    async def enqueue_effects(self, effects: tuple[OutboxEffect, ...]) -> None: ...
    async def bind_artifacts(self, refs: tuple[ArtifactRef, ...]) -> None: ...
    async def save_context_receipt(self, receipt: WorkingContextReceipt) -> None: ...

@runtime_checkable
class RuntimeAuthority(Protocol):
    capabilities: frozenset[BackendCapability]
    outbox: OutboxStore
    journal: JournalReader

    async def create_task(self, request: CreateTaskRequest) -> TaskRecord: ...
    async def claim_task(self, request: ClaimTaskRequest) -> AttemptLease | None: ...
    async def claim_runnable(self, request: ClaimRequest) -> tuple[AttemptLease, ...]: ...
    async def renew(self, lease: AttemptLease, *, ttl: timedelta) -> AttemptLease: ...
    async def load_resume_state(self, lease: AttemptLease) -> ResumeState: ...
    def transaction(
        self,
        lease: AttemptLease,
    ) -> AsyncContextManager[DurabilityUnitOfWork]: ...
    async def release(self, lease: AttemptLease) -> None: ...
    async def health(self) -> DurabilityHealth: ...
    async def close(self) -> None: ...

@runtime_checkable
class DurableAttempt(Protocol):
    lease: AttemptLease
    resume_state: ResumeState

    async def commit_node(self, commit: NodeCommit) -> None: ...
    async def complete(self, result: ExecutionResult) -> None: ...
    async def fail(self, failure: ExecutionFailure) -> None: ...
    async def close(self) -> None: ...

@runtime_checkable
class DurableRunCoordinator(Protocol):
    def open_attempt(
        self,
        *,
        scope: ExecutionScope,
        task_id: TaskID | None,
        dag: DAG,
        initial_context: Context,
    ) -> AsyncContextManager[DurableAttempt]: ...

    async def claim_next(
        self,
        *,
        scope: ExecutionScope,
        request: ClaimRequest,
    ) -> DurableAttempt | None: ...

@runtime_checkable
class OutboxStore(Protocol):
    async def claim_effects(
        self,
        *,
        dispatcher_id: str,
        limit: int,
        lease_ttl: timedelta,
    ) -> tuple[ClaimedEffect, ...]: ...
    async def mark_delivered(
        self,
        claim: ClaimedEffect,
        receipt: DeliveryReceipt,
    ) -> None: ...
    async def mark_failed(
        self,
        claim: ClaimedEffect,
        failure: DeliveryFailure,
    ) -> None: ...

@runtime_checkable
class OperationalProjection(Protocol):
    async def apply(self, events: tuple[JournalEvent, ...]) -> ProjectionCursor: ...
    async def cursor(self, *, tenant_id: str) -> ProjectionCursor: ...
    async def rebuild(self, source: JournalReader) -> ProjectionCursor: ...

@runtime_checkable
class CompanionRuntime(Protocol):
    async def start(self) -> None: ...
    async def readiness(self) -> CompanionReadiness: ...
    async def stop(self, *, drain_timeout: timedelta) -> None: ...
```

`RuntimeServices` gains exactly one executor-facing field:

```python
durable_execution: DurableRunCoordinator | None = None
```

`RuntimeAuthority.outbox` exposes the outbox written by that authority's
`DurabilityUnitOfWork`; it is not a separately configured store. Likewise,
`journal` exposes only committed authority events for replay and projection.

Database clients, outbox loops, projectors, and wake-up consumers are not
`RuntimeServices` fields. They belong to application-lifetime adapter and
`CompanionRuntime` composition. `CompanionRuntime.stop()` stops new claims,
drains bounded in-flight delivery/projection work, persists cursors/claims, and
then closes its clients; forced timeout leaves durable claims recoverable.

### 2.4 Effect capability

New module: `cemaf.tools.effects`.

```python
@dataclass(frozen=True, slots=True)
class EffectDeclaration:
    tool_id: str
    mode: EffectMode
    destination: str | None = None
    idempotency_contract: str | None = None

@dataclass(frozen=True, slots=True)
class OutboxEffect:
    tenant_id: str
    effect_id: str
    destination: str
    idempotency_key: str
    payload: JSON
    payload_hash: ContentDigest
    created_at: datetime

@dataclass(frozen=True, slots=True)
class ClaimedEffect:
    effect: OutboxEffect
    dispatcher_id: str
    claim_token: str
    attempt: int
    expires_at: datetime

@runtime_checkable
class EffectDestination(Protocol):
    capability: DestinationCapability

    async def deliver(self, effect: ClaimedEffect) -> DeliveryReceipt: ...
```

Strict production profiles reject `UNSAFE` effect declarations. An
`IDEMPOTENT` destination must enforce the CEMAF-provided stable effect key. An
`OUTBOXED` tool records intent in `NodeCommit`; it does not perform the external
effect inside `execute_node()`. `(tenant_id, destination, idempotency_key)` is
unique, and reusing it with a different `payload_hash` is a hard conflict.

### 2.5 Scheduling and backpressure

New module: `cemaf.scheduler.work_source`.

```python
@dataclass(frozen=True, slots=True)
class SchedulingLimits:
    max_global_in_flight: int
    max_tenant_in_flight: int
    max_queue_depth: int
    max_claim_batch: int
    starvation_bound_seconds: int
    retry_backoff_ceiling_seconds: int

class BackpressureAction(StrEnum):
    ACCEPT = "accept"
    DEFER = "defer"
    SHED = "shed"

@dataclass(frozen=True, slots=True)
class BackpressureDecision:
    action: BackpressureAction
    retry_after_seconds: int | None
    reason: str

@runtime_checkable
class BackpressurePolicy(Protocol):
    def evaluate(
        self,
        *,
        tenant_id: str,
        queued: int,
        tenant_in_flight: int,
        global_in_flight: int,
        limits: SchedulingLimits,
    ) -> BackpressureDecision: ...
```

The authority work claim is the ownership decision. Queues and wake-up
transports may notify workers but never authorize a commit. Locality is a
ranking hint after eligibility, tenant quota, and starvation constraints.

### 2.6 Adapter capability manifests and production profiles

New module: `cemaf.config.production_profile` for models/loaders and
`cemaf.validation.profile` for readiness validation.

```python
class BackendCapability(StrEnum):
    TRANSACTIONS = "transactions"
    LEASES = "leases"
    RENEWAL = "renewal"
    FENCING = "fencing"
    CHECKPOINTS = "checkpoints"
    JOURNAL = "journal"
    TRANSACTIONAL_OUTBOX = "transactional_outbox"
    MULTI_PROCESS = "multi_process"
    MULTI_HOST = "multi_host"
    TENANT_ISOLATION = "tenant_isolation"
    PROJECTION_REBUILD = "projection_rebuild"
    ARTIFACT_INTEGRITY = "artifact_integrity"
    ARTIFACT_AUTHORIZATION = "artifact_authorization"

@dataclass(frozen=True, slots=True)
class AdapterCapabilityManifest:
    adapter_id: str
    adapter_version: str
    role: AdapterRole
    maturity: AdapterMaturity
    capabilities: frozenset[BackendCapability]
    supported_topologies: tuple[str, ...]
    limits: tuple[ProfileLimit, ...]
    degradation_modes: tuple[DegradationMode, ...]
    evidence_ids: tuple[EvidenceID, ...]

@dataclass(frozen=True, slots=True)
class ProductionProfile:
    schema_version: Literal["cemaf.profile.v1"]
    profile_id: ProfileID
    profile_version: str
    cemaf_version: str
    cemaf_commit: str
    schema_generation: str
    topology: ProfileTopology
    adapters: tuple[AdapterCapabilityManifest, ...]
    required_capabilities: frozenset[BackendCapability]
    scheduling_limits: SchedulingLimits
    checkpoint_byte_limit: int
    manifest_byte_limit: int
    max_artifact_refs_per_manifest: int
    max_patch_refs_per_manifest: int
    context_token_limit: int
    retention_policy: RetentionPolicy
    security_policy_version: str
    evidence_ids: tuple[EvidenceID, ...]

@dataclass(frozen=True, slots=True)
class ProfileReadiness:
    ready: bool
    missing_capabilities: tuple[BackendCapability, ...]
    stale_evidence_ids: tuple[EvidenceID, ...]
    unsafe_effect_tools: tuple[str, ...]
    degradations: tuple[DegradationMode, ...]
    reasons: tuple[str, ...]

@runtime_checkable
class ProductionProfileValidator(Protocol):
    async def validate(
        self,
        *,
        profile: ProductionProfile,
        effect_declarations: tuple[EffectDeclaration, ...],
        now: datetime,
    ) -> ProfileReadiness: ...

def load_production_profile(payload: Mapping[str, JSON]) -> ProductionProfile:
    """Strict load: unknown fields and foreign schema versions raise.""" ...
```

SPEC-16 `EngineManifest` declares an engine's agents/tools/services and lowers
to `create_executor()`. `ProductionProfile` declares deployment guarantees,
limits, topology, adapters, and evidence. They are separate artifacts; an
engine manifest may reference a profile ID but must not duplicate it.

### 2.7 Evidence and claims

New module: `cemaf.observability.evidence`. Evidence is an operator-facing
record/verifier over runtime results; core execution does not import it.

```python
@dataclass(frozen=True, slots=True)
class VersionedDependency:
    name: str
    version: str
    content_hash: str | None

@dataclass(frozen=True, slots=True)
class EvidenceBundle:
    schema_version: Literal["cemaf.evidence.v1"]
    evidence_id: EvidenceID
    invariant_ids: tuple[InvariantID, ...]
    verdict: EvidenceVerdict
    cemaf_commit: str
    dirty_worktree: bool
    profile_id: ProfileID | None
    profile_version: str | None
    dependencies: tuple[VersionedDependency, ...]
    topology_hash: ContentDigest
    configuration_hash: ContentDigest
    workload_hash: ContentDigest
    dataset_manifest_hash: ContentDigest
    random_seed: int
    fault_schedule_hash: ContentDigest | None
    verifier_id: str
    verifier_version: str
    raw_results: ArtifactRef
    logical_referenced_bytes: int | None
    physical_bytes_read: int | None
    physical_bytes_processed: int | None
    exclusions: tuple[str, ...]
    limitations: tuple[str, ...]
    started_at: datetime
    completed_at: datetime

@dataclass(frozen=True, slots=True)
class VerificationReport:
    evidence_id: EvidenceID
    accepted: bool
    effective_verdict: EvidenceVerdict
    missing_artifacts: tuple[ArtifactID, ...]
    stale_dependencies: tuple[str, ...]
    uncovered_invariants: tuple[InvariantID, ...]
    reasons: tuple[str, ...]

@runtime_checkable
class EvidenceVerifier(Protocol):
    async def verify(
        self,
        bundle: EvidenceBundle,
        *,
        expected_invariants: tuple[InvariantID, ...],
        current_dependencies: tuple[VersionedDependency, ...],
    ) -> VerificationReport: ...

def load_evidence_bundle(payload: Mapping[str, JSON]) -> EvidenceBundle:
    """Strict load: unknown fields and foreign schema versions raise.""" ...

@dataclass(frozen=True, slots=True)
class MaturityClaim:
    scope: ClaimScope
    subject_id: str
    pillar_status: tuple[tuple[Pillar, PillarStatus], ...]
    evidence_ids: tuple[EvidenceID, ...]
    issued_at: datetime
```

## 3. Invariants (DbC)

Invariant IDs are stable public identifiers. Evidence bundles cite these exact
IDs. Renaming or changing the meaning of an invariant is a schema-breaking spec
change.

### Cross-cutting

1. **XS-1 — Tenant isolation.** Tenant identity SHALL participate in every
   authoritative key, artifact reference, lease, lookup, claim, journal query,
   outbox key, projection filter, and authorization decision.
2. **XS-2 — Canonical serialization.** Persisted envelopes SHALL include an
   explicit schema version and canonical content hash. Unknown future schema
   versions SHALL fail closed.
3. **XS-3 — Time.** Persisted timestamps SHALL be timezone-aware UTC. Authority
   lease correctness SHALL use authority time, not a worker clock.
4. **XS-4 — Secret exclusion.** Credentials and secret values SHALL NOT appear
   in locators, profiles, manifests, evidence bundles, errors, logs, snapshots,
   traces, or metric labels.

### Durable execution

5. **DE-1 — Crash boundaries.** WHEN a worker dies before node execution,
   during execution, before commit, during commit, or immediately after commit,
   THE authority SHALL expose either the previous complete commit or the new
   complete commit, never a partial commit.
6. **DE-2 — Automatic takeover.** WHEN a task is queued, explicitly retryable,
   or has an expired lease, THE work source SHALL make it claimable without a
   caller manually selecting that task ID.
7. **DE-3 — Fencing.** WHEN a newer attempt has acquired a task, EVERY mutation
   from an older fencing token SHALL fail before changing task, checkpoint,
   journal, context receipt, or outbox state.
8. **DE-4 — Atomic node commit.** A task transition, immutable context manifest,
   checkpoint, journal batch, working-context receipt, live artifact bindings,
   and outbox intents caused by one node SHALL commit atomically.
9. **DE-5 — Worker independence.** Resume, healing-state reconstruction,
   audit, and state replay SHALL require no object, memory, file, or clock owned
   only by a prior worker.
10. **DE-6 — Lease time.** Lease acquisition, expiry, renewal, and pre-commit
   validity SHALL use authority time; heartbeat is liveness and fencing is
   safety.

### Huge-context management

11. **HC-1 — Context universe.** A task MAY reference context larger than every
   supported model window without serializing the full universe into a prompt
   or checkpoint.
12. **HC-2 — Manifest lineage.** Every working context SHALL identify one exact
   manifest hash plus compiler and policy versions.
13. **HC-3 — Bounded projection.** `actual_tokens` SHALL NOT exceed the declared
   node/model token budget; every omitted reference SHALL have a recorded
   exclusion reason.
14. **HC-4 — Deterministic compaction.** For fixed source objects, manifest,
    compiler, policy, and budget, deterministic compilation SHALL produce the
    same selected references and rendered-content hash.
15. **HC-5 — Quality measurement.** Long-run evidence SHALL report retrieval,
    compaction, provenance, and omission quality instead of treating token fit
    alone as success.

### Big-data separation

16. **BD-1 — Bounded authority records.** A checkpoint or context manifest over
    its profile byte/reference limit SHALL fail before authority commit with the
    measured size/count and applicable limit.
17. **BD-2 — Immutable reference.** Every artifact reference SHALL carry a
    content digest or immutable backend snapshot ID, plus logical size, schema,
    classification, and version.
18. **BD-3 — Reachability.** Artifact lifecycle operations SHALL NOT delete a
    version bound by authority state to a live or retained task/checkpoint.
19. **BD-4 — Honest scale.** Terabyte-scale claims SHALL distinguish logical
    referenced bytes from physically read and processed bytes.
20. **BD-5 — Fail closed.** A missing, integrity-failed, or unauthorized
    artifact SHALL produce a durable explicit failure; it SHALL NOT be silently
    omitted or substituted.

### Distributed scheduling

21. **DS-1 — Exclusive commit.** Concurrent claims MAY race, but only the
    current fenced lease SHALL commit.
22. **DS-2 — Tenant fairness.** Under workload assumptions declared by the
    profile, an eligible tenant continuously below quota SHALL receive a claim
    within `starvation_bound_seconds`.
23. **DS-3 — Backpressure.** Queue and in-flight limits SHALL yield explicit
    ACCEPT, DEFER, or SHED decisions; overload SHALL NOT create unbounded
    in-memory work.
24. **DS-4 — Locality is advisory.** Locality MAY rank eligible work but SHALL
    NOT bypass authorization, quota, priority floor, starvation bound, or the
    authority lease.
25. **DS-5 — Retry discipline.** Retry eligibility, backoff, priority, retry
    budget, and poison/dead-letter state SHALL be durable and deterministic.

### Deterministic auditability

26. **DA-1 — Causal identities.** Every task transition, node attempt,
    recovery, context receipt, citation, policy decision, and effect SHALL carry
    task/attempt/node-attempt correlation sufficient for direct joins.
27. **DA-2 — Append-only order.** Journal sequence SHALL be append-only and
    monotonic per task; duplicate event IDs SHALL be idempotent.
28. **DA-3 — Replay modes.** State replay and model/tool re-execution SHALL be
    named separately. Only state replay is required to be deterministic.
29. **DA-4 — Audited transformation.** Redaction, retention, compaction, and
    deletion SHALL emit durable records describing what rule acted and what
    reference changed.
30. **DA-5 — Process-independent query.** Required operator/audit queries SHALL
    use durable records, never process-local logs as the sole source.

### Safe autonomy

31. **SA-1 — Authorization first.** Authorization and clearance SHALL be
    checked before retrieval, model dispatch, tool dispatch, and artifact read.
32. **SA-2 — Budget first.** A known-exhausted token, cost, time, or operation
    budget SHALL halt before another chargeable dispatch.
33. **SA-3 — Bounded recovery.** Retry count, recursive recovery depth, recovery
    token/cost budget, and wall time SHALL have durable limits.
34. **SA-4 — Durable HITL.** Human pause, approval/rejection, and resume SHALL
    survive process loss and mutate state only through a valid fence.
35. **SA-5 — Effect safety.** A strict production profile SHALL reject every
    effectful tool without PURE, destination-enforced IDEMPOTENT, or OUTBOXED
    semantics. Outbox delivery is at-least-once; reusing an idempotency key with
    a different payload hash SHALL reject the whole node commit.
36. **SA-6 — Attributable override.** Every policy override SHALL record actor,
    authority, reason, scope, expiry if any, and causal task/attempt identity.

### Backend portability

37. **BP-1 — Role validation.** Composition SHALL reject an adapter assigned to
    a role for which its capability manifest is insufficient.
38. **BP-2 — Semantic parity.** Every conformant authority adapter SHALL pass
    the same black-box authority contract suite in its supported topology.
39. **BP-3 — Portable claim.** CEMAF SHALL NOT claim backend portability until
    two materially different authority implementations pass BP-2.
40. **BP-4 — Rebuildable projection.** A projection SHALL be deletable and
    rebuildable from authority records without loss of authoritative state.
41. **BP-5 — Explicit degradation.** Adapter outage/removal SHALL follow a
    profile-declared degradation mode; no optional adapter may silently weaken
    DE, DA, or SA invariants.

### Evidence and claims

42. **EV-1 — Named coverage.** Every evidence verdict SHALL cite invariant IDs
    and link immutable raw results.
43. **EV-2 — Reproducibility.** Evidence SHALL identify code, dirty-tree state,
    profile, dependencies, topology, configuration, workload, dataset manifest,
    seed, fault schedule, and verifier.
44. **EV-3 — Honest exclusions.** Excluded data, incomplete samples,
    limitations, and untested boundaries SHALL be explicit.
45. **EV-4 — Invalidation.** A relevant protocol, migration, adapter major
    version, fault harness, verifier, or dependency-hash change SHALL make old
    evidence STALE until reverified.
46. **EV-5 — Claim floor.** A claim's status SHALL be no higher than its least-
    proven mandatory pillar. Missing evidence is not a pass; a known invariant
    failure immediately invalidates dependent claims.
47. **EV-6 — Scope.** Core-contract, adapter, production-profile, and industry-
    standard claims SHALL be distinct and SHALL NOT imply one another upward.

## 4. Acceptance Criteria (BDD)

```gherkin
Feature: Durable autonomous context substrate

  Scenario: Cross-tenant authority access fails closed
    Given task T belongs to tenant A
    And a worker is scoped to tenant B
    When it attempts to claim, load, mutate, replay, or project task T
    Then every operation is denied before task data is returned
    And no tenant A identifier or payload appears in tenant B output

  Scenario Outline: Worker death exposes only a complete commit
    Given a durable task with one committed node
    When its worker is killed <boundary>
    And replacement workers poll runnable work
    Then exactly one replacement obtains the current fencing token
    And the task resumes from one complete checkpoint
    And task, manifest, journal, context receipt, artifact bindings, and outbox have no partial commit

    Examples:
      | boundary |
      | before node execution |
      | during node execution |
      | before authority commit |
      | during authority commit |
      | immediately after authority commit |

  Scenario: Stale worker continues after takeover
    Given worker A held fencing token 7
    And its lease expired and worker B acquired fencing token 8
    When worker A attempts every authoritative mutation
    Then every mutation is rejected as stale
    And worker B's state is unchanged

  Scenario: Huge context compiles to a bounded working set
    Given a context manifest whose logical size exceeds the model window
    When a node compiles working context with a 16000 token budget
    Then actual_tokens is at most 16000
    And every selected item resolves to the exact manifest
    And every omitted item has a security, budget, relevance, missing, or policy reason
    And the receipt records compiler and policy versions

  Scenario: Oversized checkpoint is rejected
    Given a production profile with a 1048576 byte checkpoint limit
    When a node attempts to commit a 1048577 byte checkpoint
    Then the whole node commit is rolled back
    And no journal event, artifact binding, or outbox effect from that node is visible
    And the error reports measured_size=1048577 and limit=1048576

  Scenario: Oversized manifest fanout is rejected
    Given a production profile permits 10000 artifact references per manifest
    When a node attempts to commit a manifest with 10001 references
    Then the whole node commit is rolled back
    And the error reports measured_count=10001 and limit=10000
    And the caller must use bounded parent/child manifests or an external index

  Scenario: Artifact authorization fails closed
    Given a manifest references a confidential immutable artifact
    And the execution principal has INTERNAL clearance
    When the node resolves the artifact
    Then no artifact bytes reach context or the model
    And an authorization failure is journaled with the artifact version

  Scenario: Overload applies bounded fair scheduling
    Given two continuously eligible tenants below their declared quotas
    And one noisy tenant above quota
    When queue depth reaches the profile limit
    Then new work receives explicit DEFER or SHED decisions
    And both eligible tenants receive work within the starvation bound
    And locality never bypasses the quota decision

  Scenario: Unsafe effect blocks strict profile readiness
    Given a tool declares EffectMode.UNSAFE
    And a profile requires strict effect safety
    When ProductionProfileValidator validates the profile
    Then readiness is false
    And the tool id appears in unsafe_effect_tools

  Scenario: Outbox retry after ambiguous acknowledgement is effectively once
    Given an outbox effect with a destination-enforced idempotency key
    And the dispatcher delivers it successfully
    When the dispatcher dies before marking the effect delivered
    And another dispatcher retries the expired claim
    Then the destination observes one logical effect
    And the authority eventually records the delivery receipt

  Scenario: Idempotency key payload conflict is rejected
    Given one committed effect key and payload hash
    When another node commit reuses the key with a different payload hash
    Then the whole node commit fails with an idempotency conflict
    And the original effect remains unchanged

  Scenario: Projection outage does not stop authority
    Given an optional retrieval projection is unavailable
    And the profile declares degraded retrieval
    When a worker commits a node not requiring retrieval
    Then the authority commit succeeds
    And readiness reports the declared degradation
    When the projection returns
    Then it rebuilds to authority parity

  Scenario: Candidate engines are not mandatory
    Given a production profile with one conformant authority and one artifact plane
    And no search or analytics projection
    When the profile's required capabilities are satisfied
    Then readiness does not fail because an unselected candidate adapter is absent

  Scenario: State replay is distinguished from re-execution
    Given a completed task with nondeterministic model calls
    When state replay is requested
    Then the committed final state and causal lineage match byte-for-byte
    And no claim is made that a fresh model re-execution returns identical text

  Scenario: Evidence becomes stale after a relevant change
    Given passing evidence for DE-1 through DE-6
    When the authority migration checksum changes
    And no replacement evidence exists
    Then EvidenceVerifier returns STALE
    And the dependent production-profile claim is not ready

  Scenario: Logical scale is not reported as physical processing
    Given a manifest references one terabyte of logical data
    And the benchmark reads ten gigabytes
    When an evidence bundle is produced
    Then it reports logical_referenced_bytes=1TB separately from physical_bytes_read=10GB
    And it cannot label the result as one-terabyte physical processing
```

## 5. Out of Scope

- Requiring or shipping every suggested backend. Named products are adapter
  candidates, not architectural dependencies.
- Implementing a universal object store, warehouse, search engine, vector
  database, or message broker inside CEMAF core.
- Universal exactly-once node execution or arbitrary external effects.
- Deterministic fresh outputs from nondeterministic models or tools.
- One giant prompt/checkpoint/database row as a huge-context strategy.
- A supervisor agent that owns authority or becomes a mandatory hot-path boss.
- Universal framework SLO numbers. Profiles declare workload/topology-specific
  limits and SLOs; CEMAF standardizes measurement and evidence.
- Cross-region consensus or disaster-recovery topology hidden behind a protocol.
  An adapter/profile must declare and prove those guarantees explicitly.
- Bulk artifact byte transfer. CEMAF standardizes immutable references,
  authorization, integrity, and reachability; adapters move bytes.

## 6. Dependencies And Reconciliation

### SPEC-00 — Enterprise Context Brain

- `TaskID`, `NodeID`, `CorrelationID`, `TokenBudget`, `RuntimeServices`, and the
  composition root remain owned by SPEC-00.
- SPEC-17 adds `RuntimeServices.durable_execution`; no database client or
  background loop is added to the executor-facing bundle.
- Working context remains pull-not-push; SPEC-17 makes its manifest and receipt
  durable and bounded.

### SPEC-04 — Long-Horizon Task State Machine

- `TaskRepository` becomes the task-oriented facade over the same
  `RuntimeAuthority` transaction; it must not create a competing lease.
- `AcquireToken` is replaced by or gains `attempt_id`, monotonic
  `fencing_token`, `expires_at`, and renewal semantics.
- `task_id` is the durable workflow identity. Existing `run_id` is a
  compatibility alias during a declared migration window; `attempt_id` names a
  worker attempt.
- Pause/resume, retry ledger, and prior decisions participate in DE-4.

### SPEC-05 / SPEC-06 — Guardian Mesh And Recovery

- Policy, evaluation, retry, and recovery decisions become journal records.
- Recovery budgets and recursion limits participate in SA-3.
- Healing policy executes in a worker; its state/decisions remain durable and
  available to any replacement worker.

### SPEC-11 — Context Security Classification

- `ArtifactRef.security_level` reuses `SecurityLevel`.
- Clearance filtering happens before artifact read and working-context
  compilation; excluded references are recorded in `WorkingContextReceipt`.

### SPEC-14 — Operator Session Snapshot

- `SessionSnapshot` remains a read-only operator projection. It is not a
  resumable `CheckpointEnvelope` and never becomes authority.
- Snapshot adapters should expose task/attempt/profile IDs when available
  without duplicating authority state.

### SPEC-15 — Memory Branches

- Branch identities reachable by a task are context-manifest references.
- Merge decisions and promoted revisions are journaled; branch storage remains
  adapter-owned.

### SPEC-16 — Declarative Engine Manifest

- `EngineManifest` describes executable composition.
- `ProductionProfile` describes deployment guarantees and evidence.
- An engine manifest may reference `profile_id`; neither artifact embeds
  credentials or duplicates the other schema.

## 7. Correctness Properties

### Property 1: Tenant and envelope integrity

For every public substrate operation, changing the trusted tenant scope while
holding all other identifiers constant cannot reveal or mutate the original
tenant's records; every persisted envelope is versioned, canonically hashed,
UTC-timestamped, and secret-free.

**Validates:** XS-1 through XS-4 and the cross-tenant scenario.

### Property 2: Crash-safe monotonic progress

For every task history containing arbitrary worker crashes and lease takeovers,
the visible authoritative history is a prefix of complete node commits ordered
by journal sequence; no stale token can extend that history.

**Validates:** DE-1 through DE-6 and the worker-death/stale-worker scenarios.

### Property 3: Bounded context with complete lineage

For every compiled working context, actual tokens are within budget and every
included or excluded reference is explainable from one immutable manifest,
compiler version, policy version, and receipt.

**Validates:** HC-1 through HC-5 and the huge-context scenario.

### Property 4: Bulk-data non-interference

Increasing an artifact's logical size without changing bounded control metadata
does not proportionally increase checkpoint size or prompt size.

**Validates:** BD-1 through BD-5 and oversized-checkpoint/logical-scale scenarios.

### Property 5: Safe fair claiming

Under the production profile's declared workload assumptions, every eligible
below-quota tenant is scheduled within the starvation bound, while every
authoritative commit remains protected by one current fence.

**Validates:** DS-1 through DS-5 and the overload scenario.

### Property 6: Causal state replay

For any completed task whose retained records pass integrity checks, state
replay reconstructs the same committed state and causal identity graph without
requiring fresh model/tool execution.

**Validates:** DA-1 through DA-5 and the replay scenario.

### Property 7: Bounded, authorized autonomy

No dispatch occurs after a known authorization/budget denial, no recovery
exceeds durable limits, and no unsafe effect enters a strict production profile.

**Validates:** SA-1 through SA-6 and effect/artifact scenarios.

### Property 8: Adapter substitutability

Replacing one conformant adapter with another for the same role preserves every
core observable invariant supported by both capability manifests.

**Validates:** BP-1 through BP-5 and candidate-engine/projection scenarios.

### Property 9: Claim soundness

For every maturity claim, each claimed pillar/status has current passing
evidence covering all mandatory invariant IDs at that scope; removing or
invalidating any required bundle lowers or invalidates the claim.

**Validates:** EV-1 through EV-6 and the stale-evidence scenario.

## 8. Eval Criteria

Most SPEC-17 invariants are deterministic systems properties and must not be
delegated to an LLM judge. LLM-based evaluation is permitted only for semantic
quality that deterministic checks cannot measure.

### Deterministic gates

- token/checkpoint/artifact sizes and hashes;
- lease/fence/transaction behavior;
- identity joins, journal order, and replay parity;
- capability/profile validation;
- quotas, backpressure, retry counts, and starvation measurements;
- authorization decisions and effect declarations;
- evidence completeness, dependency hashes, and verdict invalidation.

### Semantic evals

Profiles exercising huge-context behavior declare datasets and thresholds for:

- retrieval recall/precision over required evidence;
- compaction factual retention and contradiction introduction;
- provenance/citation membership;
- task-goal completion across long horizons;
- recovery usefulness without policy/budget violation;
- quality degradation as context-universe size and task duration increase.

LLM judges SHALL use revision-pinned model IDs, sanitized inputs, versioned
rubrics, per-attempt eval budgets, and recorded cassettes as required by
SPEC-00/SPEC-05. An LLM-judge score alone cannot prove any DE, BD, DS, BP, or EV
invariant and cannot support a production-profile or industry-standard claim.

Eval evidence reports distributions and confidence intervals where applicable,
not only averages. Thresholds belong to a versioned profile/dataset; the core
spec does not invent one universal quality number.

## 9. Observability Contract

### Durable events

The following event families are journaled with task, attempt, tenant, and
correlation identity where applicable:

- `task.claimed`, `task.lease_renewed`, `task.lease_lost`,
  `task.stale_write_rejected`, `task.takeover_completed`;
- `checkpoint.committed`, `checkpoint.rejected_oversize`;
- `context.manifest_created`, `context.compiled`, `context.compacted`,
  `context.reference_excluded`;
- `artifact.registered`, `artifact.authorization_denied`,
  `artifact.integrity_failed`, `artifact.pin_changed`;
- `scheduler.backpressure`, `scheduler.work_claimed`, `scheduler.dead_lettered`;
- `policy.denied`, `policy.override_applied`, `recovery.started`,
  `recovery.exhausted`, `hitl.paused`, `hitl.resumed`;
- `outbox.claimed`, `outbox.delivered`, `outbox.retrying`, `outbox.dead_lettered`;
- `profile.validated`, `profile.readiness_failed`, `evidence.verified`,
  `evidence.stale`, `claim.downgraded`.

### Metrics

- `cemaf_task_takeovers_total{profile,reason}`;
- `cemaf_stale_writes_total{profile,mutation}`;
- `cemaf_checkpoint_bytes{profile}` histogram;
- `cemaf_context_logical_bytes{profile}` histogram;
- `cemaf_working_context_tokens{profile}` histogram;
- `cemaf_context_exclusions_total{profile,reason}`;
- `cemaf_scheduler_claim_latency_seconds{profile}` histogram;
- `cemaf_scheduler_backpressure_total{profile,action,reason}`;
- `cemaf_scheduler_starvation_bound_violations_total{profile}`;
- `cemaf_outbox_pending{profile,destination}` gauge;
- `cemaf_projection_lag_events{profile,projection}` gauge;
- `cemaf_evidence_verdict_total{scope,verdict}`.

Tenant, task, attempt, artifact, evidence, and raw error strings are forbidden
as metric labels. They belong in traces/logs.

### Traces

One task trace links attempt spans; each node-attempt span links working-context,
policy/eval, model/tool, authority-commit, and outbox-intent spans. Takeover uses
span links to the prior attempt because it is causal continuation, not a child
call on the same process stack.

### Readiness

Strict production readiness fails on:

- unavailable or schema-drifted authority;
- missing lease/renewal/fencing/transaction/outbox capability;
- stale mandatory evidence;
- checkpoint/profile limit mismatch;
- missing required artifact authorization/integrity capability;
- unsafe effect declaration;
- insecure network configuration where the profile requires TLS;
- unsupported adapter/server/client version;
- an undeclared degradation.

## 10. Test And Evidence Coverage

### L0 — Model and protocol surface

- frozen model construction and canonical JSON round trips;
- invalid enum/schema/version/negative-size/timezone cases;
- runtime structural checks for every protocol;
- production-profile strict unknown-field rejection;
- secret/credential rejection in locators and serialized profiles.

### L1 — Deterministic component contracts

- manifest hashing, parent/version lineage, receipt determinism;
- checkpoint size, content hash, and immutable-version behavior;
- profile capability validation and degradation decisions;
- backpressure boundary tables and retry/backoff determinism;
- evidence dependency invalidation and claim-floor calculation.

### L2 — Shared adapter conformance

- every advertised authority runs one black-box DE/DA/outbox suite;
- every artifact registry runs identity/integrity/auth/pin lifecycle tests;
- every projection runs duplicate, restart, lag, outage, and rebuild tests;
- every effect destination proves and declares idempotency behavior;
- adapters run only the role suites they claim; unsupported roles fail
  composition rather than skip tests silently.

### L3 — Destructive integration

- process kills at all DE-1 boundaries;
- stale writer continues after takeover;
- database/client disconnect during commit and renewal;
- disk-full/read-only/local corruption where applicable;
- authority failover in the advertised topology;
- outbox crash before/after destination acknowledgement;
- projection loss/rebuild and artifact missing/auth/integrity failures;
- migration interruption, rollback, backup, and restore/replay.

### L4 — Scale, security, and endurance

- multi-tenant fairness, quotas, overload, and load shedding;
- high manifest/artifact cardinality with bounded authority/checkpoint growth;
- logical referenced size and physical scan bytes reported separately;
- multi-day worker churn, lease renewal, recovery, compaction, and projection lag;
- prompt/context poisoning, cross-tenant access, policy override, and unsafe
  effect attempts;
- memory/resource growth and retention/garbage-collection reachability.

### Evidence bundle requirements

Every non-unit verdict emitted by L2–L4 includes:

1. invariant IDs;
2. CEMAF commit and dirty-tree state;
3. profile, adapter, server/client, and migration versions;
4. topology/configuration/workload/dataset hashes and seed;
5. exact fault schedule;
6. immutable raw-result reference;
7. verifier identity/version;
8. exclusions, limitations, incomplete samples, and duration;
9. reproduction command.

The verifier, not the benchmark process, calculates the final verdict from raw
results. Correctness failure makes the lane red regardless of throughput,
availability aggregate, or cost.

## 11. Graduation And Implementation Order

### Maturity transitions

| Transition | Gate |
|---|---|
| Specified → Implemented | Public models/protocols exist; L0/L1 pass; docs/imports/type checks pass |
| Implemented → Locally proven | Reference profile passes L2/L3 with current evidence |
| Adapter experimental → conformant | Shared role suite passes in documented topology |
| Adapter conformant → production-validated | L3/L4, security, upgrade, backup/restore, operations evidence passes |
| Profile → validated | Every required capability and pillar maps to current passing evidence |
| Pillar → portable | Two materially different implementations preserve its shared semantics |
| Industry-standard claim → supportable | All pillars validated plus multiple independent production adopters/profiles and public current evidence |

### Implementation order

1. Reconcile SPEC-04 identities/lease semantics and freeze SPEC-17 models.
2. Implement evidence models/verifier and shared conformance harness first, so
   later green results have a trustworthy meaning.
3. Implement the coordinator/authority/UoW contracts and one embedded reference
   adapter selected by ADR.
4. Wire `RuntimeServices.durable_execution` and replace the manual-replacement
   example with runnable-work discovery.
5. Implement context/artifact manifests, bounded receipts, size enforcement,
   and one artifact adapter selected by ADR.
6. Implement scheduling limits/backpressure/fairness and effect capability
   validation.
7. Select one complete production profile from adopter requirements; graduate
   it through L2–L4 and operations gates.
8. Add further authority/projection/artifact/transport adapters only through
   independent ADRs and role-specific conformance.

## Non-Obligation To Implement Every Adapter

SPEC-17 is mandatory as a semantic and evidence contract for production claims.
It is not an obligation to implement every adapter candidate. CEMAF needs one
exhaustive local reference and at least one complete production-validated
profile. Additional products are optional, demand-driven, and independently
graduated. No absent, unselected adapter lowers readiness.

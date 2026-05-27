---
title: TaskRepository Contract — Persistence Primitives
spec_id: SPEC-04b
status: Reviewed
last_reviewed: 2026-05-27
owner: drchinca
parent: SPEC-04 — Long-Horizon Task State Machine
depends_on: SPEC-04, SPEC-00
---

# SPEC-04b: TaskRepository Contract

> Persistence-layer contract for the `Task` aggregate defined by SPEC-04.
> Covers the `TaskRepository` Protocol surface, lease primitives (TTL,
> renewal, stale-lease detection), atomic metadata increment, child-task
> spawn, and the `canonical_projection` definition + migration cutover for
> the new tail fields (`chain_profile_id`, `chain_profile_version`,
> `eval_cost_state`).
>
> SPEC-04 covers the **state-machine and lifecycle rules** (transitions,
> step awareness, retry ledger semantics, prior_decisions windowing).
> This spec covers the **storage primitives** under those rules.

## 1. Context

SPEC-04 defines the Task aggregate and its state machine. Production runs
multi-pod (multiple executor instances behind a single TaskRepository),
where two hazards emerge that are out of scope for SPEC-04 itself:

1. **Multi-pod safety** — two executors must not both believe they own a
   resumed task. A lease primitive with TTL and stale-write detection is
   required.
2. **Cross-chain accounting** — autonomous chains spawn child tasks and
   accumulate eval-cost counters under contention. Read-modify-CAS is too
   slow under 8+ concurrent contenders; a native atomic
   fetch-and-add primitive is required.
3. **Schema evolution** — adding new tail fields (`chain_profile_id`,
   `chain_profile_version`, `eval_cost_state`) to the canonical
   serialization must be backwards-safe for tasks created before the
   cutover.

This spec is the contract that the persistence layer (PostgreSQL, Redis,
SQLite — pick one per deployment) implements; the executor (SPEC-04) and
downstream specs (SPEC-EVAL, SPEC-AGENT-analyst, SPEC-RUNTIME in
brightagent-v2) consume it.

## 2. Interface Contract (MDE)

```python
from typing import Protocol, runtime_checkable
from dataclasses import dataclass
from datetime import datetime

@dataclass(frozen=True, slots=True)
class AcquireToken:
    """Immutable lease handle returned by TaskRepository.acquire."""
    task_id: TaskID
    holder_id: str                                 # executor instance id
    acquired_at: datetime
    lease_ttl_ms: int = 60_000                     # auto-released after TTL on holder crash

@dataclass(frozen=True, slots=True)
class AcquiredLease:
    """Async context manager wrapper around an active lease.

    __aexit__ calls repository.release(self._token); re-raises any pending
    exception after release.
    """
    _repository: "TaskRepository"
    _token: AcquireToken

    async def __aenter__(self) -> AcquireToken:
        return self._token

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self._repository.release(self._token)

@dataclass(frozen=True, slots=True)
class TaskSnapshot:
    """Persistable snapshot for pause/resume across processes. Carries every
    field required to reconstruct the Task aggregate via restore(); the
    immutable Goal+DAG binding (dag_id) and creation timestamp must round-trip
    so the resumed Task is structurally equal to the paused Task."""
    task_id: TaskID
    goal: Goal
    dag_id: DAGID
    state: TaskState
    step_index: int
    step_count: int
    prior_decisions: tuple[Decision, ...]
    retry_ledger: tuple[tuple[NodeID, int], ...]
    budget_remaining: TokenBudget
    correlation_id: CorrelationID
    created_at: datetime
    snapshot_at: datetime
    # SPEC-RUNTIME phase-5 cutover tail fields (Inv 7); pre-cutover snapshots
    # SHALL project None for all three.
    chain_profile_id: "ChainProfileId | None" = None
    chain_profile_version: "str | None" = None
    eval_cost_state: "EvalCostState | None" = None

@runtime_checkable
class TaskRepository(Protocol):
    async def create(self, *, goal: Goal, dag_id: DAGID,
                     budget: TokenBudget) -> Task: ...
    async def get(self, task_id: TaskID) -> Task: ...
    async def transition(self, task_id: TaskID, *, to: TaskState,
                         reason: str | None = None,
                         token: AcquireToken | None = None) -> Task:
        """Raises InvalidTransitionError on illegal transitions (SPEC-04 §3 Inv 1).
        When `token` is provided, the repository SHALL validate it against the current lease (Inv 4); when None, only repository-internal callers may invoke."""
    async def append_decision(self, task_id: TaskID, decision: Decision) -> None: ...
    async def snapshot(self, task_id: TaskID) -> TaskSnapshot: ...
    async def restore(self, snapshot: TaskSnapshot) -> Task: ...
    async def acquire(self, task_id: TaskID, *, holder_id: str) -> AcquiredLease:
        """Exclusive resume lock with TTL-bounded lease. Returns an AcquiredLease
        usable as `async with repo.acquire(task_id, holder_id=...) as token:`.
        Raises TaskInUseError when already held by a different holder with a
        non-expired lease."""
    async def release(self, token: AcquireToken) -> None: ...
    async def increment_retry(self, task_id: TaskID, node_id: NodeID) -> int:
        """Called by the executor at re-dispatch time, BEFORE the chain runs
        for the new attempt — so guardians observe the incremented value."""
    async def decrement_retry(self, task_id: TaskID, node_id: NodeID) -> None:
        """SHALL only be callable during shutdown drain — repository asserts
        is_shutting_down flag; otherwise raises InvariantViolationError."""
    async def atomic_fetch_add_metadata(
        self,
        *,
        task_id: TaskID,
        key: str,
        delta: int,
    ) -> int:
        """Atomic fetch-and-add on integer-valued task.metadata[key].
        Returns the new value AFTER the increment.
        Single round-trip; no read-modify-CAS retry loop.
        Raises TaskNotFoundError if task_id absent.
        Raises MetadataTypeError if existing value is non-int."""
    async def spawn_child_task(
        self,
        *,
        parent_task_id: TaskID,
        child_goal: Goal,
        inherit_keys: frozenset[str] = frozenset({
            "chain_correlation_id",
            "chain_profile_id",
            "chain_profile_version",
        }),
    ) -> TaskID:
        """Atomically create a child Task with parent linkage and propagated metadata.

        SHALL: (1) read parent.metadata; (2) create child Task with task.correlation_id
        fresh per SPEC-04 §3 Inv 11; (3) copy keys in inherit_keys from parent.metadata
        to child.metadata; (4) set child.metadata['parent_task_id'] = parent_task_id;
        (5) emit TaskSpawned event with parent_task_id + child_task_id linkage.
        All five operations execute under a single persistence transaction.
        Raises TaskNotFoundError if parent_task_id absent.
        Raises ParentNotActiveError if parent.state ∉ {RUNNING, PAUSED}."""
    async def health(self) -> HealthStatus:
        """Liveness probe consumed by SPEC-00 readiness contract."""
```

### canonical_projection

The canonical, sorted-key projection used for snapshot serialization,
audit comparison, and replay equivalence is exactly:

```
task_id, goal, dag_id, state, step_index, step_count,
prior_decisions, retry_ledger, budget_remaining, correlation_id,
created_at, chain_profile_id, chain_profile_version, eval_cost_state
```

The trailing three fields appear in this exact tail order. `Task.updated_at`
is repository-managed and is NOT part of the canonical_projection.

## 3. Invariants (DbC)

1. `WHEN restoring from a snapshot, THE restored Task SHALL be structurally equal to the snapshot under canonical sorted-key JSON serialization for the canonical_projection field set (§2). Task.updated_at is repository-managed and SHALL be set to utc_now() at restore time (not required to equal the pre-snapshot value).`
2. `TaskRepository.acquire SHALL be exclusive — concurrent resumption attempts on the same task SHALL fail with TaskInUseError.`
3. `WHEN AcquireToken.lease_ttl_ms elapses without explicit release, THE TaskRepository SHALL treat the lease as expired and permit a new acquire — preventing dead executors from holding tasks indefinitely.`
4. `WHEN a holder calls TaskRepository.release(token) OR TaskRepository.transition(token=...) AFTER the lease has expired (Inv 3) and a new holder has acquired, THE Repository SHALL raise StaleLeaseError and SHALL NOT mutate Task state. Detection: every release/transition call carries the original AcquireToken; the repository compares the persisted current_holder_id against token.holder_id and raises if they differ. This closes the multi-pod race where holder A's lease expires, holder B acquires, then A's slow callback writes — A's write is discarded with a logged event "task.stale_lease_write".`
5. `TaskRepository.atomic_fetch_add_metadata SHALL be implemented via the persistence layer's native atomic increment primitive (e.g., Redis INCRBY, PostgreSQL `metadata = metadata || jsonb_build_object($key, COALESCE((metadata->>$key)::int, 0) + $delta)`); read-modify-CAS implementations are forbidden under high-fanout (autonomous chains spawn 8+ concurrent CAS contenders).`
6. `Child Task creation in autonomous / multi-agent chains SHALL go through TaskRepository.spawn_child_task exclusively. Direct TaskRepository.create(...) calls in autonomy/analyst code paths are forbidden by semgrep tools/semgrep/no_direct_child_task_create.yml.`
7. `Pre-cutover Tasks (created before SPEC-RUNTIME phase 5) project NULL for the three new tail fields (chain_profile_id, chain_profile_version, eval_cost_state). Post-cutover Tasks (created after phase 5) project verbatim. Legacy snapshot comparators that ignore trailing nulls remain valid; post-cutover comparators include the new fields verbatim. The cutover is atomic per workspace via TaskRepository migration tag.`

## 4. Acceptance Criteria (BDD)

```gherkin
Feature: TaskRepository persistence primitives

  Scenario: Snapshot fidelity round-trip (Inv 1)
    Given a Task in state RUNNING with prior_decisions, retry_ledger, and budget_remaining set
    When TaskRepository.snapshot(task_id) is taken and restore(snapshot) is called
    Then the restored Task is canonical-equal to the original under the canonical_projection field set
    And restored.updated_at equals utc_now() at restore time

  Scenario: Concurrent resume rejected
    Given a Task being resumed by executor A
    When executor B attempts to acquire() the same task
    Then the second call raises TaskInUseError

  Scenario: Lease TTL expiry permits re-acquire
    Given executor A holds an AcquireToken with lease_ttl_ms=100
    And A crashes without calling release
    When 200ms elapses and executor B calls acquire()
    Then the lease is treated as expired
    And B receives a fresh AcquireToken without TaskInUseError

  Scenario: Stale-lease write is rejected (Inv 4)
    Given executor A's lease has expired and executor B has acquired
    When A's slow callback calls release(token_A) or transition(token=token_A, ...)
    Then the Repository raises StaleLeaseError
    And Task state is unchanged
    And a "task.stale_lease_write" log event is emitted
    And cemaf_task_stale_lease_writes_total is incremented

  Scenario: Atomic increment under concurrent contention (Inv 5)
    Given a Task with metadata["eval_cost_counter"] absent or 0
    When 16 concurrent callers invoke atomic_fetch_add_metadata(key="eval_cost_counter", delta=1)
    Then the final persisted value is exactly 16
    And no caller observes a lost update
    And the returned values across callers are the set {1, 2, ..., 16}

  Scenario: spawn_child_task propagates chain metadata atomically (Inv 6)
    Given a parent Task with metadata containing chain_correlation_id="CC-1", chain_profile_id="prof-7", chain_profile_version="v3"
    And parent.state == RUNNING
    When spawn_child_task(parent_task_id=parent.id, child_goal=G) is called
    Then a child Task is created with metadata.chain_correlation_id == "CC-1"
    And child.metadata.chain_profile_id == "prof-7"
    And child.metadata.chain_profile_version == "v3"
    And child.metadata.parent_task_id == parent.id
    And child.task.correlation_id is freshly minted (≠ parent.task.correlation_id) per SPEC-04 §3 Inv 11
    And a TaskSpawned event is emitted carrying both parent_task_id and child_task_id
    And all five operations executed under a single persistence transaction

  Scenario: spawn_child_task rejects inactive parent (Inv 6)
    Given a parent Task with state == HALTED
    When spawn_child_task(parent_task_id=parent.id, child_goal=G) is called
    Then ParentNotActiveError is raised
    And no child Task is created
    And no TaskSpawned event is emitted

  Scenario: Pre-cutover task projects NULL for new tail fields (Inv 7)
    Given a Task created before the SPEC-RUNTIME phase-5 cutover for its workspace
    When canonical_projection is computed
    Then chain_profile_id projects to None
    And chain_profile_version projects to None
    And eval_cost_state projects to None
    And legacy snapshot comparators that ignore trailing nulls accept the projection

  Scenario: Post-cutover task projects new tail fields verbatim (Inv 7)
    Given a Task created after the SPEC-RUNTIME phase-5 cutover with chain_profile_id="prof-7", chain_profile_version="v3", eval_cost_state set
    When canonical_projection is computed
    Then chain_profile_id projects to "prof-7"
    And chain_profile_version projects to "v3"
    And eval_cost_state projects verbatim
    And the three fields appear as the trailing fields in the canonical sorted-key serialization
```

## 5. Out of Scope

- The Task state machine itself — see SPEC-04.
- Choice of persistence backend (PostgreSQL vs Redis vs SQLite) — deployment concern; this spec is the contract every backend implements.
- Cross-region replication / DR — separate spec.
- Encryption at rest of `metadata` — handled by the persistence layer's native crypto, not this contract.

## 6. Dependencies

- SPEC-04 (Task aggregate, TaskState, Decision, retry_ledger semantics)
- SPEC-00 §2 (TokenBudget, Goal, CorrelationID, HealthStatus)
- `persistence/entities.py`, `persistence/protocols.py`

**Downstream consumers** (this spec's primitives are consumed by):
- brightagent-v2 SPEC-EVAL-eval-budget-counter — consumes `atomic_fetch_add_metadata` as the atomic FETCH_ADD primitive replacing read-modify-CAS.
- brightagent-v2 SPEC-AGENT-analyst, SPEC-EVAL, SPEC-RUNTIME — consume `spawn_child_task` as the sole child-task creation seam in autonomous / multi-agent chains.
- brightagent-v2 SPEC-RUNTIME-chain-profiles + SPEC-EVAL-eval-budget-counter — consume the canonical_projection extension (chain_profile_id, chain_profile_version, eval_cost_state).

## 7. Correctness Properties

### Property 1: Snapshot fidelity
*For any* snapshot S taken at t1 and restored at t2 > t1, the restored Task's
canonical_projection equals that of S.

**Validates: §3 Invariant 1 / §4 "Snapshot fidelity round-trip"**

### Property 2: Lease exclusivity
*For any* task T at any instant t, at most one holder H has a non-expired
lease on T; any concurrent acquire by H' ≠ H raises TaskInUseError.

**Validates: §3 Invariants 2, 3 / §4 "Concurrent resume rejected", "Lease TTL expiry permits re-acquire"**

### Property 3: Stale-write isolation
*For any* token K whose holder lost the lease via TTL expiry, no
release(K) or transition(token=K, ...) call mutates Task state; every such
call raises StaleLeaseError.

**Validates: §3 Invariant 4 / §4 "Stale-lease write is rejected"**

### Property 4: Atomic increment correctness
*For any* N concurrent atomic_fetch_add_metadata(key=k, delta=d) calls on
the same task, the final persisted value equals (initial + N·d) and the
returned values are a permutation of {initial + d, initial + 2d, …, initial + Nd}.

**Validates: §3 Invariant 5 / §4 "Atomic increment under concurrent contention"**

### Property 5: Child-task linkage transactionality
*For any* spawn_child_task call that succeeds, the child Task exists,
inherit_keys are copied, parent_task_id metadata is set, and a TaskSpawned
event is observable — atomically. If any step fails, none of these effects
are persisted or emitted.

**Validates: §3 Invariant 6 / §4 "spawn_child_task propagates chain metadata atomically", "spawn_child_task rejects inactive parent"**

### Property 6: Migration cutover safety
*For any* Task T, canonical_projection(T) is accepted by both legacy and
post-cutover comparators given the cutover rule in §3 Invariant 7.

**Validates: §3 Invariant 7 / §4 "Pre-cutover task projects NULL", "Post-cutover task projects new tail fields verbatim"**

## 8. Eval Criteria

Persistence-contract spec — deterministic evaluators only.

| Evaluator | Node | Mode | Threshold | Method |
|---|---|---|---|---|
| SnapshotFidelityEvaluator | repository round-trip | GATE | mismatches == 0 | deterministic |
| LeaseExclusivityEvaluator | repository acquire | GATE | concurrent_holders == 1 | deterministic |
| StaleLeaseRejectionEvaluator | repository write | GATE | stale_writes_accepted == 0 | deterministic |
| AtomicIncrementEvaluator | metadata write | GATE | lost_updates == 0 | deterministic |
| ChildTaskAtomicityEvaluator | spawn_child_task | GATE | partial_commits == 0 | deterministic |
| CanonicalProjectionEvaluator | snapshot serialization | GATE | field_order_violations == 0 | deterministic |

## 9. Observability Contract

- **Span**: `gen_ai.task.acquire` — `task.id`, `holder.id`, `lease.ttl_ms`
- **Span**: `gen_ai.task.snapshot` — `task.id`, `snapshot.size_bytes`
- **Span**: `gen_ai.task.spawn_child` — `parent.task.id`, `child.task.id`, `inherit.key_count`
- **Log events**: `task.acquire_conflict`, `task.lease_expired{task_id, holder_id, expired_at_iso, ttl_ms}`, `task.stale_lease_write{task_id, holder_id, current_holder_id}`, `task.snapshot_taken`, `task.restored`, `task.child_spawned{parent_task_id, child_task_id}`, `task.atomic_increment{task_id, key, new_value}`
- **Metrics**: `cemaf_task_acquire_conflicts_total`, `cemaf_task_lease_expired_total`, `cemaf_task_stale_lease_writes_total` (no labels — Inv 4 stale-holder writes), `cemaf_task_atomic_fetch_add_total{key}` (counter — bounded label set, only well-known keys), `cemaf_task_child_spawned_total`, `cemaf_task_snapshot_bytes` (histogram)

## Migration cross-ref

The following downstream specs (in `brighthive/brightagent-v2`, on
separate branches) cite invariants that have moved from SPEC-04 into
SPEC-04b. Their next R-pass SHALL rewrite the citations:

| Downstream citation | Becomes |
|---|---|
| `SPEC-EVAL-eval-budget-counter Inv 10` → `SPEC-04 atomic_fetch_add_metadata` | `SPEC-04b §3 Inv 5 (atomic_fetch_add_metadata)` |
| `SPEC-AGENT-analyst Inv 16` → `SPEC-04 spawn_child_task` | `SPEC-04b §3 Inv 6 (spawn_child_task)` |
| `SPEC-RUNTIME Inv 6` → `SPEC-04 canonical_projection` | `SPEC-04b §3 Inv 7 (canonical_projection migration cutover)` |

Cemaf-side citations are updated in this PR; downstream repo updates are
out of scope here and tracked by the consuming spec owners.

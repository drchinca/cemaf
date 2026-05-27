---
title: Long-Horizon Task State Machine
spec_id: SPEC-04
status: Reviewed
last_reviewed: 2026-05-27
owner: drchinca
parent: SPEC-00 — Enterprise Context Brain
depends_on: SPEC-01
---

# SPEC-04: Long-Horizon Task State Machine

> Promotes a multi-step DAG run into a **Task** with a persistent state machine,
> step-aware progress, retry accounting, and resumable execution. Every node
> receives a `TaskContext` that names its position, prior decisions, and the
> retry ledger it inherits.

## Contents

- [1. Context](#1-context)
- [2. Interface Contract (MDE)](#2-interface-contract-mde)
- [3. Invariants (DbC)](#3-invariants-dbc)
- [4. Acceptance Criteria (BDD)](#4-acceptance-criteria-bdd)
- [5. Out of Scope](#5-out-of-scope)
- [6. Dependencies](#6-dependencies)
- [7. Correctness Properties](#7-correctness-properties)
- [8. Eval Criteria](#8-eval-criteria)
- [9. Observability Contract](#9-observability-contract)

## 1. Context

DAGs run today; tasks do not. There is no first-class concept of "this is step 3
of 10 in goal G", no progress, no pause/resume across processes, no inheritance
of prior decisions, and no retry counter that lets SPEC-05 enforce
"recover-once-then-halt" deterministically.

This spec adds a `Task` aggregate with a strict state machine, persists it via
`persistence/`, and adds a `TaskInjectInterceptor` (PRE phase, position 4 —
last in DEFAULT_PRE_ORDER) that populates each node's `TaskContext`.

```mermaid
stateDiagram-v2
    [*] --> QUEUED
    QUEUED --> RUNNING : DAGExecutor.start()
    RUNNING --> PAUSED : pause(reason)
    PAUSED --> RUNNING : resume()
    RUNNING --> COMPLETED : terminal node accepts
    RUNNING --> HALTED : guardian HALT or executor cancel
    PAUSED --> HALTED : timeout / cancel
    HALTED --> [*]
    COMPLETED --> [*]
```

`RUNNING` is the running state — there is no `RESUMED` state; `resume()` is a
transition (PAUSED → RUNNING), not a state. SPEC-00 §2 forwards `TaskState`
here as the single source of truth.

## 2. Interface Contract (MDE)

Common types in SPEC-00 §2 (`TaskID`, `NodeID`, `TokenBudget`, `Citation`).

```python
from __future__ import annotations
from typing import Protocol, runtime_checkable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from types import TracebackType

class TaskState(Enum):
    QUEUED    = "queued"
    RUNNING   = "running"
    PAUSED    = "paused"
    COMPLETED = "completed"
    HALTED    = "halted"

class DecisionKind(Enum):
    """Outcome class of a post-flight decision — used by Inv 16 windowing
    and SPEC-06 Inv 16 projection to retain HALT/REJECT entries preferentially."""
    ACCEPT  = "accept"
    REJECT  = "reject"
    RECOVER = "recover"
    HALT    = "halt"

@dataclass(frozen=True, slots=True)
class Decision:
    """A material choice or output from a prior step worth carrying forward."""
    node_id: NodeID
    kind: DecisionKind                             # mirrors PostflightDecision.kind on the attempt that produced this entry; populated by the executor when appending to Task.prior_decisions
    summary: str                                   # one-liner
    cited_evidence_refs: tuple[Citation, ...]
    at: datetime

@dataclass(frozen=True, slots=True)
class TaskContext:
    task_id: TaskID
    goal: Goal
    step_index: int                                # 0-based, into the executed step sequence
    step_count: int
    prior_decisions: tuple[Decision, ...]
    budget_remaining: TokenBudget                  # required, no default
    started_at: datetime                           # required, no default
    correlation_id: CorrelationID                  # required, no default
    retry_ledger: tuple[tuple[NodeID, int], ...] = ()   # SPEC-05 reads, executor rebuilds via dataclasses.replace; tuple-of-pairs preserves frozen+slots invariants while supporting increment-only updates (Inv 10)
    state: TaskState = TaskState.RUNNING
    meta_budget_remaining: "MetaInvocationBudget | None" = None  # set only inside recovery sub-DAGs (SPEC-06)

@dataclass(frozen=True, slots=True)
class AcquireToken:
    """Immutable lease handle returned by TaskRepository.acquire.
    Carries no behavior — the AcquiredLease wrapper below provides the async
    context-manager surface that calls TaskRepository.release on exit.
    """
    task_id: TaskID
    holder_id: str                                 # executor instance id
    acquired_at: datetime
    lease_ttl_ms: int = 60_000                     # auto-released after TTL on holder crash

# NOTE: this snippet uses `from __future__ import annotations` semantics —
# all annotations are strings at runtime, so TaskRepository (defined below)
# resolves without TYPE_CHECKING. The CEMAF "no TYPE_CHECKING" rule still
# holds at the module level: at implementation time, AcquiredLease lives in
# the same module as TaskRepository or imports it at module top.
@dataclass(frozen=True, slots=True)
class AcquiredLease:
    """Async context manager wrapper around an active lease.

    __aexit__ calls repository.release(self._token); re-raises any pending
    exception after release.
    """
    _repository: TaskRepository
    _token: AcquireToken

    async def __aenter__(self) -> AcquireToken:
        return self._token

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self._repository.release(self._token)

@dataclass(frozen=True, slots=True)
class Task:
    """The aggregate persisted by TaskRepository. Mirrors TaskSnapshot fields
    plus the immutable Goal+DAG binding chosen at create()."""
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
    updated_at: datetime

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

@runtime_checkable
class TaskRepository(Protocol):
    async def create(self, *, goal: Goal, dag_id: DAGID,
                     budget: TokenBudget) -> Task: ...
    async def get(self, task_id: TaskID) -> Task: ...
    async def transition(self, task_id: TaskID, *, to: TaskState,
                         reason: str | None = None,
                         token: AcquireToken | None = None) -> Task:
        """Raises InvalidTransitionError if (from, to) violates §3 Invariant 1.
        When `token` is provided, the repository SHALL validate it against the current lease (Inv 15); when None, only repository-internal callers may invoke."""
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
    async def health(self) -> HealthStatus:
        """Liveness probe consumed by SPEC-00 readiness contract."""

class TaskInjectInterceptor(NodeInterceptor):
    """PRE phase, position 4 — runs LAST in DEFAULT_PRE_ORDER."""
    interceptor_id = "task_inject"
    phase = InterceptorPhase.PRE
```

`DAGExecutor.run(dag, *, task_id=None)` either creates a new Task or resumes
from `task_id`. Bootstrap composition: `RuntimeServices.task_repository`.

## 3. Invariants (DbC)

1. `Task state transitions SHALL follow this set: QUEUED→RUNNING, RUNNING→PAUSED, PAUSED→RUNNING, RUNNING→COMPLETED, RUNNING→HALTED, PAUSED→HALTED (timeout/cancel). All other transitions are forbidden.`
2. `WHEN a Task is HALTED or COMPLETED, transition() SHALL raise InvalidTransitionError on any further state change.`
3. `Every TaskContext.step_index SHALL satisfy 0 ≤ step_index < step_count.`
4. `TaskContext.prior_decisions SHALL be append-only and ordered by node execution sequence.`
5. `WHEN restoring from a snapshot, THE restored Task SHALL be structurally equal to the snapshot under canonical sorted-key JSON serialization for task_id, goal, dag_id, state, step_index, step_count, prior_decisions, retry_ledger, budget_remaining, correlation_id, and created_at. Task.updated_at is repository-managed and SHALL be set to utc_now() at restore time (not required to equal the pre-snapshot value).`
6. `TaskContext.budget_remaining SHALL be monotonically non-increasing across the parent task's steps. Sub-DAG (recovery) consumption SHALL NOT decrement it (SPEC-06 metering boundary).`
7. `Every node SHALL receive a TaskContext via TaskInjectInterceptor — even single-step DAGs (step_count=1).`
8. `WHEN any guardian (SPEC-05) emits HALT, THE Repository SHALL transition the Task to HALTED before the next dispatch.`
9. `TaskRepository.acquire SHALL be exclusive — concurrent resumption attempts on the same task SHALL fail with TaskInUseError.`
10. `THE retry_ledger SHALL be append/increment-only; counters never decrement. Storage is tuple[tuple[NodeID, int], ...]; read access is via a helper get_retry(ledger, node_id) -> int (default 0); writes happen by rebuilding the Task aggregate via dataclasses.replace, not in-place mutation.`
11. `THE executor SHALL call TaskRepository.increment_retry(task_id, node_id) AFTER the post-flight chain emits RECOVER on attempt N AND BEFORE re-dispatching attempt N+1. Semantics: on attempt N (N starting at 1), guardians observe retry_ledger value (N-1). Combined with DAGNode.retry_budget, "budget=K" means up to K recoveries → up to (K+1) total attempts. Worked example with retry_budget=2: attempt 1 sees ledger=0 (RECOVER, ledger→1), attempt 2 sees ledger=1 (RECOVER, ledger→2), attempt 3 sees ledger=2 (HALT — 2 ≥ 2). With retry_budget=0: attempt 1 sees ledger=0 (HALT — 0 ≥ 0). SPEC-05 Inv 15 reads (ledger < retry_budget) → RECOVER, (ledger ≥ retry_budget) → HALT, which is the same boundary inverted.`
12. `WHEN AcquireToken.lease_ttl_ms elapses without explicit release, THE TaskRepository SHALL treat the lease as expired and permit a new acquire — preventing dead executors from holding tasks indefinitely.`
13. `WHEN a PostflightDecision is RECOVER(INVOKE_META_ARCHITECT), THE Executor SHALL call increment_retry(task_id, node_id) BEFORE invoking MetaDispatcher.dispatch (SPEC-06). Combined with Inv 11, the meta sub-DAG observes the incremented attempt counter via task.retry_ledger from its first node, so nested recoveries see correct attempt accounting.`
14. `task.correlation_id (per-task, assigned at create()) and ctx.correlation_id (per-attempt, assigned by DAGExecutor at node dispatch — SPEC-00 §2) are intentionally distinct scopes. Audit and recovery references resolve as follows: SPEC-05 §3 attempt-level audit SHALL use ctx.correlation_id; SPEC-06 §3 Inv 6 parent_correlation_id SHALL be the parent attempt's ctx.correlation_id (NOT task.correlation_id). On resume across PAUSED→RUNNING, task.correlation_id persists; new attempts mint fresh ctx.correlation_id. Every AuditEntry SHALL carry both fields explicitly so query paths over either are deterministic.`
15. `WHEN a holder calls TaskRepository.release(token) OR TaskRepository.transition(token=...) AFTER the lease has expired (Inv 12) and a new holder has acquired, THE Repository SHALL raise StaleLeaseError and SHALL NOT mutate Task state. Detection: every release/transition call carries the original AcquireToken; the repository compares the persisted current_holder_id against token.holder_id and raises if they differ. This closes the multi-pod race where holder A's lease expires, holder B acquires, then A's slow callback writes — A's write is discarded with a logged event "task.stale_lease_write".`
16. `TaskContext.prior_decisions injected by TaskInjectInterceptor SHALL be windowed to the most-recent PRIOR_DECISIONS_INJECT_WINDOW (default 32) entries before injection — older entries remain in Task.prior_decisions for audit/replay but are NOT shipped to per-node chains. Window retention priority by Decision.kind: HALT > REJECT > RECOVER > ACCEPT (within the window cap; entries outside the window are kept only when retention upgrades them). Within the same Decision.kind, retention prefers Decision.at desc; ties broken by node_id ASC. This makes per-node injection deterministic for replay (SPEC-00 Property 6). Persistent storage (Task aggregate) is unbounded; only the per-node injection is windowed. Closes the long-horizon-task ballooning hazard (CE rule RULE CE-1: token budgets are first-class invariants).`
17. `TaskContext.retry_ledger injected by TaskInjectInterceptor SHALL be filtered to entries where get_retry > 0 — nodes never retried do not occupy injection slots. Persistent Task.retry_ledger is unfiltered for audit determinism.`

## 4. Acceptance Criteria (BDD)

```gherkin
Feature: Long-horizon task awareness

  Scenario: Step awareness propagates
    Given a 5-node DAG started as a new Task
    When the node at index 2 executes
    Then its TaskContext.step_index == 2 and step_count == 5
    And prior_decisions contains decisions from nodes 0 and 1

  Scenario: Retry ledger observable to guardians
    Given a node that has failed once and been re-dispatched via RECOVER
    When the guardian post-flight inspects get_retry(task.retry_ledger, node.id) on the second attempt
    Then the value is 1 (incremented after the first attempt's RECOVER, before the second attempt)

  Scenario: task.retry_started emitted on every RECOVER re-dispatch
    Given a node with retry_budget=2 whose first attempt RECOVERs with reason "non_member_citation"
    When the executor re-dispatches attempt 2
    Then a task.retry_started log event is emitted carrying node_id, attempt=2, retry_budget=2, reason="non_member_citation"
    And one event is emitted per re-dispatch — including each meta-recovered retry — never coalesced

  Scenario: Pause and resume across processes
    Given a Task in state RUNNING with 3 of 10 steps complete
    When the executor pauses the task and the process exits
    And a new executor acquire() the task and calls resume()
    Then state transitions PAUSED → RUNNING
    And the next dispatched node has step_index == 3
    And prior_decisions and retry_ledger from steps 0..2 are present

  Scenario: Halt is terminal
    Given a Task transitioned to HALTED
    When transition(to=RUNNING) is called
    Then the Repository raises InvalidTransitionError

  Scenario: Decisions are append-only
    Given a Task with 3 prior decisions
    When a 4th decision is appended
    Then the decision tuple has length 4 in original order
    And no prior decision has been mutated

  Scenario: Budget monotonicity
    Given a Task with budget_remaining=10000 at step 0
    When step 1 consumes 800 tokens and step 2 consumes 1200
    Then budget_remaining at step 3 is 8000 ± 0
    And budget_remaining never increases

  Scenario: Single-step DAG still receives TaskContext
    Given a 1-node DAG
    When the node executes
    Then it receives a TaskContext with step_index=0 and step_count=1

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

  Scenario: Stale-lease release is rejected (Inv 15 — release path)
    Given executor A's lease has expired and executor B has acquired
    When A's slow callback calls release(token_A)
    Then the Repository raises StaleLeaseError
    And Task state is unchanged
    And a "task.stale_lease_write" log event is emitted
    And cemaf_task_stale_lease_writes_total is incremented

  Scenario: Stale-lease transition is rejected (Inv 15 — transition path)
    Given executor A's lease has expired and executor B has acquired
    When A's slow callback calls transition(token=token_A, to=RUNNING)
    Then the Repository raises StaleLeaseError
    And Task state is unchanged
    And a "task.stale_lease_write" log event is emitted
    And cemaf_task_stale_lease_writes_total is incremented

  Scenario: First-attempt HALT when retry_budget == 0 (Inv 11 boundary)
    Given a node N with retry_budget=0
    And the agent emits an ungrounded Claim on attempt 1
    When CiteOrFailInterceptor evaluates the post-flight (SPEC-05 Inv 15)
    Then get_retry(task.retry_ledger, N.id) == 0
    And 0 ≥ N.retry_budget
    And PostflightDecision is HALT(scope=TASK)
    And TaskRepository.increment_retry is NOT called

  Scenario: Recovery sub-DAG budget is metered separately (cross-ref SPEC-06)
    Given a parent Task with budget_remaining=10000
    When a recovery sub-DAG runs and consumes 3000 tokens via MetaInvocationBudget
    Then parent.budget_remaining stays 10000 (Inv 6 — see SPEC-06 §4 "Token budget isolation")

  Scenario: Guardian HALT propagates to Task
    Given any guardian post-flight returns HALT
    When the executor finishes the post chain
    Then TaskRepository.transition(to=HALTED) is invoked before next dispatch

  Scenario: increment_retry runs before MetaDispatcher.dispatch (Inv 13)
    Given a node whose post-flight returns RECOVER(INVOKE_META_ARCHITECT)
    And get_retry(task.retry_ledger, node.id) is 0 at decision time
    When the Executor invokes MetaDispatcher.dispatch
    Then TaskRepository.increment_retry(task.id, node.id) was called BEFORE dispatch
    And the meta sub-DAG's first TaskInjectInterceptor observes retry_ledger value 1

  Scenario: correlation_id scopes are distinct and both audited (Inv 14)
    Given a Task created with task.correlation_id="T-1"
    When attempt 1 of node N runs and Executor mints ctx.correlation_id="C-1"
    Then every AuditEntry for the attempt carries task_correlation_id="T-1" AND ctx_correlation_id="C-1"
    And the attempt's PostflightDecision.correlation_id == "C-1"
    When the task is paused and resumed and attempt 2 of N runs
    Then task.correlation_id is still "T-1"
    And the new ctx.correlation_id is freshly minted (≠ "C-1")
    And SPEC-06 parent_correlation_id (when meta dispatched) equals the parent attempt's ctx.correlation_id, NOT task.correlation_id

  Scenario: prior_decisions injection caps at PRIOR_DECISIONS_INJECT_WINDOW
    Given a Task with 50 historical Decisions
    When TaskInjectInterceptor builds the per-node TaskContext
    Then ctx.prior_decisions has at most 32 entries (PRIOR_DECISIONS_INJECT_WINDOW)
    And HALT and REJECT entries are retained over RECOVER and ACCEPT entries

  Scenario: prior_decisions retention priority within budget
    Given the window cap is 32 and the Task has 60 decisions: 5 HALT, 10 REJECT, 20 RECOVER, 25 ACCEPT
    When TaskInjectInterceptor projects them
    Then all 5 HALT and 10 REJECT entries are present
    And the remaining 17 slots are filled by most-recent RECOVER first then ACCEPT

  Scenario: retry_ledger injection filters to nodes with prior retries
    Given a Task whose retry_ledger contains 12 entries, 3 with count > 0
    When TaskInjectInterceptor projects retry_ledger
    Then ctx.retry_ledger contains exactly the 3 entries with count > 0
    And the 9 zero-count entries are dropped
```

## 5. Out of Scope

- Multi-tenant task quotas — separate spec.
- Distributed task coordination across executors (single-executor MVP via `acquire()` lock only).
- Human-in-the-loop pause approval workflows — captured at SPEC-05 layer only.
- Sub-task decomposition (Task spawning Task) — follow-on; recovery sub-DAGs (SPEC-06) are NOT sub-tasks.

## 6. Dependencies

- SPEC-01 (interceptor protocol)
- SPEC-00 §2 (TokenBudget, Goal, Citation)
- `persistence/entities.py`, `persistence/protocols.py`
- `replay/replayer.py` (deterministic step replay reuses Decision provenance)

## 7. Correctness Properties

### Property 1: Transition legality
*For any* Task, the sequence of states observed satisfies the §3 Invariant 1
DAG; no observed transition is outside the allowed set.

**Validates: §3 Invariants 1, 2 / §4 "Halt is terminal"**

### Property 2: Snapshot fidelity
*For any* snapshot S taken at t1 and restored at t2 > t1, the restored Task's
`task_id`, `goal`, `state`, `prior_decisions`, `retry_ledger`, and
`budget_remaining` equal those of S.

**Validates: §3 Invariant 5 / §4 "Pause and resume across processes"**

### Property 3: Decision append-only
*For any* Task, any operation that produces a Task' with a `prior_decisions`
of shorter length OR with any earlier decision mutated is rejected.

**Validates: §3 Invariant 4 / §4 "Decisions are append-only"**

### Property 4: Budget non-increase (parent metering)
*For any* sequence of TaskContexts c1..cn for the same parent Task,
`c_i.budget_remaining ≥ c_{i+1}.budget_remaining` for all i. Recovery sub-DAG
consumption is metered separately (SPEC-06).

**Validates: §3 Invariant 6 / §4 "Budget monotonicity"**

### Property 5: Step bound
*For any* TaskContext c, `0 ≤ c.step_index < c.step_count`.

**Validates: §3 Invariant 3 / §4 "Step awareness propagates"**

### Property 6: Retry monotonicity
*For any* node, `task.retry_ledger[node_id]` is monotonically non-decreasing.

**Validates: §3 Invariant 10 / §4 "Retry ledger observable to guardians"**

### Property 7: Per-node injection windowing determinism
*For any* identical `Task.prior_decisions` and `Task.retry_ledger`, two
invocations of `TaskInjectInterceptor` produce byte-identical
`TaskContext.prior_decisions` and `retry_ledger` projections (canonical
sorted-key JSON). Replay-safe across process boundaries.

**Validates: §3 Invariants 16, 17 / §4 "prior_decisions injection caps at PRIOR_DECISIONS_INJECT_WINDOW", "prior_decisions retention priority within budget"**

## 8. Eval Criteria

State-machine spec — deterministic evaluators only.

All evaluators in this table are eval_kind=`repository` unless explicitly marked `online` (per SPEC-05 Inv 20).

| Evaluator | Node | Mode | Threshold | Method |
|---|---|---|---|---|
| TransitionLegalityEvaluator | repository transitions | GATE | illegal == 0 | deterministic |
| BudgetMonotonicityEvaluator | task lifetime | GATE | violations == 0 | deterministic |
| DecisionImmutabilityEvaluator | task lifetime | GATE | mutations == 0 | deterministic |
| RetryMonotonicityEvaluator | task lifetime | GATE | decrements == 0 | deterministic |

## 9. Observability Contract

- **Span**: `gen_ai.task.lifetime` — `task.id`, `task.state`, `step.index`, `step.count`, `budget.remaining`
- **Span**: `gen_ai.task.transition` — `from`, `to`, `reason`
- **Log events**: `task.created`, `task.paused`, `task.resumed`, `task.halted`, `task.completed`, `task.invalid_transition`, `task.acquire_conflict`, `task.lease_expired{task_id, holder_id, expired_at_iso, ttl_ms}`, `task.retry_started` (emitted by the executor on every RECOVER re-dispatch — RETRY_WITH_HINTS, REROUTE_TO_AGENT, or post-recovery re-issue — carrying `node_id`, `attempt` (1-based), `retry_budget`, `reason` from the prior PostflightDecision; rendered to users via SPEC-05 §10 status-event copy as "Retrying step (`<DAGNode.display_name>`), attempt N of M". One event per re-dispatch — including each meta-recovered retry — so users see every attempt, not just the first.)
- **Metrics**: `cemaf_task_state_transitions_total{from,to}` (counter — emitted on every transition; replaces the earlier mis-shaped `cemaf_task_state_total{state}` counter), `cemaf_task_state_current{state}` (gauge — current count of tasks in each state, sampled), `cemaf_task_steps_completed_total` (counter, no per-task label), `cemaf_task_budget_remaining_tokens` (gauge, no labels — sampled snapshot only), `cemaf_task_retries_total{node_type,outcome}` — per-`node_id` labels are forbidden by SPEC-00 §9 cardinality rules; `node_id` stays a span attribute only. Also: `cemaf_task_acquire_conflicts_total`, `cemaf_task_lease_expired_total`, `cemaf_task_stale_lease_writes_total` (no labels — Inv 15 stale-holder writes)

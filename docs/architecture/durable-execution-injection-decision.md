# Durable Execution Injection Boundary

Status: proposed architecture; implementation pending
Date: 2026-07-13
Scope: disposable workers, durable task ownership, recovery, replay, effects,
and backend injection

## Question

What should CEMAF inject into an executor so a worker can disappear without
losing durable authority, while keeping the companion service plane off the
agent/DAG decision path?

## Decision

Inject one backend-independent `DurableRunCoordinator` into
`RuntimeServices`. Do not inject database clients, separate checkpointers,
lease stores, loggers, dispatchers, or projections into `DAGExecutor`.

The coordinator is deterministic framework infrastructure. It owns the
execution-attempt lifecycle and delegates atomic persistence to a
`RuntimeAuthority` adapter. A separate `CompanionRuntime`, started at
application/process lifespan, publishes wake-ups for runnable or abandoned
tasks, dispatches the outbox, and advances rebuildable projections. Workers
still claim ownership from the authority themselves.

```text
                     application composition root
                                  │
                 ┌────────────────┴────────────────┐
                 │                                 │
                 ▼                                 ▼
      RuntimeServices.durable_execution      CompanionRuntime
          DurableRunCoordinator          wake-up scan / outbox / projection
                 │                       retention / migration lifecycle
                 └──────────────┬──────────────────┘
                                ▼
                         RuntimeAuthority
                     lease + fence + transaction
                  task/checkpoint/journal/outbox
                                │
              ┌─────────────────┼──────────────────┐
              ▼                 ▼                  ▼
       production adapter  embedded adapter   committed journal
       selected profile    reference profile       │
                                                  ├── search projection
                                                  └── analytics projection
```

This is not a supervisor agent. It does not choose DAG steps, generate plans,
or sit between nodes as an intelligent actor. The worker still executes the
DAG. The coordinator only enforces ownership and commit semantics; background
services only move already-committed work and records.

In this document, **companion service plane** means the authority plus its
background and read-side services. `DurableRunCoordinator` is the thin client
injected into each worker; `CompanionRuntime` is the off-path process lifecycle.
Neither is a second pipeline.

## What We Are Resolving

The feature is **durable execution**, not merely “database support.” It must
resolve these failure modes as one contract:

| Failure | Required behavior |
|---|---|
| Worker dies after a node | A replacement discovers the task and resumes from the last committed checkpoint |
| Two workers race a resume | One current lease/fencing token can commit; the stale worker is rejected |
| Lease expires during slow work | Heartbeat loss cancels best-effort; fencing prevents every stale authoritative write |
| Process dies during persistence | Task transition, checkpoint, journal, and outbox all commit or all roll back |
| Process dies after commit | The committed checkpoint is visible and pending effects remain dispatchable |
| Process dies around an external call | The outbox retries; the destination must enforce the supplied idempotency key |
| Search or analytics is unavailable | Execution continues; projections catch up from the committed journal |
| A backend is swapped | The same authority conformance suite proves identical observable guarantees |
| A replacement heals a failure | Retry ledger, recovery decision, inputs, and resulting patches survive independently of the worker |
| Operators request replay | Replay reads committed lineage/journal, not a dead worker's memory |

The current file proof resolves only part of this. It proves state survival,
fenced takeover, atomic file replacement, and an idempotent local destination.
It manually launches the replacement worker, has no lease renewal, and cannot
atomically commit checkpoint + trace + external-effect intent. Therefore it is
a useful reference test, not the production architecture.

## What We Are Not Claiming

- Exactly-once execution of node code. A node attempt may run again after an
  ambiguous crash; only its authoritative commit is fenced.
- Exactly-once behavior for an arbitrary external API. Effective-once behavior
  requires destination idempotency or a transactional receiver.
- That a search or analytics engine can own runtime state. Elasticsearch and
  DuckDB are examples of disposable, rebuildable projections.
- That a lease alone stops a partitioned process. The fencing predicate on
  every transaction is the safety mechanism; heartbeat is liveness.
- That checkpoint snapshots are event sourcing. Checkpoints are the efficient
  resume source; the append-only journal is the audit/projection source.

## The Two Injection Lifetimes

### 1. Application-lifetime resources

Database pools, migrations, the authority adapter, the companion runtime, and
projector/dispatcher loops are created once during application startup and
closed during shutdown. They are not reconstructed per DAG node.

```python
authority = create_runtime_authority(
    backend="postgres",
    dsn=secret_ref,
    migration_mode="validate",
)

coordinator = DefaultDurableRunCoordinator(
    authority=authority,
    lease_policy=LeasePolicy(ttl_seconds=30, renew_every_seconds=10),
)

executor = create_executor(
    agent_registry=registry,
    services=RuntimeServices(durable_execution=coordinator),
)

companion = create_companion_runtime(
    authority=authority,
    outbox_destinations=destinations,
    projections=(elastic_projection, duckdb_projection),
)
```

An installation may run `CompanionRuntime` in a separate process. Both
processes connect to the same authority; neither needs a shared Python object.

### 2. Attempt-lifetime state

Tenant, durable task identity, attempt identity, lease, and fencing token are
created or resolved per execution. They must not live in the frozen
application-level `RuntimeServices`, and authority fields must not be stored in
agent-controlled `Context`.

The caller supplies only trusted request scope and an optional task to resume:

```python
result = await executor.run(
    dag,
    initial_context,
    task_id=task_id,
    scope=ExecutionScope(tenant_id=tenant_id, principal=principal),
)
```

The coordinator generates `attempt_id` and `holder_id`, acquires the lease,
and receives the fencing token from the authority. Callers and agents never
choose fencing tokens or authority generations.

## Executor-Facing Protocol

The executor should consume a behavior-oriented protocol, not storage methods:

```python
@runtime_checkable
class DurableRunCoordinator(Protocol):
    async def open_attempt(
        self,
        *,
        scope: ExecutionScope,
        task_id: TaskID | None,
        dag: DAG,
        initial_context: Context,
    ) -> DurableAttempt: ...

    async def claim_next(
        self,
        *,
        scope: ExecutionScope,
        worker: WorkerIdentity,
    ) -> DurableAttempt | None: ...

@runtime_checkable
class DurableAttempt(Protocol):
    identity: AttemptIdentity
    checkpoint: CheckpointEnvelope

    async def commit_node(self, commit: NodeCommit) -> None: ...
    async def record_recovery(self, recovery: RecoveryCommit) -> None: ...
    async def complete(self, result: ExecutionResult) -> None: ...
    async def fail(self, failure: ExecutionFailure) -> None: ...
    async def close(self) -> None: ...
```

`DefaultDurableRunCoordinator` owns heartbeat, cancellation on ownership loss,
checkpoint materialization, and translation between executor results and one
authority transaction. `RuntimeAuthority` remains the lower-level adapter
contract used by the coordinator and companion runtime.

The coordinator must be safe to share across concurrent runs. Mutable
attempt-specific state—including heartbeat task, lease, fence, and resume
cursor—lives only in the returned `DurableAttempt`.

This split keeps SQL/Mongo concerns out of orchestration while making the
correct transaction impossible to bypass accidentally.

## Authority-Facing Contract

The authority must provide both safety and work discovery:

```python
@runtime_checkable
class RuntimeAuthority(Protocol):
    capabilities: BackendCapabilities

    async def create_task(self, request: CreateTask) -> TaskRecord: ...
    async def claim_task(self, request: ClaimTask) -> AttemptLease | None: ...
    async def claim_runnable(self, request: ClaimRunnable) -> AttemptLease | None: ...
    async def renew(self, lease: AttemptLease) -> AttemptLease: ...
    async def load_resume_state(self, lease: AttemptLease) -> ResumeState: ...
    def transaction(self, lease: AttemptLease) -> AsyncContextManager[DurabilityUnitOfWork]: ...
    async def release(self, lease: AttemptLease) -> None: ...
```

`claim_runnable` closes the gap in the current demonstration: any worker can
atomically claim a `QUEUED`, explicitly retryable, or expired-running task.
Deployments that already use SQS, Kafka, or another queue may use redelivery as
the wake-up signal, and `CompanionRuntime` may publish equivalent wake-ups, but
authority acquisition and fencing remain mandatory. A queue message is never
proof of ownership, and the companion never acquires a worker's lease.

## Canonical Durable Unit

CEMAF must reconcile its current `run_id` API with SPEC-04 before implementing
adapters:

- `task_id` identifies the durable workflow across crashes and resumes.
- `attempt_id` identifies one worker's execution attempt.
- `node_attempt` identifies a retry/recovery of one node.
- `run_id` becomes a compatibility alias for `task_id` during migration or is
  removed at the declared breaking-version boundary.

There must not be independent `RunLeaseStore` and `TaskRepository` concepts
protecting the same execution. `TaskRepository` semantics become the
task-oriented view of `RuntimeAuthority`; all mutations participate in the
same fenced unit of work.

## Commit Boundary

After a node produces a result, the coordinator creates one `NodeCommit` and
executes one authority transaction:

```python
async with authority.transaction(attempt.lease) as tx:
    await tx.assert_fence()
    await tx.transition_task(commit.transition)
    await tx.save_checkpoint(commit.checkpoint)
    await tx.append_journal(commit.events)
    await tx.enqueue_effects(commit.effects)
```

Trace events required for recovery or audit are journal records in this
transaction. High-volume telemetry may be projected asynchronously, but it
cannot be the only record of a state transition.

Effectful tools in durable mode must declare one of these capabilities:

1. `PURE` — safe to repeat and produces no external effect.
2. `IDEMPOTENT` — receives a stable CEMAF effect key enforced by the destination.
3. `OUTBOXED` — records intent during `NodeCommit`; a dispatcher performs it
   after commit.
4. `UNSAFE` — rejected by strict durable mode or explicitly accepted with a
   downgraded guarantee visible in readiness.

Without this rule, an HTTP call inside `execute_node()` can occur before the
checkpoint commits and no storage adapter can make the combined operation
atomic.

## Runtime Sequence

1. An API caller creates a task, or a worker receives/polls a task identifier.
2. The coordinator atomically claims the task and obtains a new fencing token.
3. It loads the last committed resume state and starts heartbeat renewal.
4. The worker executes the next eligible node.
5. The coordinator fences and atomically commits task state, checkpoint,
   journal, and outbox intent.
6. Steps 4–5 repeat until pause, halt, or completion.
7. Graceful exit releases the lease; process loss leaves it to expire.
8. Queue redelivery or the companion work scanner exposes the abandoned task.
9. A replacement receives a higher fencing token and resumes.
10. Outbox/projector loops process only committed records and never block the
    worker hot path.

## Responsibility Boundary

| Component | Owns | Does not own |
|---|---|---|
| `DAGExecutor` | DAG semantics and node execution | Database, lease algorithms, background scanning |
| `DurableRunCoordinator` | Attempt lifecycle, heartbeat, resume, fenced commits | SQL/Mongo representation, DAG decisions |
| `RuntimeAuthority` | Atomic authoritative records and backend capabilities | Agent behavior, external delivery |
| `CompanionRuntime` | Optional runnable-task wake-ups, outbox, projections, retention | Task ownership, intelligent orchestration, or node execution |
| Worker process | Temporary compute and in-flight values | Durable truth |
| Destination adapter | Delivery and idempotency capability | Workflow ownership |
| Projection adapters | Search and analytics read models | Runtime authority |

## Rejected Alternatives

### Inject every store separately

Rejected because a checkpoint, trace, state transition, and effect intent can
split across independent commits. Structural typing alone cannot recover the
missing transaction boundary.

### Inject `RuntimeAuthority` directly into `DAGExecutor`

Rejected as the public executor seam. It couples orchestration to storage-level
operations and duplicates heartbeat/commit logic across executor variants.
The coordinator may depend on the authority internally.

### Put dispatcher and projectors in `RuntimeServices`

Rejected because those are application-lifetime background loops, not
per-executor hot-path dependencies. Running one copy per worker creates unclear
ownership and shutdown behavior.

### Rely only on an external queue

Rejected as the correctness authority. Queues can redeliver, duplicate, delay,
or lose visibility leases independently. They are wake-up mechanisms; the
database fence decides who may commit.

### Make the companion an agent/supervisor

Rejected because an intelligent boss on the hot path adds a new failure and
latency domain. Recovery policy is executable code injected into workers;
recovery state and decisions are durable authority records.

## Required Reconciliation Before Adapter Work

1. Update SPEC-00's canonical `DAGExecutor.run` contract to include trusted
   tenant execution scope without placing it in `Context`.
2. Update SPEC-04 so task acquisition includes renewal and monotonic fencing,
   and make `TaskRepository` a view over the authority transaction.
3. Replace the independent `RunLeaseStore`/`FencedCheckpointer` production path
   with the coordinator; retain it only as a compatibility/local proof.
4. Define effect capability metadata for tools and strict durable-mode
   readiness validation.
5. Define `claim_runnable` ordering, fairness, retry eligibility, backoff, and
   poison-task/dead-letter semantics.
6. Add one shared crash/concurrency contract suite that runs against every
   authority adapter CEMAF advertises as conformant.
7. Change the disposable-worker example so replacement is discovered through
   the work-source contract rather than launched manually.

## Acceptance Scenarios

The boundary is accepted only when tests prove all of the following:

- kill the worker before node execution, during execution, before commit,
  during commit, and immediately after commit;
- stop heartbeats and prove a replacement is discovered and claims the task;
- allow the stale process to continue and prove every mutation is rejected;
- race multiple replacements and prove only one fencing token commits;
- interrupt outbox delivery before and after destination acknowledgement;
- delete any configured projection and rebuild equal read models from the journal;
- swap each authority adapter under the identical black-box test suite;
- show that an `UNSAFE` effectful tool fails strict production readiness;
- prove no worker-local object or file is needed to resume, heal, trace, or
  replay the task.

## Consequence

The first implementation milestone is not “build every suggested adapter.” It is to ship
the identity model, coordinator protocol, authority/UoW protocol, runnable-work
contract, effect capability contract, and shared destructive test harness.
One embedded adapter then becomes the executable semantic reference. One
production authority profile is selected and graduated only after the reference
behavior is stable. Further authority and projection adapters are optional and
must prove parity independently.

## Supporting References

- [Temporal durable execution overview](https://docs.temporal.io/) supports the
  core expectation that execution resumes after worker or infrastructure loss;
  CEMAF still defines and tests its own semantics.
- [AWS transactional outbox guidance](https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/transactional-outbox.html)
  documents the dual-write failure and the need for same-transaction outbox
  persistence plus idempotent consumers.
- The [enterprise durability plan](enterprise-durability-plan.md#17-authoritative-references)
  links the authoritative backend concurrency and transaction documentation
  used for CEMAF's adapter role assignments.

# Enterprise Durability And Persistence Plan

Status: implementation plan; not a production-readiness claim
Scope: runtime authority, checkpoints, leases, run journal, outbox, and operational projections
Audience: CEMAF maintainers, adapter authors, platform engineers, and reviewers

## 1. Executive Decision

CEMAF needs two explicitly different storage roles:

1. **Runtime authority** — the transactional source of truth for run ownership,
   checkpoints, lineage, and pending external effects.
2. **Operational projection** — rebuildable stores optimized for analytics,
   search, reporting, and long-term trace exploration.

The approved backend roles are:

| Backend | Runtime authority | Operational projection | Intended deployment |
|---|---:|---:|---|
| SQLite | Yes | Limited | Local, edge, single-host, test reference |
| PostgreSQL | **Yes; enterprise default** | Yes | Multi-host production control plane |
| MongoDB | Yes, with replica-set/sharded transaction requirements | Yes | Document-oriented production alternative |
| DuckDB | **No** | Yes | Embedded analytics, offline replay, benchmark history |
| Elasticsearch | **No** | Yes | Searchable traces/events and operator read models |

DuckDB and Elasticsearch must never be presented as authoritative lease,
checkpoint, or outbox backends. DuckDB's stable in-process model permits one
read-write process, while Elasticsearch is designed around distributed indexing
and optimistic document concurrency rather than cross-record control-plane
transactions.

PostgreSQL is the recommended production authority because it can atomically
commit run state, checkpoint state, journal entries, and outbox rows while using
row locks and `SKIP LOCKED` queue consumption. MongoDB is supported as an
alternative, but multi-document transactions require a replica set or sharded
cluster. SQLite supplies the executable reference semantics and local durable
mode.

## 2. Current-State Audit

The repository does not yet provide this enterprise backend layer.

| Existing capability | Current implementation | Gap |
|---|---|---|
| Checkpoints | `InMemoryCheckpointer`, atomic `FileCheckpointer` | No SQLite/PostgreSQL/Mongo checkpoint adapter; no listing/CAS/retention protocol |
| Ownership | `FileRunLeaseStore`, `RunLease`, `FencedCheckpointer` | No renewal/heartbeat; no shared-database implementation; not wired through `RuntimeServices` |
| Run traces | `InMemoryRunLogger`, `FileRunLogger` | Stateful single-current-run API; no durable reload/query protocol; not transactionally coupled to checkpoints |
| External effects | `FileIdempotentEffectSink` | No durable outbox lifecycle, claim/retry/dead-letter, or DB adapter |
| Domain persistence | `ProjectStore`, `ArtifactStore`, `ContentStore`, `RunStore` protocols | Factory default is an intentionally unregistered `mock`; no built-in implementations |
| SQLite | Memory, vector, and blueprint stores | No unified runtime authority |
| PostgreSQL | Memory, sessions, pgvector, and audit adapters | No unified runtime authority or shared transaction boundary |
| MongoDB | Environment option names only | No implementation |
| DuckDB | None | No analytics projection |
| Elasticsearch | None | No trace/search projection |
| Long-running task repository | Detailed in SPEC-04 | Architecture map still marks implementation as scaffold pending |

Important structural problems:

- `CheckpointingDAGExecutor` is a wrapper outside the normal composition root.
- `RuntimeServices` has no durability service bundle.
- A checkpoint write, run-log write, and external effect cannot currently commit
  as one transaction.
- Existing PostgreSQL adapters create schema lazily at runtime. Enterprise
  authority migrations must be explicit and independently deployable.
- Persistence factory registries describe extensibility but do not provide a
  working built-in default.
- Current file leases use application time and do not renew. Database adapters
  must use database/server time and heartbeat renewal.

## 3. Non-Negotiable Invariants

Every authoritative adapter must satisfy the same observable contract.

1. At most one unexpired lease holder owns a `(tenant_id, run_id)` pair.
2. Every successful takeover increments a monotonic fencing token.
3. A stale fencing token can never mutate run state, checkpoints, journal, or
   outbox—even if its operation began before takeover.
4. A committed runtime transaction contains all or none of:
   - run-state transition;
   - checkpoint version/current pointer;
   - append-only journal records;
   - outbox effects.
5. Checkpoint versions are immutable. Updating “current” selects a version; it
   never rewrites historical versions.
6. Journal sequence is monotonic per run and event IDs are globally idempotent
   within a tenant.
7. An outbox effect key is unique within `(tenant_id, destination)`.
8. Delivery is at-least-once internally and effectively-once at the destination
   through its idempotency key. CEMAF must never claim universal exactly-once
   behavior for a destination that ignores idempotency.
9. Tenant identity is part of every primary key, lookup, lease, and query.
10. Serialization includes an explicit schema version and canonical content
    hash. Unknown future versions fail closed.
11. All timestamps are timezone-aware UTC. Lease correctness uses the authority
    database's clock, not a worker clock.
12. Search and analytics failures never block the execution hot path.
13. Elasticsearch and DuckDB data can be deleted and rebuilt from the authority
    journal without losing authoritative state.
14. No adapter silently reduces guarantees. Unsupported capabilities are
    rejected during composition.

## 4. Target Architecture

```text
                         disposable workers
                    acquire / renew / transact
                                │
                                ▼
                ┌──────────────────────────────┐
                │ RuntimeAuthority             │
                │                              │
                │ lease + fencing              │
                │ transaction / unit of work   │
                │ checkpoints + run state      │
                │ append-only journal          │
                │ transactional outbox         │
                └──────────────┬───────────────┘
                               │ committed outbox/journal
              ┌────────────────┼───────────────────┐
              ▼                ▼                   ▼
       external APIs     Elasticsearch         DuckDB
       idempotency key   trace/search view     analytics/replay view
       or receiver       rebuildable           rebuildable
```

The worker calls one authority transaction after a node completes. It does not
independently write four stores. A separate dispatcher claims outbox records and
delivers effects. Separate projectors consume the journal/outbox and update
Elasticsearch or DuckDB.

There is no supervisor agent in this design. Claiming, fencing, projection, and
delivery are deterministic infrastructure services.

## 5. Public Protocol Design

Do not extend the existing four domain-store protocols into a lowest-common-
denominator “universal store.” Add a dedicated durability package with narrow
capability protocols and one transactional authority composition.

Proposed package:

```text
src/cemaf/durability/
├── models.py              # envelopes, lease, checkpoint, journal, outbox
├── protocols.py           # authority/UoW/projection contracts
├── capabilities.py        # declared backend guarantees
├── factories.py           # registry + typed configuration
├── migrations.py          # migration runner/protocol
├── sqlite.py              # reference authority
├── postgres.py            # enterprise authority
├── mongo.py               # document authority
├── duckdb.py              # analytics projection only
├── elastic.py             # search/trace projection only
├── outbox.py              # dispatcher and retry policy
└── projectors.py          # journal → projections
```

The initial public shape should be equivalent to:

```python
@dataclass(frozen=True)
class BackendCapabilities:
    transactions: bool
    leases: bool
    fencing: bool
    checkpoints: bool
    journal: bool
    transactional_outbox: bool
    projection: bool
    multi_process: bool
    multi_host: bool

@runtime_checkable
class RuntimeAuthority(Protocol):
    capabilities: BackendCapabilities

    async def acquire(
        self,
        *,
        tenant_id: str,
        run_id: RunID,
        holder_id: str,
        ttl: timedelta,
    ) -> RunLease | None: ...

    async def renew(self, lease: RunLease, *, ttl: timedelta) -> RunLease: ...
    async def release(self, lease: RunLease) -> None: ...

    def transaction(
        self,
        *,
        lease: RunLease,
    ) -> AsyncContextManager[DurabilityUnitOfWork]: ...

    async def load_current_checkpoint(
        self,
        *,
        tenant_id: str,
        run_id: RunID,
    ) -> CheckpointEnvelope | None: ...

    async def health(self) -> DurabilityHealth: ...
    async def close(self) -> None: ...

@runtime_checkable
class DurabilityUnitOfWork(Protocol):
    async def save_checkpoint(self, checkpoint: CheckpointEnvelope) -> None: ...
    async def transition_run(self, transition: RunTransition) -> None: ...
    async def append_events(self, events: tuple[JournalEvent, ...]) -> None: ...
    async def enqueue_effects(self, effects: tuple[OutboxEffect, ...]) -> None: ...

@runtime_checkable
class OutboxStore(Protocol):
    async def claim_batch(
        self,
        *,
        dispatcher_id: str,
        limit: int,
        lease_ttl: timedelta,
    ) -> tuple[ClaimedEffect, ...]: ...
    async def mark_delivered(self, claim: ClaimedEffect, receipt: JSON) -> None: ...
    async def mark_failed(self, claim: ClaimedEffect, error: str) -> None: ...

@runtime_checkable
class OperationalProjection(Protocol):
    async def apply(self, events: tuple[JournalEvent, ...]) -> ProjectionCursor: ...
    async def cursor(self, *, tenant_id: str) -> ProjectionCursor: ...
    async def rebuild(self, source: JournalReader) -> None: ...
```

`RuntimeAuthority.transaction()` is the critical missing seam. Merely injecting
separate `Checkpointer`, `RunLogger`, and `EffectSink` implementations cannot
provide atomic state-plus-effect semantics.

### Runtime composition

Add one field rather than scattering backend objects:

```python
@dataclass(frozen=True)
class DurabilityServices:
    authority: RuntimeAuthority
    outbox_dispatcher: OutboxDispatcher | None = None
    projections: tuple[OperationalProjection, ...] = ()

RuntimeServices(
    durability=DurabilityServices(...),
    # existing eval, moderation, memory, LLM, etc.
)
```

`create_executor()` must:

1. validate required authority capabilities;
2. acquire or resume the run lease;
3. start a renewal heartbeat;
4. fence each node commit;
5. atomically commit checkpoint, transition, journal, and outbox;
6. stop heartbeat and release on graceful completion;
7. leave expiry-based takeover to replacement workers after process loss.

The legacy `CheckpointingDAGExecutor` remains supported during migration, then
becomes a compatibility adapter over `RuntimeAuthority`.

## 6. Canonical Data Model

Every authority implementation must preserve these logical records even when
its physical representation differs.

### `runs`

| Field | Requirement |
|---|---|
| `tenant_id`, `run_id` | Composite primary identity |
| `dag_name`, `dag_revision` | Exact executable definition identity |
| `status` | Pending/running/paused/completed/failed/cancelled |
| `current_checkpoint_version` | Pointer to immutable checkpoint |
| `fencing_token` | Highest accepted token |
| `schema_version` | Serialization contract version |
| `created_at`, `updated_at`, `completed_at` | Authority timestamps |
| `metadata` | Bounded JSON; secrets forbidden |

### `run_leases`

| Field | Requirement |
|---|---|
| `tenant_id`, `run_id` | Unique lease identity |
| `holder_id` | Worker/process identity |
| `fencing_token` | Monotonically incremented on each acquisition |
| `acquired_at`, `renewed_at`, `expires_at` | Authority-clock timestamps |

Lease cleanup jobs are operational hygiene only. Correctness must depend on the
`expires_at` predicate, never on timely deletion.

### `checkpoints`

| Field | Requirement |
|---|---|
| `tenant_id`, `run_id`, `version` | Immutable composite key |
| `fencing_token` | Token authorizing creation |
| `status`, `completed_nodes`, `pending_nodes`, `failed_node` | Resume state |
| `context_payload` | Canonical serialized context and patch history |
| `content_sha256` | Integrity verification |
| `codec`, `schema_version` | Decode/migration contract |
| `created_at` | Authority timestamp |

Large payloads may later move to object storage, but the authority transaction
must commit a content-addressed manifest. That extension is outside the first
adapter release.

### `run_journal`

| Field | Requirement |
|---|---|
| `tenant_id`, `run_id`, `sequence` | Ordered primary key |
| `event_id` | Unique idempotency key |
| `event_type`, `source`, `correlation_id` | Query dimensions |
| `payload`, `metadata` | Versioned bounded JSON |
| `occurred_at`, `committed_at` | Event and authority times |

The journal is append-only. Mutable operator snapshots are projections of this
journal plus the `runs` row.

### `outbox`

| Field | Requirement |
|---|---|
| `tenant_id`, `destination`, `effect_key` | Unique idempotency identity |
| `run_id`, `journal_sequence` | Causal link |
| `payload` | Versioned bounded JSON |
| `state` | pending/inflight/delivered/dead |
| `attempts`, `next_attempt_at` | Retry control |
| `claimed_by`, `claim_token`, `claim_expires_at` | Fenced dispatcher claim |
| `last_error`, `receipt` | Operator evidence |

An outbox row and the checkpoint that caused it must commit in one authority
transaction.

## 7. Backend-Specific Plans

### 7.1 SQLite authority

Purpose: canonical semantics, local applications, development, edge deployments,
and destructive contract tests.

Implementation requirements:

- `aiosqlite`; one managed connection per authority instance.
- `PRAGMA foreign_keys=ON`.
- WAL mode for concurrent readers and one writer.
- Configurable `busy_timeout`; bounded retry with jitter on `SQLITE_BUSY`.
- `BEGIN IMMEDIATE` for lease acquisition and every fenced unit of work.
- `synchronous=FULL` for the durability profile; `NORMAL` allowed only through an
  explicit lower-durability profile.
- Database file and WAL must be on local storage. Reject/document network filesystems.
- Schema migrations run before readiness; never lazily during the first request.
- Online backup and restore verification using SQLite backup APIs.

SQLite serializes writes and provides atomic transactions across connections.
This makes it suitable for multi-process single-host authority, not horizontally
scaled multi-host authority.

### 7.2 PostgreSQL authority

Purpose: default enterprise control plane.

Implementation requirements:

- `asyncpg` pool with configurable minimum/maximum, command timeout, statement
  timeout, lock timeout, application name, TLS, and connection health.
- One explicit transaction for checkpoint + run transition + journal + outbox.
- Lease acquisition updates a run/lease row under row lock and increments
  `fencing_token` atomically. Use database time (`clock_timestamp()` or
  equivalent), not worker time.
- Every mutation includes `WHERE fencing_token = $expected` or locks and checks
  the run row inside the same transaction.
- Outbox dispatch uses `FOR UPDATE SKIP LOCKED`, bounded batches, and claim expiry.
- Composite tenant keys and optional PostgreSQL row-level security.
- Separate least-privilege roles for migration, runtime authority, dispatcher,
  projector, and read-only operator access.
- No `CREATE TABLE IF NOT EXISTS` in request startup. Migrations are a deployment
  step and readiness fails on version mismatch.
- Backup/PITR and restore drills are part of the production gate.

Do not use advisory locks as the sole correctness mechanism. Row state and
fencing tokens must survive client disconnects and remain auditable.

### 7.3 MongoDB authority

Purpose: alternative when the consuming platform standardizes on MongoDB and
accepts its operational model.

Implementation requirements:

- Use PyMongo's `AsyncMongoClient`; do not introduce new Motor code.
- Require a replica set or sharded cluster for multi-document transactions.
- Lease document keyed by `(tenant_id, run_id)`; atomic conditional
  `find_one_and_update` with `$inc` fencing token.
- Checkpoint, run, journal, and outbox writes commit in one session transaction.
- Majority write concern and appropriate read concern are configuration defaults.
- TTL indexes clean expired claims but are never part of correctness.
- Shard keys must co-locate a run's transaction records or the adapter must
  explicitly support distributed transaction costs.
- Change streams may drive projections, but the journal remains authoritative.
- Each process/event loop creates its own async client lifecycle correctly.

Standalone MongoDB must fail the enterprise readiness check because it cannot
provide the required multi-document transaction contract.

### 7.4 DuckDB analytics projection

Purpose: offline/local analytics, benchmark history, cost analysis, replay
inspection, and Parquet export.

Implementation requirements:

- Implement `OperationalProjection`, never `RuntimeAuthority`.
- One writer service/process per native DuckDB file.
- Dedicated connection objects; never the module-global connection.
- Batch journal records into `run_fact`, `node_fact`, `cost_fact`,
  `evaluation_fact`, and `effect_fact` tables.
- Store projection cursor and source schema version.
- Support full rebuild and deterministic parity counts against the authority.
- Optional Parquet export/import for long-term analytical storage.

Multi-process native-file writes are not a supported stable authority shape.
Remote/beta concurrency features are out of scope until separately qualified.

### 7.5 Elasticsearch operational projection

Purpose: searchable traces, events, errors, provenance, and operator dashboards.

Implementation requirements:

- Implement `OperationalProjection`, never `RuntimeAuthority`.
- Use the official asynchronous Python client with a compatibility-tested major.
- Timestamped journal records go to versioned data-stream templates.
- Use stable `event_id` with create semantics for idempotent indexing.
- Run snapshots use optimistic concurrency (`if_seq_no`, `if_primary_term`) but
  are still projections, not authority.
- Explicit mappings for identifiers, timestamps, numeric costs/tokens, and
  searchable message fields. Disable uncontrolled dynamic-field growth.
- Index lifecycle/data-stream lifecycle policies define rollover and retention.
- Tenant-aware aliases or routing plus document-level authorization.
- Redact secrets and restricted context before projection.
- Projector retries/dead-letter without blocking DAG execution.
- Full rebuild from authority journal must be automated and tested.

## 8. Factory And Configuration Contract

Introduce one capability-aware factory:

```python
authority = create_runtime_authority(
    backend="postgres",
    dsn=secret_ref,
    tenant_mode="row",
    migration_mode="validate",
)

services = RuntimeServices(
    durability=DurabilityServices(
        authority=authority,
        projections=(elastic_projection, duckdb_projection),
    )
)
```

Factory rules:

- Validate capability role at construction. `backend="elastic"` as authority is
  an immediate configuration error.
- Never default production to in-memory or an unregistered mock.
- `CEMAF_ENV=production` requires an explicit authority backend.
- Development may default to SQLite only when an explicit local database path is
  resolved and printed without secrets.
- DSNs are secret values and must never appear in logs, reprs, errors, snapshots,
  or metrics.
- Backend clients are request-independent resources owned by application
  lifespan, not recreated per DAG node.

Optional dependency groups:

```toml
sqlite = ["aiosqlite>=..."]
postgres = ["asyncpg>=..."]
mongo = ["pymongo>=..."]
duckdb = ["duckdb>=..."]
elastic = ["elasticsearch[async]>=..."]
enterprise-postgres = ["cemaf[postgres,redis,otel,security]"]
```

Do not make an `all` or `enterprise` extra silently install mutually alternative
authority databases. Provide explicit deployment profiles.

## 9. Migration And Compatibility Strategy

### Schema lifecycle

- Versioned, checksum-protected migrations packaged with CEMAF.
- `cemaf durability migrate --backend ...` performs migrations.
- `cemaf durability status` reports current/required versions and destructive
  pending operations.
- Production default is `migration_mode="validate"`; mismatch fails readiness.
- Development can opt into `migration_mode="apply"`.
- Every destructive migration requires expand/backfill/contract phases.
- Mongo indexes and validators, Elasticsearch templates/aliases, and DuckDB
  projection schemas are versioned through the same release manifest.

### File backend to database authority

1. Upgrade file records to the latest serialization version.
2. Stop new claims and allow active leases to drain or expire.
3. Import runs, immutable checkpoints, journal records, and effect receipts.
4. Verify counts, per-run checkpoint hashes, journal sequence continuity, and
   replay equality.
5. Enable database authority in read-only comparison mode.
6. Freeze file authority, import final delta, and switch a generation marker.
7. Keep file state read-only for the rollback window.

### Authority-to-authority migration

Use journal-based shadowing rather than application dual-writes. Dual-writes can
split authority when one backend commits and the other fails.

1. Snapshot/import historical state.
2. Project new committed journal entries into the target.
3. Compare lag, hashes, states, and replay results continuously.
4. Freeze new lease acquisition briefly.
5. Apply delta and advance a deployment-level authority generation.
6. Switch workers and dispatchers.
7. Reject old-generation writers through fencing.

## 10. Security And Multi-Tenancy

Enterprise readiness requires:

- Tenant ID in every key and query; no optional tenant filtering.
- PostgreSQL RLS or equivalent enforcement tests where enabled.
- TLS with certificate verification for all network backends.
- Secret-manager references rather than plaintext DSNs in configuration files.
- Separate credentials and least privileges for migrator, runtime, dispatcher,
  projector, and read-only operators.
- Encryption at rest delegated to the managed database/storage layer and
  documented per deployment.
- Payload classification before persistence and projection. Elasticsearch and
  DuckDB receive only fields permitted for their security tier.
- Maximum checkpoint/event/effect sizes with rejection metrics.
- Audit of lease acquisition, expiry, takeover, stale writes, migrations,
  retention deletion, and operator replay.
- Retention and legal-hold controls that distinguish authoritative journal,
  operational projection, and ephemeral traces.
- Backup encryption and periodic restore tests into an isolated environment.

## 11. Observability And Operations

Required metrics:

- lease acquire/conflict/renew/expiry/takeover/stale-write totals;
- lease renewal lag and remaining TTL;
- checkpoint commit latency, bytes, versions, and failures;
- authority transaction latency, rollback count, serialization/deadlock retries;
- journal append latency and sequence conflicts;
- outbox pending count, oldest age, delivery latency, retries, and dead letters;
- projection lag by backend and tenant-independent aggregate;
- connection-pool usage/wait time;
- migration version drift;
- backup age and last successful restore drill.

Required health surfaces:

- **Liveness**: process/event loop is alive; does not require the database.
- **Readiness**: authority reachable, schema current, clock usable, and a bounded
  read/write transaction succeeds.
- **Degraded**: projections unavailable or lagging while authority remains safe.
- **Not ready**: authority unavailable, schema mismatch, or lease renewal cannot
  maintain its safety margin.

Proposed default lease policy:

- TTL is configuration with a conservative production default.
- Renew before one-third of TTL remains.
- Stop dispatching new work when renewal fails.
- Reject the node commit if the lease cannot be proven current.
- RTO lower bound after hard process loss is lease expiry plus claim/restore time.

SLO values must be deployment-configured. The framework ships measurement and
conformance gates, not a universal latency promise across local SQLite and
cross-region databases.

## 12. Verification Program

### Shared authority contract suite

Every SQLite, PostgreSQL, and MongoDB adapter runs the same black-box tests:

- create/load/complete run;
- immutable checkpoint versioning and hash verification;
- resume after process death;
- 100+ simultaneous lease claims produce exactly one winner;
- heartbeat renewal prevents takeover;
- expired lease permits takeover with a higher fence;
- stale release/checkpoint/journal/outbox mutations fail;
- checkpoint + journal + outbox atomic rollback under injected failure;
- duplicate event/effect IDs are idempotent;
- conflicting idempotency payload fails closed;
- outbox claim expiry and redelivery;
- dead-letter after bounded attempts;
- tenant A cannot read/write/claim tenant B;
- schema-version rejection and migration;
- close/cleanup is idempotent.

### Destructive and concurrency verification

- `SIGKILL` at every commit phase, including before/after external delivery;
- database restart/failover during lease renewal and commit;
- network partition and connection-pool exhaustion;
- disk-full and read-only filesystem for SQLite;
- clock skew between workers (authority clock must win);
- duplicate dispatchers and duplicate projectors;
- stale worker resumes after a newer holder commits;
- migration interruption and rollback;
- corrupted checkpoint payload/hash mismatch;
- large checkpoint and event storms;
- backup restore followed by deterministic replay comparison.

The existing `benchmarks/red_team_durable_companion.py` becomes the minimum
local profile. Database profiles must run in disposable containers in CI and in
scheduled soak jobs. “Unit tests passed” is not sufficient evidence for this
layer.

### Projection contract suite

DuckDB and Elasticsearch must prove:

- idempotent application of repeated journal batches;
- cursor persistence and restart;
- out-of-order event rejection or deterministic buffering;
- full rebuild parity with authority counts/hashes;
- projection outage does not fail authority commits;
- security filtering/redaction;
- schema/template upgrade and alias cutover;
- bounded lag under declared load.

## 13. Implementation Sequence And Merge Gates

### Phase 0 — Freeze contracts and terminology

Deliverables:

- `durability` models/protocols/capabilities package;
- serialization version and canonical hash fixtures;
- shared authority contract-test kit;
- update SPEC-04 and architecture map to reconcile `TaskRepository` and
  `RuntimeAuthority` rather than creating competing lease concepts;
- architecture decision records for backend roles and transaction boundary.

Merge gate: protocol review proves all non-negotiable invariants are expressible.

### Phase 1 — SQLite reference authority

Deliverables:

- SQLite schema/migrations;
- authority, lease renewal, immutable checkpoints, journal, and outbox;
- outbox dispatcher with a fake idempotent destination;
- `RuntimeServices.durability` executor wiring;
- import tool from current file backend;
- complete destructive local test suite.

Merge gate: zero broken invariants across repeated process-kill, race, rollback,
and replay tests; no hidden file-only path in the example.

### Phase 2 — PostgreSQL enterprise authority

Deliverables:

- PostgreSQL adapter and explicit migrations;
- transaction/fencing/outbox implementation;
- RLS/tenant tests and least-privilege SQL roles;
- container integration tests, failover tests, pool/timeout metrics;
- backup/restore runbook;
- SQLite/PostgreSQL parity report.

Merge gate: shared contract suite, destructive suite, migration rehearsal, and
restore/replay proof all pass. PostgreSQL becomes the documented production
default only after this gate.

### Phase 3 — Production outbox destinations

Deliverables:

- destination adapter protocol with idempotency capability declaration;
- HTTP adapter supporting `Idempotency-Key`;
- transactional receiver example;
- retry/backoff/dead-letter tooling and operator commands;
- effect reconciliation and replay procedures.

Merge gate: crash between delivery and acknowledgement cannot create a second
effect against the conforming test receiver.

### Phase 4 — MongoDB authority

Deliverables:

- PyMongo Async adapter, migrations/index validators, replica-set guard;
- transaction, lease/fence, checkpoint, journal, and outbox implementations;
- change-stream projector option;
- replica-set failover and transaction retry testing;
- SQLite/PostgreSQL/Mongo parity report.

Merge gate: same authority contract and destructive tests; standalone Mongo is
rejected for enterprise mode.

### Phase 5 — DuckDB projection

Deliverables:

- analytics schema/projector and cursor;
- batch ingestion, rebuild, parity, Parquet export;
- cost/eval/recovery analysis examples;
- single-writer enforcement.

Merge gate: repeated rebuild produces identical aggregate results and never
participates in runtime authority.

### Phase 6 — Elasticsearch projection

Deliverables:

- versioned templates/data streams, lifecycle policy examples;
- asynchronous projector, cursor, retries/dead-letter;
- trace/search/operator queries and dashboards;
- rebuild and alias-cutover tooling;
- redaction and tenant authorization tests.

Merge gate: projection can be destroyed/rebuilt without affecting execution;
outage and backpressure do not block authority commits.

### Phase 7 — Enterprise graduation

Deliverables:

- sustained multi-worker soak tests;
- chaos/failover evidence for the supported production profile;
- upgrade/downgrade and authority-migration rehearsal;
- security review and dependency/SBOM scanning;
- published SLO template, dashboards, alerts, backup/restore, and incident runbooks;
- compatibility policy and supported-version matrix.

Merge/release gate: every item in the definition of done below has direct,
current evidence. Until then, CEMAF remains alpha for enterprise durability.

## 14. Pull-Request Decomposition

Keep reviews bounded and preserve bisectability:

1. ADRs + reconciled SPEC-04 contract.
2. Durability models, capability manifest, serialization fixtures.
3. Authority/UoW protocols + reusable contract tests.
4. RuntimeServices and executor integration behind a feature flag.
5. SQLite migrations and lease/checkpoint implementation.
6. SQLite journal/outbox + dispatcher.
7. File-to-SQLite importer and example conversion.
8. PostgreSQL migrations and connection lifecycle.
9. PostgreSQL lease/fencing/UoW.
10. PostgreSQL outbox and operations tooling.
11. PostgreSQL destructive/container tests and runbook.
12. Destination idempotency adapters.
13. MongoDB authority series.
14. DuckDB projection series.
15. Elasticsearch projection series.
16. Enterprise graduation evidence.

No PR should add a backend implementation before the shared contract tests it
must satisfy exist.

## 15. Risk Register

| Risk | Consequence | Required mitigation |
|---|---|---|
| Separate stores without UoW | Checkpoint committed but effect/journal lost | Mandatory authority transaction |
| Lease expires during long node | Two workers act concurrently | Renewal heartbeat + pre-commit fence check |
| Destination ignores idempotency | Duplicate external effect | Capability declaration, outbox, conforming receiver, reconciliation |
| Worker clock skew | Premature/late takeover | Database clock for lease predicates |
| Lazy schema creation | Startup races and surprise DDL | Explicit checksum migrations + readiness validation |
| Tenant filter omitted | Cross-tenant breach | Composite keys, RLS/validator tests, API requires tenant |
| Projection becomes dependency | Search outage halts runs | Async journal/outbox projection only |
| DuckDB multi-process writer | Conflicts/corruption risk | Single projector writer; never authority |
| Elasticsearch mapping explosion | Cluster instability | Explicit mappings and bounded metadata |
| Mongo standalone deployment | No atomic multi-collection UoW | Fail enterprise readiness |
| PostgreSQL pool exhaustion | Lease renewal failure | Reserved capacity/priority, pool metrics, load shedding |
| Migration dual-write split | Two sources of truth | Journal shadowing + fenced cutover generation |
| Payload growth | DB/latency failure | Size limits, compression policy, later content-addressed blobs |

## 16. Definition Of Done

CEMAF may describe this layer as enterprise-production-ready only when all are
true:

- [ ] Runtime authority/UoW protocols are public, runtime-checkable, documented,
      and used by `create_executor` through `RuntimeServices`.
- [ ] SQLite reference authority passes every shared and destructive test.
- [ ] PostgreSQL authority passes every shared/destructive test, tenant test,
      migration rehearsal, failover test, and backup restore/replay drill.
- [ ] Lease heartbeat, monotonic fencing, and stale-write rejection are proven
      across processes and hosts.
- [ ] Checkpoint, transition, journal, and outbox atomicity is fault-injection tested.
- [ ] At least one real destination adapter proves crash-safe effective-once
      delivery using idempotency.
- [ ] MongoDB, if advertised as authoritative, passes the identical suite on a
      supported replica-set/sharded topology.
- [ ] DuckDB and Elasticsearch are capability-rejected as runtime authorities.
- [ ] Both projections can rebuild from the authority journal with parity.
- [ ] Schema migrations, upgrades, rollback/cutover, and file import are tested.
- [ ] Production configuration fails closed on missing authority, schema drift,
      insecure TLS, or insufficient backend capabilities.
- [ ] Metrics, alerts, dashboards, retention, backup/restore, and incident
      runbooks are shipped and exercised.
- [ ] Security review covers tenant isolation, secret handling, encryption,
      payload classification, and operator access.
- [ ] Supported backend/server/client versions and compatibility policy are published.
- [ ] No unresolved P0/P1 durability defect remains.

## 17. Authoritative References

- [SQLite isolation and single-writer/WAL behavior](https://www.sqlite.org/isolation.html)
- [SQLite atomic commit behavior](https://www.sqlite.org/atomiccommit.html)
- [PostgreSQL row locking and `SKIP LOCKED`](https://www.postgresql.org/docs/current/sql-select.html)
- [PostgreSQL explicit locking](https://www.postgresql.org/docs/current/explicit-locking.html)
- [MongoDB multi-document transactions](https://www.mongodb.com/docs/manual/data-modeling/enforce-consistency/transactions/)
- [PyMongo Async and Motor migration guidance](https://www.mongodb.com/docs/languages/python/pymongo-driver/current/reference/migration/)
- [DuckDB concurrency model](https://duckdb.org/docs/current/connect/concurrency)
- [DuckDB Python connection guidance](https://duckdb.org/docs/stable/clients/python/overview)
- [Elasticsearch optimistic concurrency control](https://www.elastic.co/docs/reference/elasticsearch/rest-apis/optimistic-concurrency-control)
- [Elasticsearch append-oriented data streams](https://www.elastic.co/docs/manage-data/data-store/data-streams)

These references justify backend role assignments; CEMAF's contract tests remain
the acceptance authority for its own implementations.

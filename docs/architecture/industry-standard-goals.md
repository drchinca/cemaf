# CEMAF Industry-Standard Goals

Status: product and architecture target; not a maturity claim
Scope: huge-context, long-running, autonomous, data-intensive tasks
Audience: maintainers, adopters, adapter authors, and benchmark reviewers

## North Star

CEMAF aims to be the execution and context substrate for autonomous,
long-running, data-intensive, multi-agent systems.

“Industry standard” is an earned claim. It depends on portable contracts,
production behavior, published limits, and reproducible destructive evidence.
The number of integrations is not the measure.

## Product Pillars

### 1. Durable execution

Disposable workers, automatic takeover, monotonic fencing, checkpointed
progress, replay, and durable recovery state.

Required proof:

- kill workers at every execution/commit boundary;
- automatically discover and resume abandoned work;
- reject every stale-worker mutation;
- preserve task, checkpoint, journal, and effect-intent atomicity;
- replay committed lineage after all original worker objects are gone.

### 2. Huge-context management

Versioned context manifests, bounded snapshots, compaction, retrieval,
provenance, and prompt projection under explicit token/cost budgets.

Required proof:

- context size grows beyond any single model window without losing lineage;
- deterministic compaction preserves declared facts and provenance;
- each node receives only its relevant bounded projection;
- replay identifies the exact manifest, sources, compiler, and policy versions;
- context quality and retrieval degradation are measured over long runs.

### 3. Big-data separation

Checkpoints contain execution state and content-addressed references, not huge
datasets or unbounded artifacts. Large payloads remain in object stores, tables,
indexes, warehouses, or application-owned artifact systems.

Required proof:

- checkpoint size limits fail closed;
- referenced artifacts have immutable identity, checksum, schema, and access
  metadata;
- garbage collection cannot delete data reachable from a live task;
- a task referencing terabyte-scale data resumes without loading that dataset
  into the authority database or model prompt;
- missing or unauthorized artifacts produce explicit, replayable failures.

### 4. Distributed scheduling

Partitioning, backpressure, priorities, tenant quotas, concurrency controls,
data locality, retry eligibility, poison-task handling, and fair task claiming.

Required proof:

- multiple workers claim work without duplicate authoritative commits;
- high-volume tenants cannot starve other tenants;
- overload produces bounded queues and load shedding rather than collapse;
- locality hints improve placement without becoming correctness authority;
- retries respect budgets, backoff, priority, and dead-letter policy.

### 5. Deterministic auditability

Every material decision, context mutation, recovery, citation, tool effect,
policy result, and state transition is causally linked and queryable.

Required proof:

- task, attempt, node-attempt, parent, correlation, and effect identities join
  without inference;
- audit records are append-only and ordered per declared scope;
- replay parity distinguishes deterministic state reconstruction from
  nondeterministic model/tool re-execution;
- redaction and retention remain visible as audited transformations;
- operator queries work without reading process-local logs.

### 6. Safe autonomy

Budgets, authorization, moderation, validation, evaluation, retry limits,
recovery bounds, human intervention, cancellation, and fail-closed readiness.

Required proof:

- unauthorized work cannot reach execution or retrieval;
- budget exhaustion halts before another costly dispatch;
- recovery cannot recurse or retry without bound;
- human pause/resume survives process loss and uses fenced authority;
- unsafe effect capabilities prevent strict-production startup or dispatch;
- policy decisions and overrides are durable and attributable.

### 7. Backend portability

CEMAF defines capability protocols and conformance tests for storage roles.
Specific engines are optional adapters, not the architecture.

Candidate role examples:

| Role | Possible adapters | Framework requirement |
|---|---|---|
| Runtime authority | PostgreSQL, MongoDB, another transactional store | Lease, fencing, atomic state/checkpoint/journal/outbox contract |
| Local semantic reference | SQLite or another embedded transactional store | Same observable authority semantics within declared topology |
| Large-object/artifact plane | S3-compatible storage, cloud object stores, application artifact systems | Immutable references, integrity, authorization, lifecycle |
| Retrieval projection | Elasticsearch, vector databases, application indexes | Rebuildable, bounded-lag, security-filtered retrieval |
| Analytics projection | DuckDB, warehouses, lakehouse engines | Rebuildable analysis; never runtime authority |
| Wake-up transport | SQS, Kafka, Redis Streams, database polling, application queues | Notification only; authority fencing decides ownership |

No deployment needs every role to use a separate product, and no CEMAF release
must ship every candidate adapter. A single engine may satisfy multiple roles
when its declared guarantees and scale are sufficient.

Every advertised adapter graduates independently:

1. **Experimental** — API may change; correctness suite incomplete.
2. **Conformant** — shared semantic contract passes in its supported topology.
3. **Production-validated** — destructive, scale, upgrade, security, backup,
   restore, and operational evidence passes for published versions.

CEMAF may claim portability only when at least two materially different
implementations pass the same core semantic suite. It may claim a production
profile when at least one complete, documented combination passes every
applicable pillar; this does not require all candidate adapters.

### 8. Evidence

Claims must be reproducible and tied to a versioned environment, dataset,
configuration, fault schedule, and expected invariant.

The evidence program includes:

- multi-day uninterrupted and failure-injected runs;
- terabyte-scale **referenced** datasets without terabyte checkpoints;
- hard worker kills and stale-worker continuation;
- authority failover and connection-partition tests;
- checkpoint/journal/replay parity;
- projection destruction and rebuild;
- tenant isolation and adversarial authorization tests;
- overload, backpressure, fairness, and quota tests;
- prompt/context poisoning and unsafe-effect tests;
- upgrade, rollback, backup, and restore rehearsals.

Throughput numbers never substitute for correctness counts. A green benchmark
must publish what it did not test.

## Architectural Consequences

The framework is organized around roles and guarantees:

```text
application / agents / DAGs
             │
             ▼
     CEMAF execution + context contracts
             │
     ┌───────┼────────┬──────────┬─────────┐
     ▼       ▼        ▼          ▼         ▼
 authority artifacts retrieval analytics wake-ups
     │       │        │          │         │
     └──── optional capability-conformant adapters ────┘
```

- `RuntimeServices` injects behavior-oriented CEMAF protocols.
- Adapter factories and deployment composition choose products at the edge.
- The authority stores bounded control state; context manifests point to large
  immutable content.
- Retrieval and analytics are rebuildable projections.
- Queues wake workers; leases and fencing authorize commits.
- Every optional capability reports readiness and degradation explicitly.

## What CEMAF Must Build First

Priority follows correctness dependencies, not adapter count:

1. Freeze task/attempt/context-manifest identities and semantic contracts.
2. Build the destructive, backend-neutral conformance harness.
3. Implement one local reference profile for fast exhaustive testing.
4. Implement and graduate one complete production profile selected by demand
   and operational fit.
5. Prove huge-context artifact references, compaction, retrieval, and bounded
   prompt projection in long-running tasks.
6. Prove scheduling, safety, audit, and multi-day scale evidence end to end.
7. Add further adapters only when users need them and they can pass the same
   gates without weakening the core contract.

## Claim Gate

CEMAF cannot call itself an industry standard merely because these protocols or
adapters exist. The claim becomes supportable only after every pillar has:

- a public contract and documented limits;
- at least one complete production implementation path;
- automated conformance and destructive tests;
- published, reproducible evidence;
- operational and security review;
- no unresolved correctness defect that invalidates the claim.

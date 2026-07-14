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

## Current Truth

As of 2026-07-14, CEMAF has a strong local file-backed proof for worker loss,
fenced replacement, atomic file writes, native `RuntimeServices` checkpoint
resume, replay, and an idempotent local effect. It also has opt-in live boundary
tests for local/cloud LLMs and PostgreSQL memory storage.
It does **not** yet have a production-validated durable authority, automatic
abandoned-work discovery, one atomic checkpoint/journal/outbox transaction,
large-artifact manifests, multi-day evidence, or a graduated production
profile. The target below must not be presented as shipped behavior.

The executable claim-by-claim record is the
[Capability Evidence Ledger](../production-evidence.md).

The normative implementation contract is
[SPEC-17: Production-Grade Autonomous Context Substrate](../specs/SPEC-17-autonomous-context-substrate.md).
This document is the product-level summary; SPEC-17 owns stable invariant IDs,
interfaces, acceptance scenarios, and graduation rules.

## Canonical Terms

| Term | Meaning |
|---|---|
| Task | Durable logical objective that survives every worker and attempt |
| Attempt | One lease-bound worker execution of a task |
| Node attempt | One execution/recovery try for a DAG node within an attempt |
| Context universe | All durable facts, artifacts, decisions, and lineage reachable by a task |
| Working context | The bounded, policy-filtered projection compiled for one node/model call |
| Context manifest | Versioned, content-addressed graph of context and artifact references |
| Checkpoint | Bounded control state sufficient to resume; never the bulk-data plane |
| Runtime authority | Store that decides ownership and atomically commits authoritative state |
| Projection | Rebuildable retrieval, search, analytics, or operator read model |
| Production profile | Versioned combination of adapters, topology, limits, policies, and evidence |
| Evidence bundle | Reproducible records proving named invariants for one code/profile version |

Three distinctions are non-negotiable:

1. A huge **context universe** does not imply a huge prompt.
2. CEMAF provides a fenced authoritative commit, not exactly-once execution of
   arbitrary code.
3. A conformant adapter is not automatically a production-validated deployment
   profile.

## Pillar Contract Map

| ID | Pillar | Core invariant | Primary evidence |
|---|---|---|---|
| DE | Durable execution | A dead or stale worker cannot lose or corrupt committed progress | Kill matrix, takeover races, atomicity faults |
| HC | Huge context | Every node receives a bounded projection with complete manifest lineage | Compaction/retrieval parity and long-run context growth |
| BD | Big-data separation | Bulk payloads never become authority rows or implicit prompts | Size-limit, artifact-integrity, and large-reference tests |
| DS | Distributed scheduling | Eligible work is claimed fairly under declared limits without duplicate commits | Overload, quota, starvation, and locality tests |
| DA | Deterministic auditability | Every material commit is causally reconstructable from durable records | Identity joins, state replay, retention/redaction audits |
| SA | Safe autonomy | Policy and resource bounds remain enforceable across crashes and recovery | Authorization, budget, recursion, HITL, and effect tests |
| BP | Backend portability | Products may change without changing declared semantics | Shared conformance suite across supported adapters |
| EV | Evidence | Every maturity claim resolves to reproducible current proof | Signed manifest, raw results, environment, fault schedule |

## Product Pillars

### 1. Durable execution

Disposable workers, automatic takeover, monotonic fencing, checkpointed
progress, replay, and durable recovery state.

Required proof:

- **DE-1:** kill workers at every execution/commit boundary;
- **DE-2:** automatically discover and resume abandoned work;
- **DE-3:** reject every stale-worker mutation;
- **DE-4:** preserve task, checkpoint, journal, and effect-intent atomicity;
- **DE-5:** replay committed lineage after all original worker objects are gone.

### 2. Huge-context management

Versioned context manifests, bounded snapshots, compaction, retrieval,
provenance, and prompt projection under explicit token/cost budgets.

Required proof:

- **HC-1:** context size grows beyond any single model window without losing lineage;
- **HC-2:** deterministic compaction preserves declared facts and provenance;
- **HC-3:** each node receives only its relevant bounded projection;
- **HC-4:** replay identifies the exact manifest, sources, compiler, and policy versions;
- **HC-5:** context quality and retrieval degradation are measured over long runs.

### 3. Big-data separation

Checkpoints contain execution state and content-addressed references, not huge
datasets or unbounded artifacts. Large payloads remain in object stores, tables,
indexes, warehouses, or application-owned artifact systems.

Required proof:

- **BD-1:** checkpoint size limits fail closed;
- **BD-2:** referenced artifacts have immutable identity, checksum, schema, and access
  metadata;
- **BD-3:** garbage collection cannot delete data reachable from a live task;
- **BD-4:** a task referencing terabyte-scale data resumes without loading that dataset
  into the authority database or model prompt;
- **BD-5:** missing or unauthorized artifacts produce explicit, replayable failures.

### 4. Distributed scheduling

Partitioning, backpressure, priorities, tenant quotas, concurrency controls,
data locality, retry eligibility, poison-task handling, and fair task claiming.

Required proof:

- **DS-1:** multiple workers claim work without duplicate authoritative commits;
- **DS-2:** high-volume tenants cannot starve other tenants;
- **DS-3:** overload produces bounded queues and load shedding rather than collapse;
- **DS-4:** locality hints improve placement without becoming correctness authority;
- **DS-5:** retries respect budgets, backoff, priority, and dead-letter policy.

### 5. Deterministic auditability

Every material decision, context mutation, recovery, citation, tool effect,
policy result, and state transition is causally linked and queryable.

Required proof:

- **DA-1:** task, attempt, node-attempt, parent, correlation, and effect identities join
  without inference;
- **DA-2:** audit records are append-only and ordered per declared scope;
- **DA-3:** replay parity distinguishes deterministic state reconstruction from
  nondeterministic model/tool re-execution;
- **DA-4:** redaction and retention remain visible as audited transformations;
- **DA-5:** operator queries work without reading process-local logs.

### 6. Safe autonomy

Budgets, authorization, moderation, validation, evaluation, retry limits,
recovery bounds, human intervention, cancellation, and fail-closed readiness.

Required proof:

- **SA-1:** unauthorized work cannot reach execution or retrieval;
- **SA-2:** budget exhaustion halts before another costly dispatch;
- **SA-3:** recovery cannot recurse or retry without bound;
- **SA-4:** human pause/resume survives process loss and uses fenced authority;
- **SA-5:** unsafe effect capabilities prevent strict-production startup or dispatch;
- **SA-6:** policy decisions and overrides are durable and attributable.

### 7. Backend portability

CEMAF defines capability protocols and conformance tests for storage roles.
Specific engines are optional adapters, not the architecture.

Required proof:

- **BP-1:** composition rejects adapters that lack a required role capability;
- **BP-2:** every conformant authority passes the same observable semantic suite;
- **BP-3:** at least two materially different implementations prove portability;
- **BP-4:** every projection can be destroyed and rebuilt without authority loss;
- **BP-5:** adapter removal or outage follows its declared degradation behavior
  without silently weakening a core invariant.

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

#### Production profile contract

A production profile is a reviewable artifact, not a README recipe. It must
declare:

| Field | Required disclosure |
|---|---|
| Identity | Profile ID/version, CEMAF version/commit, schema generation |
| Topology | Worker count/range, authority topology, regions/zones, failure domain |
| Adapters | Package and server versions, maturity level, capability manifest |
| Guarantees | Transaction, fencing, delivery, replay, consistency, and degradation semantics |
| Limits | Checkpoint/artifact size, concurrency, queue depth, context/token, retry, and retention bounds |
| Security | Tenant isolation, credentials, encryption, redaction, authorization mode |
| Operations | Migrations, readiness, backup/restore, drain, failover, rollback, alerts |
| Evidence | Evidence-bundle IDs covering every claimed pillar and supported topology |

Composition fails closed when a required capability is absent. An optional
capability may degrade only when the profile declares the degraded behavior,
readiness reports it, and no core invariant becomes weaker.

### 8. Evidence

Claims must be reproducible and tied to a versioned environment, dataset,
configuration, fault schedule, and expected invariant.

Required proof:

- **EV-1:** every verdict maps to named invariant IDs and raw results;
- **EV-2:** the environment, versions, workload, seed, and fault schedule are reproducible;
- **EV-3:** exclusions, incomplete samples, and untested boundaries are explicit;
- **EV-4:** relevant code/protocol/adapter/verifier changes invalidate stale evidence;
- **EV-5:** an independent rerun can reproduce the verdict within declared tolerances.

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

### Evidence bundle contract

Every published result must include:

- unique evidence ID and the invariant IDs it proves;
- CEMAF commit, dirty-tree status, adapter/server/client versions, and migration
  checksums;
- topology, resource limits, dataset/manifest hashes, seed, workload generator,
  and configuration with secrets redacted;
- exact fault schedule and expected outcome for every injected failure;
- raw machine-readable events/results plus a derived human report;
- start/end time, duration, incomplete samples, retries, and excluded data;
- the verifier version and a command that reproduces the verdict;
- explicit scope and limitations.

Evidence expires when a relevant protocol, migration, adapter major version,
fault harness, or verifier changes. CI may reuse evidence only when the bundle's
declared dependency hashes are unchanged.

### Benchmark lanes

| Lane | Purpose | Required cadence |
|---|---|---|
| Contract | Fast semantic parity and invariant properties | Every relevant PR |
| Destructive | Process kill, partition, disk/full, stale writer, commit ambiguity | Every adapter release; scheduled CI |
| Security | Tenant isolation, authorization, secret/redaction, poisoning | Every security-relevant release |
| Scale | Backpressure, fairness, context/artifact cardinality, projection lag | Release candidate and material scheduler changes |
| Endurance | Multi-day execution, leak/growth detection, lease churn, recovery | Production-profile graduation and scheduled runs |
| Operations | Upgrade, rollback, backup/restore, failover, rebuild | Production-profile graduation and supported-version changes |

Each lane publishes correctness first, then latency/throughput/cost. A lane is
red if an invariant breaks, even when aggregate availability or throughput
looks healthy.

Terabyte-scale evidence must distinguish **logical referenced size** from bytes
physically scanned during the benchmark. CEMAF must prove both metadata/control
scalability and at least one representative physical data path; it must not
inflate a manifest and call that a terabyte-processing result.

### Claim scopes

Claims are made at the narrowest proven scope:

1. **Core-contract conformant** — framework semantics pass without implying a
   production backend.
2. **Adapter conformant** — one adapter/version/topology passes its shared and
   adapter-specific suites.
3. **Production-profile validated** — one complete deployment profile passes
   all applicable pillar, security, operations, scale, and endurance gates.
4. **Industry-standard claim supportable** — multiple independent production
   adopters/profiles plus portable contracts and current public evidence cover
   every pillar.

Passing a lower scope must never be worded as passing a higher one.

## Explicit Non-Goals

- Shipping or requiring every suggested database, queue, search engine, vector
  store, object store, or warehouse.
- Treating one giant prompt, database row, or serialized checkpoint as “huge
  context.”
- Universal exactly-once execution or exactly-once arbitrary external effects.
- Deterministic re-generation from nondeterministic models; CEMAF guarantees
  deterministic state/audit replay within its declared replay mode.
- A supervisor agent that becomes durable authority or a mandatory hot-path
  decision maker.
- Hiding deployment-specific SLOs behind framework-wide marketing numbers.

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
4. Prove huge-context artifact references, compaction, retrieval, and bounded
   prompt projection in long-running tasks.
5. Prove scheduling, safety, audit, and worker-loss behavior together end to end.
6. Select, implement, and graduate one complete production profile based on
   adopter demand and operational fit, including multi-day evidence.
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

The public scoreboard records each pillar as one of:

| State | Meaning |
|---|---|
| Specified | Contract and limits exist; implementation/evidence incomplete |
| Implemented | Code exists; destructive proof incomplete |
| Locally proven | Reference profile passes named evidence; not production validated |
| Profile validated | A complete production profile passes current evidence gates |
| Portable | At least two materially different implementations preserve the semantics |

The overall claim is bounded by the least-proven mandatory pillar. Missing
evidence is “not proven,” never an implicit pass. Any known invariant failure
immediately downgrades every claim that depends on it until new evidence closes
the defect.

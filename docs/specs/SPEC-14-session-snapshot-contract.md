# SPEC-14 — `cemaf.session.v1` Snapshot Contract

> Status: Draft · Last-Reviewed: 2026-06-25 · Depends on: SPEC-00
> Owns: a versioned, public, read-only operator snapshot of a CEMAF run, generated
> deterministically from existing runtime objects. Realizes P0 of the ECC enhancement
> roadmap (`docs/analysis/ECC_ENHANCEMENT_RESEARCH.md`).

## 1. Context

CEMAF has rich internal runtime artifacts (`RunRecord`, `ExecutionResult`, `NodeResult`,
`BudgetGuard`, `GlassBoxReport`) but **no single public run snapshot**. Downstream code drifts
toward internal coupling — `cemaf-service` exposes an API-local run shape instead of core state.

This spec adds a versioned `cemaf.session.v1` snapshot: a frozen, JSON-serializable projection
of a run's state, workers (DAG nodes), context pressure, risk, and aggregates, built by pure
adapters from `RunRecord` / `ExecutionResult`. It is **read-only** and changes **no execution
behavior**. It is the stable target every later operator-plane surface (CLI, service, MCP,
benchmarks) projects from.

Contract discipline (ported from ECC's session-adapter rule): required top-level fields are
validated; unknown *optional nested* fields are tolerated; a new *top-level* field requires a
schema-version bump. Absent optional services are represented as `"absent"`, never errors.

## 2. Interface Contract (MDE)

`cemaf.observability.snapshot` — frozen Pydantic models:

```python
SCHEMA_VERSION = "cemaf.session.v1"

class SnapshotRunState(StrEnum):
    PENDING; RUNNING; BLOCKED; PAUSED; COMPLETED; FAILED; CANCELLED; STOPPED; UNKNOWN

class SnapshotHealth(StrEnum):
    HEALTHY; DEGRADED; STALE; FAILED; UNKNOWN

class ServicePresence(StrEnum):
    ENABLED; ABSENT

class WorkerSnapshot(BaseModel):      # one per DAG node
    id: str; kind: str; state: SnapshotRunState; health: SnapshotHealth
    intent: WorkerIntent              # objective, input_keys, output_keys
    duration_ms: float; error: str | None
    metadata: dict[str, Any]          # unknown nested fields tolerated

class ContextPressure(BaseModel):
    patch_count: int; input_tokens: int; total_tokens_budget: int | None
    pressure: str                     # normal | elevated | high | unknown

class RiskSummary(BaseModel):
    budget: str; quality: str; moderation: str; collision: str; governance: str

class RuntimeSummary(BaseModel):
    profile: str; services: dict[str, ServicePresence]

class Aggregates(BaseModel):
    worker_count: int; states: dict[str,int]; healths: dict[str,int]
    tool_calls: int; llm_calls: int; total_cost_usd: float; total_tokens: int

class SessionSnapshot(BaseModel):
    schema_version: Literal["cemaf.session.v1"]
    adapter_id: str
    run: RunSummary                   # id, state, dag_name, started_at, ended_at
    workers: tuple[WorkerSnapshot, ...]
    runtime: RuntimeSummary
    context: ContextPressure
    risk: RiskSummary
    aggregates: Aggregates
    def to_json(self) -> str: ...     # stable key order
    @classmethod
    def json_schema(cls) -> dict: ... # exported JSON Schema

# Adapters — pure, deterministic:
def snapshot_from_run_record(record, *, services_present=(), profile="standard", adapter_id="cemaf-dag") -> SessionSnapshot
def snapshot_from_execution_result(result, *, ...) -> SessionSnapshot
```

State mapping: `RunStatus` → `SnapshotRunState` (pending/running/completed/failed/cancelled
direct; unknown others → UNKNOWN). `HealthStatus` → `SnapshotHealth` (degraded→DEGRADED,
unhealthy→FAILED, + STALE/UNKNOWN at adapter discretion).

## 3. Invariants (DbC)

1. `schema_version SHALL equal "cemaf.session.v1"` and a model with any other top-level
   schema_version SHALL be rejected at validation.
2. `WHEN the same RunRecord is converted twice, THE resulting JSON SHALL be byte-identical`
   except for fields whose value came from the input (timestamps are passed through, not generated).
3. `Unknown nested keys placed in a worker's metadata SHALL survive a round-trip` (parse→serialize).
4. `WHEN an optional service is not present, THE runtime.services entry SHALL be "absent"` (not omitted, not an error).
5. `aggregates.states and aggregates.healths SHALL sum to worker_count.`
6. `THE adapter SHALL NOT mutate the input RunRecord/ExecutionResult` (read-only).
7. `total_cost_usd and total_tokens in aggregates SHALL equal the source RunRecord's totals.`

Budget: 7 invariants.

## 4. Acceptance Criteria (BDD)

```gherkin
Feature: cemaf.session.v1 snapshot

  Scenario: Deterministic conversion
    Given a RunRecord
    When snapshot_from_run_record is called twice
    Then the two to_json() outputs are byte-identical

  Scenario: Unknown nested metadata survives
    Given a worker snapshot whose metadata has an unrecognized key
    When the snapshot is serialized and re-parsed
    Then the unrecognized key is still present

  Scenario: Invalid top-level schema version rejected
    Given a snapshot dict with schema_version "cemaf.session.v2"
    When it is validated
    Then validation raises

  Scenario: Absent service shown, not errored
    Given a RunRecord built with no budget_guard present
    When the snapshot is produced with services_present excluding "budget_guard"
    Then runtime.services["budget_guard"] == "absent"

  Scenario: Aggregates are consistent
    Given a RunRecord whose execution produced N node results
    When the snapshot is produced
    Then aggregates.worker_count == N and the state counts sum to N

  Scenario: Adapter does not mutate input
    Given a RunRecord
    When the snapshot is produced
    Then the RunRecord's fields are unchanged
```

Budget: 6 scenarios.

## 5. Out of Scope

- Service endpoints, CLI, MCP resources (later roadmap PRs — P1).
- Live event-stream snapshots (start from recorded objects; streaming later).
- Capability/runtime-policy/improvement contracts (P2+).
- Any executor behavior change.

## 6. Dependencies

- `RunRecord` (`observability/run_logger.py`), `ExecutionResult`/`NodeResult`
  (`orchestration/results.py`), `RunStatus` (`core/enums.py`), `HealthStatus`
  (`observability/health.py`). No new third-party deps.

## 7. Correctness Properties

### Property 1: Determinism
*For any* RunRecord with fixed field values, repeated conversion yields byte-identical JSON.
**Validates: §3 Inv 2, §4 "Deterministic conversion".**

### Property 2: Schema stability
*For any* snapshot, required top-level fields are present and a foreign top-level
schema_version is rejected; unknown nested metadata is preserved.
**Validates: §3 Inv 1/3, §4 "Unknown nested metadata", "Invalid top-level schema version".**

### Property 3: Read-only fidelity
*For any* input, the adapter mutates nothing and the aggregates equal the source totals.
**Validates: §3 Inv 6/7, §4 "Adapter does not mutate input".**

Budget: 3 properties.

## 8. Eval Criteria

Not applicable — pure deterministic projection. §3 invariants are the enforcement.

## 9. Observability Contract

This spec *is* an operator surface; it emits nothing itself. The committed golden JSON fixture
`tests/observability/fixtures/session_v1.golden.json` is the contract artifact (regenerate-and-diff).

> Note: the snapshot lives in a new top-level `cemaf.operator` package (not `observability`):
> it sits *above* both observability and orchestration (it imports `RunRecord` and
> `ExecutionResult`), so placing it under the lower observability layer would be a back-edge.

## 10. Test Coverage Update

### a. In-repo layered (cemaf `tests/unit/operator/test_snapshot.py`)
- **L0 (surface)**: every §2 model constructs + serializes; `SessionSnapshot.json_schema()`
  returns a dict with the declared top-level fields; `to_json()` round-trips; `map_run_status`
  / `map_health_status` cover every enum member.
- **L2 (behavior)**: each §3 invariant — determinism (byte-identical + insertion-order-robust),
  unknown-nested survives through the SessionSnapshot envelope, foreign schema_version rejected,
  absent-service="absent", aggregates sum to worker_count (incl. zero-workers boundary), input
  not mutated (both adapters), totals match source. Golden-fixture test: a known RunRecord → the
  committed `tests/observability/fixtures/session_v1.golden.json` (regenerate-and-diff).
- **Integration** (`tests/integration/test_snapshot_real_run.py`): drive a real 2-node agent DAG
  through the real `DAGExecutor` + a real `InMemoryRunLogger`, then snapshot BOTH the returned
  `ExecutionResult` and the logged `RunRecord` — proving the adapters work on production-shaped
  objects (per "fixtures mirror reality"), not just hand-built ones.

### Self-verification
`cd cemaf && uv run pytest tests/unit/operator tests/integration/test_snapshot_real_run.py -q && uv run mypy src/cemaf/operator && uv run ruff check`. Confirm each §2/§3/§4 entry has a test before the PR.

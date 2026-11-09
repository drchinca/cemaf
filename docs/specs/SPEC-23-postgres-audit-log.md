---
title: Postgres Audit Log
spec_id: SPEC-23
status: Implemented
last_reviewed: 2026-11-06
owner: drchinca
parent: none
depends_on: []
---

# SPEC-23: Postgres Audit Log

> The durable `AuditLog` backend. `create_audit_log(backend="postgres")` returns
> it whenever a DSN is configured, so it must work against a real Postgres.

## 1. Context

`PostgresAuditLog` had no test of any kind. Run against a real database for the
first time, every read query failed: each SQL string began with
`f"""  # nosec B608`, so the linter comment became part of the SQL and Postgres
rejected it with a syntax error. The module docstring also promised revoked
UPDATE/DELETE and monthly partitions, neither of which the DDL does.

## 2. Interface Contract (MDE)

```python
class PostgresAuditLog:  # satisfies cemaf.audit.protocols.AuditLog
    def __init__(self, dsn: str, signing_registry: SigningKeyRegistry | None = None,
                 schema: str = "cemaf", pool_min: int = 2, pool_max: int = 5) -> None: ...
    async def append(self, entry: AuditEntry) -> None: ...
    async def query(self, *, run_id=None, entry_type=None, since=None, limit=100) -> tuple[AuditEntry, ...]: ...
    async def count(self, *, run_id: str | None = None) -> int: ...
    async def verify_chain(self, run_id: str) -> tuple[bool, str | None]: ...
```

## 3. Invariants (DbC)

1. `THE System SHALL return appended entries from query() with type, payload and run order intact.`
2. `WHEN a signing registry is configured, THE System SHALL verify every entry of a run`, and `IF a stored row was edited after it was written, THEN verify_chain SHALL return (False, that entry's id).`
3. `PostgresAuditLog SHALL satisfy the AuditLog protocol`, so `InMemoryAuditTrail` works on top of it.
4. `THE module SHALL NOT claim database-level append-only enforcement`; that is the deployer's grant.

Budget: 4 invariants.

## 4. Acceptance Criteria (BDD)

```gherkin
Feature: Postgres audit log

  Scenario: Entries round-trip through Postgres
    When three entries for two runs are appended
    Then query(run_id) returns that run's entries in order with their payloads

  Scenario: A tampered row is caught
    Given a signed run of two entries that verifies
    When one row's payload is edited with SQL
    Then verify_chain reports that row

  Scenario: The audit trail reads from Postgres
    When get_run_timeline runs over a PostgresAuditLog
    Then it returns that run's entries only
```

## 5. Out of Scope

- Revoking UPDATE/DELETE or partitioning the table.
- Retention and archival.

## 10. Test Coverage Update

- **Integration** (`tests/integration/test_postgres_audit_log_live.py`): all §4
  scenarios against a real Postgres (CI: `pgvector/pgvector` service container).

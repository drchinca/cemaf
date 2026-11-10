"""PostgresAuditLog against a real Postgres.

Run with a Postgres reachable at CEMAF_TEST_POSTGRES_DSN (CI provides one):
    CEMAF_TEST_POSTGRES_DSN=postgresql://cemaf@localhost:5432/cemaf \
        uv run pytest -q tests/integration/test_postgres_audit_log_live.py

Before this file the Postgres audit backend had no test of any kind.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from cemaf.audit.models import AuditEntry, AuditEntryType
from cemaf.audit.postgres_audit_log import PostgresAuditLog
from cemaf.audit.protocols import AuditLog
from cemaf.audit.signing import SigningKeyRegistry
from cemaf.audit.trail import InMemoryAuditTrail

_DSN = os.getenv("CEMAF_TEST_POSTGRES_DSN")

pytestmark = pytest.mark.skipif(_DSN is None, reason="set CEMAF_TEST_POSTGRES_DSN to run against Postgres")


class InMemoryEd25519Key:
    """KeyProvider holding a freshly generated Ed25519 key (real crypto, no env var)."""

    def __init__(self, *, key_id: str) -> None:
        self._key_id = key_id
        self._private_key = Ed25519PrivateKey.generate()

    @property
    def key_id(self) -> str:
        return self._key_id

    def sign(self, payload: bytes) -> bytes:
        return self._private_key.sign(payload)

    def verify(self, payload: bytes, signature: bytes) -> bool:
        try:
            self._private_key.public_key().verify(signature, payload)
        except Exception:
            return False
        return True


@pytest.fixture
async def schema() -> AsyncIterator[str]:
    """A fresh schema per test, dropped afterwards."""
    import asyncpg

    name = f"cemaf_audit_{uuid.uuid4().hex[:8]}"
    yield name
    conn = await asyncpg.connect(_DSN)
    try:
        await conn.execute(f'DROP SCHEMA IF EXISTS "{name}" CASCADE')
    finally:
        await conn.close()


def _entry(*, run_id: str, node_id: str) -> AuditEntry:
    return AuditEntry.create(
        type=AuditEntryType.NODE_EXECUTED,
        run_id=run_id,
        source="dag_executor",
        payload={"node_id": node_id, "output": {"rows": 3}},
        correlation_id=run_id,
    )


@pytest.mark.asyncio
async def test_entries_round_trip_through_real_postgres(schema: str) -> None:
    """Appended entries come back with their payload, type and order intact."""
    assert _DSN is not None
    log = PostgresAuditLog(dsn=_DSN, schema=schema, pool_min=1)
    try:
        first = _entry(run_id="run-a", node_id="extract")
        second = _entry(run_id="run-a", node_id="load")
        await log.append(first)
        await log.append(second)
        await log.append(_entry(run_id="run-b", node_id="other"))

        run_a = await log.query(run_id="run-a")

        assert [e.payload["node_id"] for e in run_a] == ["extract", "load"]
        assert run_a[0].type is AuditEntryType.NODE_EXECUTED
        assert run_a[0].payload["output"] == {"rows": 3}
        assert await log.count(run_id="run-a") == 2
        assert await log.count() == 3
    finally:
        await log.close()


@pytest.mark.asyncio
async def test_signed_chain_verifies_and_a_tampered_row_is_caught(schema: str) -> None:
    """Signatures stored in Postgres verify, and editing a row in SQL breaks verification for that row."""
    import asyncpg

    assert _DSN is not None
    registry = SigningKeyRegistry(
        providers={"test": InMemoryEd25519Key(key_id="test")}, current_key_id="test"
    )
    log = PostgresAuditLog(dsn=_DSN, schema=schema, signing_registry=registry, pool_min=1)
    try:
        await log.append(_entry(run_id="run-signed", node_id="extract"))
        tampered = _entry(run_id="run-signed", node_id="load")
        await log.append(tampered)

        assert await log.verify_chain("run-signed") == (True, None)

        conn = await asyncpg.connect(_DSN)
        try:
            await conn.execute(
                f'UPDATE "{schema}".audit_log SET payload = $1 WHERE id = $2',
                '{"node_id": "load", "output": {"rows": 999}}',
                tampered.id,
            )
        finally:
            await conn.close()

        assert await log.verify_chain("run-signed") == (False, tampered.id)
    finally:
        await log.close()


@pytest.mark.asyncio
async def test_audit_trail_reads_a_run_timeline_from_postgres(schema: str) -> None:
    """The factory hands this class out as an AuditLog; the audit trail must work on top of it."""
    assert _DSN is not None
    log = PostgresAuditLog(dsn=_DSN, schema=schema, pool_min=1)
    try:
        await log.append(_entry(run_id="run-t", node_id="extract"))
        await log.append(_entry(run_id="run-t", node_id="load"))
        await log.append(_entry(run_id="run-other", node_id="unrelated"))

        assert isinstance(log, AuditLog)
        timeline = await InMemoryAuditTrail(audit_log=log).get_run_timeline("run-t")

        assert [e.payload["node_id"] for e in timeline] == ["extract", "load"]
    finally:
        await log.close()

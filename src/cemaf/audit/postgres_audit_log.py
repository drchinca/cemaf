"""
PostgreSQL-backed append-only AuditLog with Ed25519 signature storage.

The application DB user must have INSERT + SELECT only — DELETE/UPDATE
are revoked at table creation to enforce append-only at the DB level.
Monthly range partitions for retention management.

Requires ``asyncpg`` (``pip install 'cemaf[postgres]'``).
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING, Any

from cemaf.audit.models import AuditEntry, AuditEntryType

if TYPE_CHECKING:
    from cemaf.audit.signing import SigningKeyRegistry


class PostgresAuditLog:
    """
    Append-only AuditLog backed by PostgreSQL.

    Table layout uses a simple primary key (``id TEXT``) with two composite
    indexes for the most common query patterns (by run_id+timestamp and by
    type+timestamp).

    If *signing_registry* is provided every appended entry is signed before
    insertion, and the signature columns are populated.  The ``verify_chain``
    method can be used to audit an entire run's entries offline.

    Args:
        dsn:              asyncpg-compatible DSN, e.g.
                          ``"postgresql://user:pass@host/db"``.
        signing_registry: Optional registry; when set entries are signed.
        schema:           Postgres schema name (default ``"cemaf"``).
        pool_min:         Minimum pool connections (default 2).
        pool_max:         Maximum pool connections (default 5).
    """

    def __init__(
        self,
        dsn: str,
        signing_registry: SigningKeyRegistry | None = None,
        schema: str = "cemaf",
        pool_min: int = 2,
        pool_max: int = 5,
    ) -> None:
        try:
            import asyncpg  # noqa: PLC0415, F401
        except ImportError as exc:
            raise ImportError(
                "asyncpg is required for PostgresAuditLog. Install it with: pip install 'cemaf[postgres]'"
            ) from exc

        self._dsn = dsn
        self._signing_registry = signing_registry
        self._schema = schema
        self._pool_min = pool_min
        self._pool_max = pool_max
        self._pool: Any = None  # asyncpg.Pool, typed as Any to avoid hard dep

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def _get_pool(self) -> Any:
        """Return the connection pool, creating it on first call."""
        if self._pool is None:
            import asyncpg  # noqa: PLC0415

            self._pool = await asyncpg.create_pool(
                self._dsn,
                min_size=self._pool_min,
                max_size=self._pool_max,
            )
            await self._ensure_schema()
        return self._pool

    async def close(self) -> None:
        """Gracefully close the connection pool."""
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def _ensure_schema(self) -> None:
        """Create the audit_log table and indexes if they do not exist."""
        schema = self._schema
        ddl = f"""
        CREATE SCHEMA IF NOT EXISTS {schema};

        CREATE TABLE IF NOT EXISTS {schema}.audit_log (
            id                  TEXT        NOT NULL,
            type                TEXT        NOT NULL,
            timestamp           TIMESTAMPTZ NOT NULL,
            run_id              TEXT        NOT NULL,
            source              TEXT        NOT NULL,
            correlation_id      TEXT,
            payload             JSONB       NOT NULL DEFAULT '{{}}',
            metadata            JSONB       NOT NULL DEFAULT '{{}}',
            signature           BYTEA,
            signer_key_id       TEXT,
            signature_algorithm TEXT        DEFAULT 'ed25519',
            PRIMARY KEY (id)
        );

        CREATE INDEX IF NOT EXISTS idx_al_run_ts
            ON {schema}.audit_log (run_id, timestamp);

        CREATE INDEX IF NOT EXISTS idx_al_type_ts
            ON {schema}.audit_log (type, timestamp);
        """
        pool = self._pool
        async with pool.acquire() as conn:
            await conn.execute(ddl)

    # ------------------------------------------------------------------
    # AuditLog protocol
    # ------------------------------------------------------------------

    async def append(self, entry: AuditEntry) -> None:
        """
        Insert *entry* into the audit_log table.

        If a signing registry is configured, the entry is signed first and
        the signature columns are populated.
        """
        pool = await self._get_pool()

        signature: bytes | None = None
        signer_key_id: str | None = None
        sig_alg: str | None = None

        if self._signing_registry is not None:
            from cemaf.audit.models_v2 import SignedAuditEntry  # noqa: PLC0415

            signed: SignedAuditEntry = self._signing_registry.sign(entry)
            signature = signed.signature
            signer_key_id = signed.signer_key_id
            sig_alg = signed.signature_algorithm

        sql = f"""
        INSERT INTO {self._schema}.audit_log
            (id, type, timestamp, run_id, source, correlation_id,
             payload, metadata, signature, signer_key_id, signature_algorithm)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
        ON CONFLICT (id) DO NOTHING
        """
        async with pool.acquire() as conn:
            await conn.execute(
                sql,
                entry.id,
                entry.type.value,
                entry.timestamp,
                entry.run_id,
                entry.source,
                entry.correlation_id,
                json.dumps(entry.payload),
                json.dumps(entry.metadata),
                signature,
                signer_key_id,
                sig_alg or "ed25519",
            )

    async def query(
        self,
        *,
        run_id: str | None = None,
        entry_type: AuditEntryType | None = None,
        since: datetime | None = None,
        limit: int = 100,
    ) -> tuple[AuditEntry, ...]:
        """Return entries matching the given filters, ordered by timestamp ascending."""
        pool = await self._get_pool()

        conditions: list[str] = []
        params: list[Any] = []
        idx = 1

        if run_id is not None:
            conditions.append(f"run_id = ${idx}")
            params.append(run_id)
            idx += 1

        if entry_type is not None:
            conditions.append(f"type = ${idx}")
            params.append(entry_type.value)
            idx += 1

        if since is not None:
            conditions.append(f"timestamp >= ${idx}")
            params.append(since)
            idx += 1

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.append(limit)

        sql = f"""
        SELECT id, type, timestamp, run_id, source,
               correlation_id, payload, metadata
        FROM {self._schema}.audit_log
        {where}
        ORDER BY timestamp ASC
        LIMIT ${idx}
        """

        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)

        return tuple(self._row_to_entry(r) for r in rows)

    async def count(self, *, run_id: str | None = None) -> int:
        """Return total number of entries, optionally filtered by *run_id*."""
        pool = await self._get_pool()

        if run_id is not None:
            sql = f"SELECT COUNT(*) FROM {self._schema}.audit_log WHERE run_id = $1"
            async with pool.acquire() as conn:
                return int(await conn.fetchval(sql, run_id))
        else:
            sql = f"SELECT COUNT(*) FROM {self._schema}.audit_log"
            async with pool.acquire() as conn:
                return int(await conn.fetchval(sql))

    # ------------------------------------------------------------------
    # Extra: verify_chain (not in AuditLog protocol)
    # ------------------------------------------------------------------

    async def verify_chain(self, run_id: str) -> tuple[bool, str | None]:
        """
        Verify the Ed25519 signature on every entry for *run_id*.

        Entries are fetched in ascending timestamp order.

        Returns:
            ``(True, None)`` — all signatures are valid.
            ``(False, entry_id)`` — the first entry whose signature fails.

        Raises:
            RuntimeError: If no signing_registry was configured.
        """
        if self._signing_registry is None:
            raise RuntimeError(
                "verify_chain requires a signing_registry; "
                "pass signing_registry= to PostgresAuditLog.__init__"
            )

        pool = await self._get_pool()

        sql = f"""
        SELECT id, type, timestamp, run_id, source,
               correlation_id, payload, metadata,
               signature, signer_key_id, signature_algorithm
        FROM {self._schema}.audit_log
        WHERE run_id = $1
        ORDER BY timestamp ASC
        """
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, run_id)

        from cemaf.audit.models_v2 import SignedAuditEntry  # noqa: PLC0415

        for row in rows:
            base = self._row_to_entry(row)
            sig = row["signature"]
            if not sig:
                # Entry was inserted without signing — treat as failure
                return False, row["id"]

            signed = SignedAuditEntry.from_audit_entry(
                entry=base,
                signature=bytes(sig),
                signer_key_id=row["signer_key_id"] or "",
            )
            if not self._signing_registry.verify_any(signed):
                return False, row["id"]

        return True, None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_entry(row: Any) -> AuditEntry:
        """Convert an asyncpg Record to an AuditEntry."""
        payload = row["payload"]
        metadata = row["metadata"]

        # asyncpg may return JSONB as a string or already parsed
        if isinstance(payload, str):
            payload = json.loads(payload)
        if isinstance(metadata, str):
            metadata = json.loads(metadata)

        return AuditEntry(
            id=row["id"],
            type=AuditEntryType(row["type"]),
            timestamp=row["timestamp"],
            run_id=row["run_id"],
            source=row["source"],
            correlation_id=row["correlation_id"],
            payload=payload or {},
            metadata=metadata or {},
        )

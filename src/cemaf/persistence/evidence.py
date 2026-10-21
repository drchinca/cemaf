"""Durable per-call evidence and immutable transitive answer dependencies."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Protocol, runtime_checkable

from pydantic import model_validator

from cemaf.context.manifest import ContentDigest, ImmutableModel, RequestManifest, canonical_json
from cemaf.llm.preflight import PreflightReceipt


class RecordedEvidence(ImmutableModel):
    request: RequestManifest
    preflight: PreflightReceipt
    response_json: str

    @model_validator(mode="after")
    def validate_response(self) -> RecordedEvidence:
        if canonical_json(json.loads(self.response_json)) != self.response_json:
            raise ValueError("Response must be canonical JSON")
        return self

    @property
    def evidence_id(self) -> str:
        return ContentDigest.of(canonical_json(self.model_dump(mode="json")).encode()).digest


@runtime_checkable
class EvidenceStore(Protocol):
    def save(self, record: RecordedEvidence) -> str: ...
    def load(self, evidence_id: str) -> RecordedEvidence: ...
    def bind_answer(self, *, answer_id: str, evidence_ids: tuple[str, ...]) -> None: ...
    def affected_answers(self, *, source_ids: tuple[str, ...]) -> tuple[str, ...]: ...


class SQLiteEvidenceStore:
    """A local evidence store. Records never change when review status changes."""

    def __init__(self, *, path: str | Path, tenant_id: str) -> None:
        self.path, self.tenant_id = Path(path), tenant_id
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(mode=0o600, exist_ok=True)
        self.path.chmod(0o600)
        if not tenant_id:
            raise ValueError("A tenant identity is required")
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS evidence (
                    tenant TEXT, id TEXT, payload TEXT NOT NULL, PRIMARY KEY (tenant, id));
                CREATE TABLE IF NOT EXISTS evidence_entities (
                    tenant TEXT, id TEXT, kind TEXT, PRIMARY KEY (tenant, id));
                CREATE TABLE IF NOT EXISTS evidence_dependencies (
                    tenant TEXT, child TEXT, parent TEXT, PRIMARY KEY (tenant, child, parent));
            """)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def _bind(self, db: sqlite3.Connection, *, derived_id: str, parents: tuple[str, ...], kind: str) -> None:
        existing = db.execute(
            "SELECT kind FROM evidence_entities WHERE tenant=? AND id=?", (self.tenant_id, derived_id)
        ).fetchone()
        if existing is not None:
            previous = {
                row[0]
                for row in db.execute(
                    "SELECT parent FROM evidence_dependencies WHERE tenant=? AND child=?",
                    (self.tenant_id, derived_id),
                )
            }
            if previous != set(parents) or existing[0] != kind:
                raise ValueError("Evidence dependencies are immutable")
            return
        for parent in parents:
            reachable = db.execute(
                """
                WITH RECURSIVE ancestors(id) AS (
                    SELECT ? UNION SELECT d.parent FROM evidence_dependencies d
                    JOIN ancestors a ON d.child=a.id
                    WHERE d.tenant=?) SELECT id FROM ancestors WHERE id=?
            """,
                (parent, self.tenant_id, derived_id),
            ).fetchone()
            if reachable is not None:
                raise ValueError("Cyclic evidence dependency")
        db.execute("INSERT INTO evidence_entities VALUES (?, ?, ?)", (self.tenant_id, derived_id, kind))
        db.executemany(
            "INSERT INTO evidence_dependencies VALUES (?, ?, ?)",
            ((self.tenant_id, derived_id, parent) for parent in set(parents)),
        )

    def save(self, record: RecordedEvidence) -> str:
        if record.request.context.tenant_id != self.tenant_id:
            raise ValueError("Evidence belongs to a different tenant")
        payload = record.model_dump_json()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "INSERT OR IGNORE INTO evidence VALUES (?, ?, ?)",
                (self.tenant_id, record.evidence_id, payload),
            )
            for dependency in record.request.context.dependencies:
                self._bind(
                    db, derived_id=dependency.source_id, parents=dependency.parent_source_ids, kind="source"
                )
            self._bind(
                db,
                derived_id=record.evidence_id,
                parents=record.request.receipt.selected_ref_ids,
                kind="call",
            )
        return record.evidence_id

    def load(self, evidence_id: str) -> RecordedEvidence:
        with self._connect() as db:
            row = db.execute(
                "SELECT payload FROM evidence WHERE tenant=? AND id=?", (self.tenant_id, evidence_id)
            ).fetchone()
        if row is None:
            raise FileNotFoundError("Recorded evidence is missing")
        record = RecordedEvidence.model_validate_json(row[0])
        if record.evidence_id != evidence_id or record.request.context.tenant_id != self.tenant_id:
            raise ValueError("Recorded evidence identity mismatch")
        return record

    def bind_answer(self, *, answer_id: str, evidence_ids: tuple[str, ...]) -> None:
        for evidence_id in evidence_ids:
            self.load(evidence_id)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._bind(db, derived_id=answer_id, parents=evidence_ids, kind="answer")

    def affected_answers(self, *, source_ids: tuple[str, ...]) -> tuple[str, ...]:
        affected: set[str] = set()
        with self._connect() as db:
            for source_id in source_ids:
                rows = db.execute(
                    """
                    WITH RECURSIVE affected(id) AS (
                        SELECT ? UNION SELECT d.child FROM evidence_dependencies d
                        JOIN affected a ON d.parent=a.id
                        WHERE d.tenant=?)
                    SELECT e.id FROM evidence_entities e JOIN affected a ON e.id=a.id
                    WHERE e.tenant=? AND e.kind='answer'
                """,
                    (source_id, self.tenant_id, self.tenant_id),
                )
                affected.update(row[0] for row in rows)
        return tuple(sorted(affected))

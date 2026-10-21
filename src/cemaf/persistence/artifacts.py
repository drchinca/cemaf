"""Tenant-scoped immutable snapshots with current authorization and integrity.

This local SQLite adapter is for bounded text evidence. Its database is a
trusted local store, not a distributed authority or a bulk-object data plane.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Protocol, runtime_checkable

from cemaf.context.manifest import ArtifactRef, ContentDigest
from cemaf.context.patch import SecurityLevel


class ArtifactIntegrityError(RuntimeError):
    """A pinned artifact is absent, replaced, or corrupted."""


class ArtifactAccessDeniedError(PermissionError):
    """Current policy denies evidence access; messages omit protected identifiers."""


@runtime_checkable
class ArtifactRegistry(Protocol):
    async def register(self, ref: ArtifactRef) -> None: ...
    async def head(self, artifact_id: str, version: str) -> ArtifactRef: ...
    async def authorize(
        self, *, ref: ArtifactRef, tenant_id: str, principal_id: str, clearance: SecurityLevel
    ) -> bool: ...


@runtime_checkable
class ArtifactResolver(ArtifactRegistry, Protocol):
    @property
    def authorization_version(self) -> str: ...
    async def resolve(self, *, ref: ArtifactRef, principal_id: str, clearance: SecurityLevel) -> bytes: ...


class SQLiteArtifactRegistry:
    """Immutable revision bindings; grants are re-read on every resolution."""

    def __init__(self, *, path: str | Path, tenant_id: str, max_artifact_bytes: int = 1_000_000) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(mode=0o600, exist_ok=True)
        self.path.chmod(0o600)
        if not tenant_id or max_artifact_bytes < 1:
            raise ValueError("A tenant and positive artifact byte limit are required")
        self.tenant_id = tenant_id
        self.max_artifact_bytes = max_artifact_bytes
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS snapshots (
                    tenant TEXT, artifact TEXT, version TEXT, ref TEXT NOT NULL, content BLOB NOT NULL,
                    PRIMARY KEY (tenant, artifact, version));
                CREATE TABLE IF NOT EXISTS artifact_grants (
                    tenant TEXT, principal TEXT, artifact TEXT, version TEXT,
                    PRIMARY KEY (tenant, principal, artifact, version));
                CREATE TABLE IF NOT EXISTS authorization_epochs (tenant TEXT PRIMARY KEY, epoch INTEGER);
            """)
            db.execute("INSERT OR IGNORE INTO authorization_epochs VALUES (?, 0)", (tenant_id,))

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    @property
    def authorization_version(self) -> str:
        with self._connect() as db:
            row = db.execute(
                "SELECT epoch FROM authorization_epochs WHERE tenant=?", (self.tenant_id,)
            ).fetchone()
        return str(row[0])

    async def put(
        self,
        *,
        artifact_id: str,
        version: str,
        content: bytes,
        security_level: SecurityLevel = SecurityLevel.INTERNAL,
    ) -> ArtifactRef:
        if len(content) > self.max_artifact_bytes:
            raise ValueError("Artifact exceeds the local adapter byte limit")
        digest = ContentDigest.of(content)
        ref = ArtifactRef(
            tenant_id=self.tenant_id,
            artifact_id=artifact_id,
            version=version,
            locator=f"sqlite:sha256:{digest.digest}",
            digest=digest,
            logical_bytes=len(content),
            security_level=security_level,
        )
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT ref, content FROM snapshots WHERE tenant=? AND artifact=? AND version=?",
                (self.tenant_id, artifact_id, version),
            ).fetchone()
            if row is not None:
                existing = ArtifactRef.model_validate_json(row[0])
                if bytes(row[1]) != content or existing.security_level != security_level:
                    raise ArtifactIntegrityError("An immutable revision cannot be replaced")
                return existing
            db.execute(
                "INSERT INTO snapshots VALUES (?, ?, ?, ?, ?)",
                (self.tenant_id, artifact_id, version, ref.model_dump_json(), content),
            )
        return ref

    async def head(self, artifact_id: str, version: str) -> ArtifactRef:
        with self._connect() as db:
            row = db.execute(
                "SELECT ref FROM snapshots WHERE tenant=? AND artifact=? AND version=?",
                (self.tenant_id, artifact_id, version),
            ).fetchone()
        if row is None:
            raise ArtifactIntegrityError("Pinned evidence is missing")
        return ArtifactRef.model_validate_json(row[0])

    async def register(self, ref: ArtifactRef) -> None:
        if ref.tenant_id != self.tenant_id or await self.head(ref.artifact_id, ref.version) != ref:
            raise ArtifactIntegrityError("Reference does not match an existing immutable snapshot")

    async def set_access(self, *, ref: ArtifactRef, principal_id: str, allowed: bool) -> None:
        await self.register(ref)
        with self._connect() as db:
            if allowed:
                db.execute(
                    "INSERT OR IGNORE INTO artifact_grants VALUES (?, ?, ?, ?)",
                    (self.tenant_id, principal_id, ref.artifact_id, ref.version),
                )
            else:
                db.execute(
                    "DELETE FROM artifact_grants WHERE tenant=? AND principal=? AND artifact=? AND version=?",
                    (self.tenant_id, principal_id, ref.artifact_id, ref.version),
                )
            db.execute("UPDATE authorization_epochs SET epoch=epoch+1 WHERE tenant=?", (self.tenant_id,))

    async def authorize(
        self,
        *,
        ref: ArtifactRef,
        tenant_id: str,
        principal_id: str,
        clearance: SecurityLevel,
    ) -> bool:
        if (
            tenant_id != self.tenant_id
            or ref.tenant_id != tenant_id
            or clearance.rank < ref.security_level.rank
        ):
            return False
        with self._connect() as db:
            row = db.execute(
                "SELECT 1 FROM artifact_grants WHERE tenant=? AND principal=? AND artifact=? AND version=?",
                (tenant_id, principal_id, ref.artifact_id, ref.version),
            ).fetchone()
        return row is not None

    async def resolve(self, *, ref: ArtifactRef, principal_id: str, clearance: SecurityLevel) -> bytes:
        if not await self.authorize(
            ref=ref, tenant_id=self.tenant_id, principal_id=principal_id, clearance=clearance
        ):
            raise ArtifactAccessDeniedError("Evidence access denied by current policy")
        await self.register(ref)
        with self._connect() as db:
            row = db.execute(
                "SELECT content FROM snapshots WHERE tenant=? AND artifact=? AND version=?",
                (self.tenant_id, ref.artifact_id, ref.version),
            ).fetchone()
        if row is None:
            raise ArtifactIntegrityError("Pinned evidence is missing")
        content = bytes(row[0])
        if len(content) != ref.logical_bytes or ContentDigest.of(content) != ref.digest:
            raise ArtifactIntegrityError("Pinned evidence failed integrity verification")
        return content

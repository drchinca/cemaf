"""Audit protocols — contracts for audit logging and trail analysis."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from cemaf.audit.models import AuditEntry, AuditEntryType


@runtime_checkable
class AuditLog(Protocol):
    """Append-only audit log with query capabilities."""

    async def append(self, entry: AuditEntry) -> None: ...

    async def query(
        self,
        *,
        run_id: str | None = None,
        entry_type: AuditEntryType | None = None,
        since: datetime | None = None,
        limit: int = 100,
    ) -> tuple[AuditEntry, ...]: ...

    async def count(self, *, run_id: str | None = None) -> int: ...


@runtime_checkable
class AuditTrail(Protocol):
    """Higher-level audit analysis over the log."""

    async def get_run_timeline(self, run_id: str) -> tuple[AuditEntry, ...]: ...

    async def get_quality_trend(self, *, window: int = 20) -> tuple[float, ...]: ...

    async def get_anomalies(self, *, threshold: float = 2.0) -> tuple[AuditEntry, ...]: ...

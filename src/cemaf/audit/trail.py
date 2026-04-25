"""In-memory audit trail — higher-level analysis over an AuditLog."""

from __future__ import annotations

import math

from cemaf.audit.models import AuditEntry, AuditEntryType
from cemaf.audit.protocols import AuditLog


class InMemoryAuditTrail:
    """Higher-level analysis over an AuditLog."""

    def __init__(self, *, audit_log: AuditLog) -> None:
        self._log = audit_log

    async def get_run_timeline(self, run_id: str) -> tuple[AuditEntry, ...]:
        """Get all entries for a run, sorted by timestamp."""
        entries = await self._log.query(run_id=run_id, limit=10_000)
        return tuple(sorted(entries, key=lambda e: e.timestamp))

    async def get_quality_trend(self, *, window: int = 20) -> tuple[float, ...]:
        """Get recent quality scores from EVAL_RESULT entries."""
        entries = await self._log.query(
            entry_type=AuditEntryType.EVAL_RESULT,
            limit=window,
        )
        scores: list[float] = []
        for entry in entries:
            score = entry.payload.get("score")
            if score is not None:
                try:
                    scores.append(float(score))
                except (TypeError, ValueError):
                    continue
        return tuple(scores[-window:])

    async def get_anomalies(self, *, threshold: float = 2.0) -> tuple[AuditEntry, ...]:
        """Find quality alert entries and entries with z-score anomalies."""
        alerts = await self._log.query(
            entry_type=AuditEntryType.QUALITY_ALERT,
            limit=10_000,
        )
        anomalies: list[AuditEntry] = list(alerts)

        eval_entries = await self._log.query(
            entry_type=AuditEntryType.EVAL_RESULT,
            limit=10_000,
        )
        scores_with_entries: list[tuple[float, AuditEntry]] = []
        for entry in eval_entries:
            score = entry.payload.get("score")
            if score is not None:
                try:
                    scores_with_entries.append((float(score), entry))
                except (TypeError, ValueError):
                    continue

        if len(scores_with_entries) >= 2:
            values = [s for s, _ in scores_with_entries]
            mean = sum(values) / len(values)
            variance = sum((v - mean) ** 2 for v in values) / len(values)
            std = math.sqrt(variance)
            if std > 0:
                alert_ids = {e.id for e in anomalies}
                for score, entry in scores_with_entries:
                    z = abs(score - mean) / std
                    if z >= threshold and entry.id not in alert_ids:
                        anomalies.append(entry)

        return tuple(anomalies)

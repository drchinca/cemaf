"""Unit tests for InMemoryAuditTrail — higher-level audit analysis."""

from __future__ import annotations

from datetime import timedelta

import pytest

from cemaf.audit.models import AuditEntry, AuditEntryType
from cemaf.audit.protocols import AuditTrail
from cemaf.audit.subscriber import EventBusAuditLog
from cemaf.audit.trail import InMemoryAuditTrail
from cemaf.core.utils import utc_now


@pytest.fixture()
def audit_log() -> EventBusAuditLog:
    return EventBusAuditLog()


@pytest.fixture()
def trail(audit_log: EventBusAuditLog) -> InMemoryAuditTrail:
    return InMemoryAuditTrail(audit_log=audit_log)


class TestProtocolConformance:
    """InMemoryAuditTrail satisfies the AuditTrail protocol."""

    def test_isinstance_audit_trail(self, trail: InMemoryAuditTrail) -> None:
        """InMemoryAuditTrail is a runtime-checkable AuditTrail."""
        assert isinstance(trail, AuditTrail)


class TestGetRunTimeline:
    """Timeline returns entries sorted by timestamp."""

    @pytest.mark.asyncio()
    async def test_sorted_by_timestamp(self, audit_log: EventBusAuditLog, trail: InMemoryAuditTrail) -> None:
        """Entries are returned in chronological order."""
        now = utc_now()
        timestamps = [now - timedelta(minutes=5), now, now - timedelta(minutes=10)]
        for i, ts in enumerate(timestamps):
            entry = AuditEntry(
                id=f"entry_{i}",
                type=AuditEntryType.NODE_EXECUTED,
                timestamp=ts,
                run_id="run_timeline",
                source="test",
            )
            await audit_log.append(entry=entry)

        timeline = await trail.get_run_timeline(run_id="run_timeline")
        assert len(timeline) == 3
        assert timeline[0].id == "entry_2"  # -10 min
        assert timeline[1].id == "entry_0"  # -5 min
        assert timeline[2].id == "entry_1"  # now

    @pytest.mark.asyncio()
    async def test_filters_by_run_id(self, audit_log: EventBusAuditLog, trail: InMemoryAuditTrail) -> None:
        """Only entries for the requested run_id appear."""
        for run_id in ("run_a", "run_b"):
            entry = AuditEntry.create(
                type=AuditEntryType.NODE_EXECUTED,
                run_id=run_id,
                source="test",
            )
            await audit_log.append(entry=entry)

        timeline = await trail.get_run_timeline(run_id="run_a")
        assert len(timeline) == 1
        assert timeline[0].run_id == "run_a"

    @pytest.mark.asyncio()
    async def test_empty_for_unknown_run(self, trail: InMemoryAuditTrail) -> None:
        """Unknown run_id returns empty tuple."""
        timeline = await trail.get_run_timeline(run_id="nonexistent")
        assert timeline == ()


class TestGetQualityTrend:
    """Quality trend extracts scores from EVAL_RESULT entries."""

    @pytest.mark.asyncio()
    async def test_returns_scores(self, audit_log: EventBusAuditLog, trail: InMemoryAuditTrail) -> None:
        """Scores are extracted from payload."""
        for score in (0.8, 0.9, 0.7):
            entry = AuditEntry.create(
                type=AuditEntryType.EVAL_RESULT,
                run_id="run_q",
                source="eval",
                payload={"score": score},
            )
            await audit_log.append(entry=entry)

        trend = await trail.get_quality_trend(window=10)
        assert trend == (0.8, 0.9, 0.7)

    @pytest.mark.asyncio()
    async def test_empty_log_returns_empty(self, trail: InMemoryAuditTrail) -> None:
        """No entries means no scores."""
        trend = await trail.get_quality_trend()
        assert trend == ()

    @pytest.mark.asyncio()
    async def test_window_limits_results(
        self, audit_log: EventBusAuditLog, trail: InMemoryAuditTrail
    ) -> None:
        """Window parameter limits the number of scores returned."""
        for score in (0.1, 0.2, 0.3, 0.4, 0.5):
            entry = AuditEntry.create(
                type=AuditEntryType.EVAL_RESULT,
                run_id="run_w",
                source="eval",
                payload={"score": score},
            )
            await audit_log.append(entry=entry)

        trend = await trail.get_quality_trend(window=3)
        assert len(trend) <= 3

    @pytest.mark.asyncio()
    async def test_skips_entries_without_score(
        self, audit_log: EventBusAuditLog, trail: InMemoryAuditTrail
    ) -> None:
        """Entries with no score in payload are skipped."""
        entry_with = AuditEntry.create(
            type=AuditEntryType.EVAL_RESULT,
            run_id="run_skip",
            source="eval",
            payload={"score": 0.85},
        )
        entry_without = AuditEntry.create(
            type=AuditEntryType.EVAL_RESULT,
            run_id="run_skip",
            source="eval",
            payload={"reason": "no score field"},
        )
        await audit_log.append(entry=entry_with)
        await audit_log.append(entry=entry_without)

        trend = await trail.get_quality_trend()
        assert trend == (0.85,)


class TestGetAnomalies:
    """Anomaly detection finds quality alerts and z-score outliers."""

    @pytest.mark.asyncio()
    async def test_returns_quality_alerts(
        self, audit_log: EventBusAuditLog, trail: InMemoryAuditTrail
    ) -> None:
        """QUALITY_ALERT entries are always returned as anomalies."""
        entry = AuditEntry.create(
            type=AuditEntryType.QUALITY_ALERT,
            run_id="run_alert",
            source="quality_police",
            payload={"reason": "score too low"},
        )
        await audit_log.append(entry=entry)

        anomalies = await trail.get_anomalies()
        assert len(anomalies) == 1
        assert anomalies[0].type == AuditEntryType.QUALITY_ALERT

    @pytest.mark.asyncio()
    async def test_detects_zscore_outliers(
        self, audit_log: EventBusAuditLog, trail: InMemoryAuditTrail
    ) -> None:
        """Eval entries with scores far from the mean are flagged."""
        # Create a cluster of normal scores and one outlier
        normal_scores = [0.80, 0.82, 0.81, 0.79, 0.80, 0.83, 0.81, 0.80]
        for score in normal_scores:
            entry = AuditEntry.create(
                type=AuditEntryType.EVAL_RESULT,
                run_id="run_z",
                source="eval",
                payload={"score": score},
            )
            await audit_log.append(entry=entry)

        # Add outlier (very low)
        outlier = AuditEntry.create(
            type=AuditEntryType.EVAL_RESULT,
            run_id="run_z",
            source="eval",
            payload={"score": 0.1},
        )
        await audit_log.append(entry=outlier)

        anomalies = await trail.get_anomalies(threshold=2.0)
        anomaly_ids = {a.id for a in anomalies}
        assert outlier.id in anomaly_ids

    @pytest.mark.asyncio()
    async def test_no_anomalies_in_uniform_scores(
        self, audit_log: EventBusAuditLog, trail: InMemoryAuditTrail
    ) -> None:
        """Uniform scores produce no z-score anomalies."""
        for _ in range(5):
            entry = AuditEntry.create(
                type=AuditEntryType.EVAL_RESULT,
                run_id="run_uniform",
                source="eval",
                payload={"score": 0.80},
            )
            await audit_log.append(entry=entry)

        anomalies = await trail.get_anomalies()
        assert len(anomalies) == 0

    @pytest.mark.asyncio()
    async def test_empty_log_returns_empty(self, trail: InMemoryAuditTrail) -> None:
        """No entries means no anomalies."""
        anomalies = await trail.get_anomalies()
        assert anomalies == ()

    @pytest.mark.asyncio()
    async def test_no_duplicate_between_alerts_and_zscore(
        self, audit_log: EventBusAuditLog, trail: InMemoryAuditTrail
    ) -> None:
        """A QUALITY_ALERT entry is not double-counted even if it's an outlier."""
        # Quality alert entries have type QUALITY_ALERT, not EVAL_RESULT,
        # so they're in different query results and won't duplicate.
        alert = AuditEntry.create(
            type=AuditEntryType.QUALITY_ALERT,
            run_id="run_dup",
            source="police",
        )
        await audit_log.append(entry=alert)

        # Add some eval entries (no outliers)
        for score in (0.8, 0.82, 0.79):
            entry = AuditEntry.create(
                type=AuditEntryType.EVAL_RESULT,
                run_id="run_dup",
                source="eval",
                payload={"score": score},
            )
            await audit_log.append(entry=entry)

        anomalies = await trail.get_anomalies()
        assert len(anomalies) == 1
        assert anomalies[0].id == alert.id

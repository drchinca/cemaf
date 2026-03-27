"""Contract tests for audit models and protocols."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime

import pytest

from cemaf.audit.models import AuditEntry, AuditEntryType, AuditReport
from cemaf.audit.protocols import AuditLog, AuditTrail


class TestAuditEntryType:
    """Verify enum values match the event taxonomy."""

    def test_all_values_present(self) -> None:
        """All seven entry types exist with dotted string values."""
        expected = {
            "NODE_EXECUTED": "node.executed",
            "AGENT_COMPLETED": "agent.completed",
            "CONTEXT_PATCHED": "context.patched",
            "EVAL_RESULT": "eval.result",
            "QUALITY_ALERT": "quality.alert",
            "DAG_COMPLETED": "dag.completed",
            "MEMORY_EXTRACTED": "memory.extracted",
        }
        for name, value in expected.items():
            assert AuditEntryType[name].value == value

    def test_is_str_enum(self) -> None:
        """AuditEntryType values are usable as plain strings."""
        assert isinstance(AuditEntryType.NODE_EXECUTED, str)


class TestAuditEntry:
    """Contract: AuditEntry is frozen and factory-constructable."""

    def test_frozen_raises_on_mutation(self) -> None:
        """Mutating a frozen entry raises FrozenInstanceError."""
        entry = AuditEntry.create(
            type=AuditEntryType.NODE_EXECUTED,
            run_id="run_abc",
            source="system",
        )
        with pytest.raises(FrozenInstanceError):
            entry.run_id = "run_xyz"  # type: ignore[misc]

    def test_create_generates_id(self) -> None:
        """Factory generates an id with 'audit' prefix."""
        entry = AuditEntry.create(
            type=AuditEntryType.EVAL_RESULT,
            run_id="run_001",
            source="eval_agent",
        )
        assert entry.id.startswith("audit_")
        assert len(entry.id) > len("audit_")

    def test_create_generates_timestamp(self) -> None:
        """Factory sets a UTC timestamp."""
        entry = AuditEntry.create(
            type=AuditEntryType.DAG_COMPLETED,
            run_id="run_002",
            source="system",
        )
        assert isinstance(entry.timestamp, datetime)
        assert entry.timestamp.tzinfo is not None

    def test_create_with_all_parameters(self) -> None:
        """Factory accepts all optional fields."""
        entry = AuditEntry.create(
            type=AuditEntryType.QUALITY_ALERT,
            run_id="run_003",
            source="quality_police",
            payload={"score": 0.4, "reason": "below threshold"},
            correlation_id="corr_xyz",
            metadata={"tier": "t1"},
        )
        assert entry.type == AuditEntryType.QUALITY_ALERT
        assert entry.run_id == "run_003"
        assert entry.source == "quality_police"
        assert entry.payload == {"score": 0.4, "reason": "below threshold"}
        assert entry.correlation_id == "corr_xyz"
        assert entry.metadata == {"tier": "t1"}

    def test_create_defaults_empty_dicts(self) -> None:
        """Payload and metadata default to empty dicts."""
        entry = AuditEntry.create(
            type=AuditEntryType.MEMORY_EXTRACTED,
            run_id="run_004",
            source="extraction_pipeline",
        )
        assert entry.payload == {}
        assert entry.metadata == {}
        assert entry.correlation_id is None


class TestAuditReport:
    """Contract: AuditReport is frozen."""

    def test_frozen_raises_on_mutation(self) -> None:
        """Mutating a frozen report raises FrozenInstanceError."""
        report = AuditReport(
            run_id="run_rpt",
            generated_at=datetime.now(),
            total_entries=10,
            quality_scores=(0.8, 0.9),
            quality_mean=0.85,
            anomalies=(),
            coverage_gaps=("node_a",),
        )
        with pytest.raises(FrozenInstanceError):
            report.total_entries = 99  # type: ignore[misc]


class TestProtocolsRuntimeCheckable:
    """Contract: protocols are runtime-checkable for isinstance."""

    def test_audit_log_is_runtime_checkable(self) -> None:
        """AuditLog supports isinstance checks."""

        class _FakeLog:
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

        assert isinstance(_FakeLog(), AuditLog)

    def test_audit_trail_is_runtime_checkable(self) -> None:
        """AuditTrail supports isinstance checks."""

        class _FakeTrail:
            async def get_run_timeline(self, run_id: str) -> tuple[AuditEntry, ...]: ...
            async def get_quality_trend(self, *, window: int = 20) -> tuple[float, ...]: ...
            async def get_anomalies(self, *, threshold: float = 2.0) -> tuple[AuditEntry, ...]: ...

        assert isinstance(_FakeTrail(), AuditTrail)

    def test_non_conforming_object_fails_audit_log(self) -> None:
        """Object without required methods is not an AuditLog."""
        assert not isinstance(object(), AuditLog)

    def test_non_conforming_object_fails_audit_trail(self) -> None:
        """Object without required methods is not an AuditTrail."""
        assert not isinstance(object(), AuditTrail)

"""SPEC-14 — cemaf.session.v1 session snapshot contract."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from cemaf.core.enums import RunStatus
from cemaf.observability.health import HealthStatus
from cemaf.observability.run_logger import RunRecord
from cemaf.operator.snapshot import (
    SCHEMA_VERSION,
    ServicePresence,
    SessionSnapshot,
    SnapshotHealth,
    SnapshotRunState,
    map_health_status,
    map_run_status,
    snapshot_from_execution_result,
    snapshot_from_run_record,
)
from cemaf.orchestration.results import ExecutionResult, NodeResult

_GOLDEN = Path(__file__).resolve().parents[2] / "observability" / "fixtures" / "session_v1.golden.json"

_T0 = datetime(2026, 6, 25, 12, 0, 0, tzinfo=UTC)
_T1 = datetime(2026, 6, 25, 12, 0, 5, tzinfo=UTC)


def _run_record(*, success: bool = True) -> RunRecord:
    return RunRecord(
        run_id="run_123",
        dag_name="research_report",
        started_at=_T0,
        completed_at=_T1,
        success=success,
        total_cost_usd=0.12,
    )


def _execution_result() -> ExecutionResult:
    return ExecutionResult(
        run_id="run_123",
        dag_name="research_report",
        status=RunStatus.COMPLETED,
        node_results=(
            NodeResult(node_id="research", success=True, duration_ms=120.0),
            NodeResult(node_id="write", success=False, error="boom", duration_ms=30.0),
        ),
        started_at=_T0,
        completed_at=_T1,
    )


class TestSnapshotModels:
    def test_schema_version_constant(self) -> None:
        assert SCHEMA_VERSION == "cemaf.session.v1"

    def test_json_schema_exports_top_level_fields(self) -> None:
        schema = SessionSnapshot.json_schema()
        props = schema["properties"]
        for field in ("schema_version", "run", "workers", "runtime", "context", "risk", "aggregates"):
            assert field in props

    def test_to_json_round_trips(self) -> None:
        snap = snapshot_from_run_record(_run_record())
        reparsed = SessionSnapshot.model_validate(json.loads(snap.to_json()))
        assert reparsed.run.id == "run_123"


class TestRunRecordAdapter:
    def test_basic_projection(self) -> None:
        snap = snapshot_from_run_record(_run_record())
        assert snap.schema_version == SCHEMA_VERSION
        assert snap.run.id == "run_123"
        assert snap.run.state is SnapshotRunState.COMPLETED
        assert snap.aggregates.total_cost_usd == 0.12

    def test_failed_run_maps_to_failed(self) -> None:
        snap = snapshot_from_run_record(_run_record(success=False))
        assert snap.run.state is SnapshotRunState.FAILED
        assert snap.workers[0].health is SnapshotHealth.FAILED

    def test_totals_match_source(self) -> None:
        """Inv 7 — aggregates equal the source RunRecord totals."""
        record = _run_record()
        snap = snapshot_from_run_record(record)
        assert snap.aggregates.total_cost_usd == record.total_cost_usd
        assert snap.aggregates.total_tokens == record.total_tokens

    def test_adapter_does_not_mutate_input(self) -> None:
        """Inv 6 — read-only."""
        record = _run_record()
        before = record.to_dict()
        snapshot_from_run_record(record)
        assert record.to_dict() == before

    def test_deterministic_conversion(self) -> None:
        """Inv 2 — same RunRecord ⇒ byte-identical JSON."""
        record = _run_record()
        assert snapshot_from_run_record(record).to_json() == snapshot_from_run_record(record).to_json()


class TestExecutionResultAdapter:
    def test_per_node_workers(self) -> None:
        snap = snapshot_from_execution_result(_execution_result())
        assert snap.aggregates.worker_count == 2
        ids = {w.id for w in snap.workers}
        assert ids == {"research", "write"}

    def test_failed_node_state(self) -> None:
        snap = snapshot_from_execution_result(_execution_result())
        write = next(w for w in snap.workers if w.id == "write")
        assert write.state is SnapshotRunState.FAILED
        assert write.error == "boom"

    def test_aggregates_sum_to_worker_count(self) -> None:
        """Inv 5 — state + health counts sum to worker_count."""
        snap = snapshot_from_execution_result(_execution_result())
        assert sum(snap.aggregates.states.values()) == snap.aggregates.worker_count
        assert sum(snap.aggregates.healths.values()) == snap.aggregates.worker_count


class TestServicePresence:
    def test_present_service_enabled(self) -> None:
        snap = snapshot_from_run_record(_run_record(), services_present=("budget_guard", "event_bus"))
        assert snap.runtime.services["budget_guard"] is ServicePresence.ENABLED

    def test_absent_service_shown_not_errored(self) -> None:
        """Inv 4 — an unwired optional service is 'absent', not omitted/errored."""
        snap = snapshot_from_run_record(_run_record(), services_present=())
        assert snap.runtime.services["budget_guard"] is ServicePresence.ABSENT


class TestSchemaDiscipline:
    def test_foreign_schema_version_rejected(self) -> None:
        """Inv 1 — a non-v1 top-level schema_version fails validation."""
        snap = snapshot_from_run_record(_run_record())
        data = snap.model_dump(mode="json")
        data["schema_version"] = "cemaf.session.v2"
        with pytest.raises(ValidationError):
            SessionSnapshot.model_validate(data)

    def test_unknown_nested_metadata_survives_through_envelope(self) -> None:
        """Inv 3 — an unrecognized key in worker.metadata round-trips through SessionSnapshot."""
        result = ExecutionResult(
            run_id="r",
            dag_name="d",
            status=RunStatus.COMPLETED,
            node_results=(NodeResult(node_id="n", success=True, metadata={"custom_signal": {"nested": 42}}),),
        )
        snap = snapshot_from_execution_result(result)
        restored = SessionSnapshot.model_validate(json.loads(snap.to_json()))
        assert restored.workers[0].metadata["custom_signal"] == {"nested": 42}


class TestDeterminismRobustness:
    def test_metadata_insertion_order_irrelevant(self) -> None:
        """Inv 2 — sort_keys defends against dict insertion-order differences."""
        base = ExecutionResult(
            run_id="r",
            dag_name="d",
            status=RunStatus.COMPLETED,
            node_results=(NodeResult(node_id="n", success=True, metadata={"a": 1, "b": 2, "c": 3}),),
            started_at=_T0,
            completed_at=_T1,
        )
        reordered = ExecutionResult(
            run_id="r",
            dag_name="d",
            status=RunStatus.COMPLETED,
            node_results=(NodeResult(node_id="n", success=True, metadata={"c": 3, "b": 2, "a": 1}),),
            started_at=_T0,
            completed_at=_T1,
        )
        # CPython float repr + sort_keys ⇒ byte-identical regardless of insertion order.
        a = snapshot_from_execution_result(base).to_json()
        b = snapshot_from_execution_result(reordered).to_json()
        assert a == b


class TestGoldenFixture:
    def test_golden_fixture_matches(self) -> None:
        """The committed golden JSON is the contract artifact (regenerate-and-diff).

        Regenerate with: write snapshot_from_run_record(_run_record()).to_json() to the path.
        """
        snap = snapshot_from_run_record(
            _run_record(), services_present=("run_logger", "event_bus", "budget_guard")
        )
        produced = snap.to_json()
        if not _GOLDEN.exists():  # first run bootstraps the fixture
            _GOLDEN.write_text(produced + "\n")
        # rstrip tolerates the trailing newline the end-of-file-fixer adds to the committed file.
        assert produced == _GOLDEN.read_text().rstrip("\n"), (
            "session.v1 snapshot drifted from the golden fixture. If intended, delete "
            f"{_GOLDEN} and re-run to regenerate (and bump schema_version for top-level changes)."
        )


class TestStatusMapping:
    @pytest.mark.parametrize(
        ("status", "expected"),
        [
            (RunStatus.PENDING, SnapshotRunState.PENDING),
            (RunStatus.RUNNING, SnapshotRunState.RUNNING),
            (RunStatus.COMPLETED, SnapshotRunState.COMPLETED),
            (RunStatus.FAILED, SnapshotRunState.FAILED),
            (RunStatus.CANCELLED, SnapshotRunState.CANCELLED),
        ],
    )
    def test_map_run_status(self, status: RunStatus, expected: SnapshotRunState) -> None:
        assert map_run_status(status) is expected

    @pytest.mark.parametrize(
        ("status", "expected"),
        [
            (HealthStatus.HEALTHY, SnapshotHealth.HEALTHY),
            (HealthStatus.DEGRADED, SnapshotHealth.DEGRADED),
            (HealthStatus.UNHEALTHY, SnapshotHealth.FAILED),
        ],
    )
    def test_map_health_status(self, status: HealthStatus, expected: SnapshotHealth) -> None:
        assert map_health_status(status) is expected


class TestEdgeCases:
    def test_zero_workers_aggregates_consistent(self) -> None:
        """Empty node_results ⇒ worker_count 0 and Inv 5 still holds (sums == 0)."""
        result = ExecutionResult(run_id="r", dag_name="d", status=RunStatus.RUNNING, node_results=())
        snap = snapshot_from_execution_result(result)
        assert snap.aggregates.worker_count == 0
        assert sum(snap.aggregates.states.values()) == 0
        assert snap.run.state is SnapshotRunState.RUNNING

    def test_running_run_null_ended_at(self) -> None:
        """A not-yet-completed RunRecord ⇒ ended_at None, duration 0."""
        record = RunRecord(run_id="r", dag_name="d", started_at=_T0, completed_at=None)
        snap = snapshot_from_run_record(record)
        assert snap.run.ended_at is None
        assert snap.workers[0].duration_ms == 0.0

    def test_execution_result_adapter_does_not_mutate_input(self) -> None:
        """Inv 6 on the ExecutionResult path."""
        result = _execution_result()
        before = (result.run_id, result.status, tuple(n.node_id for n in result.node_results))
        snapshot_from_execution_result(result)
        after = (result.run_id, result.status, tuple(n.node_id for n in result.node_results))
        assert before == after

    def test_execution_result_totals_supplied_by_caller(self) -> None:
        """Inv 7 on the ExecutionResult path — caller-supplied totals land in aggregates."""
        snap = snapshot_from_execution_result(
            _execution_result(), total_cost_usd=0.42, total_tokens=8400, tool_calls=3, llm_calls=2
        )
        assert snap.aggregates.total_cost_usd == 0.42
        assert snap.aggregates.total_tokens == 8400
        assert snap.aggregates.tool_calls == 3
        assert snap.aggregates.llm_calls == 2

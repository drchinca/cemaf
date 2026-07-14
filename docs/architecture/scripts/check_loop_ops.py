"""Verify the public loop/operator release seams stay wired.

This is the docs-facing guard referenced by AGENTS.md. It checks the small,
public contracts that make CEMAF inspectable while agent loops are running:

- cemaf.session.v1 snapshots stay deterministic and match the golden fixture.
- Failure-feedback iteration is importable and executable through public APIs.
- Self-improvement is importable and executable through public factories.
- Specs, examples, and tests that prove those contracts remain in place.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]


def _read(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


def _require_file(failures: list[str], rel_path: str) -> None:
    if not (ROOT / rel_path).is_file():
        failures.append(f"missing required file: {rel_path}")


def _require_text(failures: list[str], rel_path: str, needles: tuple[str, ...]) -> None:
    path = ROOT / rel_path
    if not path.is_file():
        failures.append(f"missing required file: {rel_path}")
        return

    text = _read(rel_path)
    for needle in needles:
        if needle not in text:
            failures.append(f"{rel_path}: missing required text: {needle!r}")


def _check_static_contracts(failures: list[str]) -> None:
    required_files = (
        "docs/specs/SPEC-14-session-snapshot-contract.md",
        "docs/architecture/spec-module-map.md",
        "examples/session_snapshot.py",
        "tests/observability/fixtures/session_v1.golden.json",
        "tests/unit/operator/test_snapshot.py",
        "tests/integration/test_snapshot_real_run.py",
        "tests/unit/iteration/test_loop.py",
        "tests/unit/improvement/test_improvement_factories.py",
    )
    for rel_path in required_files:
        _require_file(failures, rel_path)

    _require_text(
        failures,
        "README.md",
        (
            "cemaf.session.v1",
            "SessionSnapshot",
            "snapshot_from_run_record",
            "snapshot_from_execution_result",
        ),
    )
    _require_text(
        failures,
        "docs/specs/SPEC-14-session-snapshot-contract.md",
        (
            'SCHEMA_VERSION = "cemaf.session.v1"',
            "snapshot_from_run_record",
            "snapshot_from_execution_result",
            "session_v1.golden.json",
        ),
    )
    _require_text(
        failures,
        "docs/architecture/spec-module-map.md",
        (
            "Failure-feedback loop (SPEC-08)",
            "`IterationLoop`",
            "`PytestParser`",
            "`RuffParser`",
            "`MypyParser`",
        ),
    )
    _require_text(
        failures,
        "docs/modules.md",
        (
            "improvement/",
            "self-improvement feedback",
        ),
    )


def _check_operator_snapshot(failures: list[str]) -> None:
    from cemaf.context.patch import ContextPatch
    from cemaf.core.enums import RunStatus
    from cemaf.observability.run_logger import LLMCall, RunRecord, ToolCall
    from cemaf.operator import (
        SCHEMA_VERSION,
        ServicePresence,
        SessionSnapshot,
        SnapshotRunState,
        snapshot_from_execution_result,
        snapshot_from_run_record,
    )
    from cemaf.orchestration.results import ExecutionResult, NodeResult

    t0 = datetime(2026, 6, 25, 12, 0, 0, tzinfo=UTC)
    t1 = datetime(2026, 6, 25, 12, 0, 5, tzinfo=UTC)
    record = RunRecord(
        run_id="run_123",
        dag_name="research_report",
        started_at=t0,
        completed_at=t1,
        success=True,
        total_cost_usd=0.12,
    )
    snapshot = snapshot_from_run_record(
        record,
        services_present=("run_logger", "event_bus", "budget_guard"),
    )

    if SCHEMA_VERSION != "cemaf.session.v1":
        failures.append(f"operator schema version drifted: {SCHEMA_VERSION!r}")
    if snapshot.schema_version != SCHEMA_VERSION:
        failures.append("snapshot schema_version does not match SCHEMA_VERSION")
    if snapshot.run.id != record.run_id:
        failures.append("snapshot run.id does not mirror RunRecord.run_id")
    if snapshot.runtime.services["moderation_pipeline"] is not ServicePresence.ABSENT:
        failures.append("absent optional services must be reported as absent")
    if (
        snapshot.to_json()
        != snapshot_from_run_record(
            record,
            services_present=("run_logger", "event_bus", "budget_guard"),
        ).to_json()
    ):
        failures.append("snapshot_from_run_record is not deterministic")

    parsed = SessionSnapshot.model_validate(json.loads(snapshot.to_json()))
    if parsed != snapshot:
        failures.append("SessionSnapshot JSON does not round-trip")

    golden_path = ROOT / "tests/observability/fixtures/session_v1.golden.json"
    if golden_path.is_file() and golden_path.read_text(encoding="utf-8").rstrip("\n") != snapshot.to_json():
        failures.append("session_v1.golden.json does not match the public snapshot contract")

    busy_record = RunRecord(
        run_id="run_busy",
        dag_name="busy",
        started_at=t0,
        completed_at=t1,
        success=True,
        total_cost_usd=0.42,
        llm_calls=(LLMCall(model="m", input_messages=[], output="x", input_tokens=8, output_tokens=5),),
        tool_calls=(ToolCall(tool_id="tool", input={}, output={}),),
        patches=(ContextPatch.set("k", "v"),),
    )
    busy_snapshot = snapshot_from_run_record(busy_record)
    if busy_snapshot.aggregates.total_tokens != busy_record.total_tokens:
        failures.append("snapshot aggregates.total_tokens does not mirror RunRecord")
    if busy_snapshot.aggregates.llm_calls != 1 or busy_snapshot.aggregates.tool_calls != 1:
        failures.append("snapshot aggregate call counts do not mirror RunRecord")
    if busy_snapshot.context.patch_count != 1:
        failures.append("snapshot context.patch_count does not mirror RunRecord")

    result_snapshot = snapshot_from_execution_result(
        ExecutionResult(
            run_id="run_123",
            dag_name="research_report",
            status=RunStatus.COMPLETED,
            node_results=(
                NodeResult(node_id="research", success=True, duration_ms=100.0),
                NodeResult(node_id="write", success=False, error="boom", duration_ms=25.0),
            ),
            started_at=t0,
            completed_at=t1,
        )
    )
    if result_snapshot.aggregates.worker_count != 2:
        failures.append("snapshot_from_execution_result lost per-node workers")
    if result_snapshot.run.state is not SnapshotRunState.COMPLETED:
        failures.append("ExecutionResult status did not map to snapshot run state")
    if sum(result_snapshot.aggregates.states.values()) != result_snapshot.aggregates.worker_count:
        failures.append("snapshot state aggregates do not sum to worker_count")


async def _run_iteration_loop() -> tuple[bool, str]:
    from cemaf.core.result import Result
    from cemaf.iteration import (
        FailureKind,
        IterationLimits,
        IterationLoop,
        IterationOutcome,
        PytestParser,
    )
    from cemaf.sandbox.shell import ShellResult

    calls: list[Any] = []

    async def attempt(signal: Any) -> Result[str]:
        calls.append(signal)
        return Result.ok("artifact", metadata={"cost_usd": 0.01})

    async def verify(_: Result[str]) -> ShellResult:
        if len(calls) == 1:
            return ShellResult(
                command="pytest",
                exit_code=1,
                stdout="FAILED tests/test_contract.py::test_contract - assert 1 == 2",
            )
        return ShellResult(command="pytest", exit_code=0)

    loop = IterationLoop(
        attempt=attempt,
        verify=verify,
        parsers=(PytestParser(),),
        limits=IterationLimits(max_attempts=2, max_cost_usd=1.0),
    )
    report = await loop.run()
    if report.outcome is not IterationOutcome.SUCCESS:
        return False, f"IterationLoop outcome was {report.outcome!r}"
    if report.attempts != 2:
        return False, f"IterationLoop attempts was {report.attempts}, expected 2"
    if calls[0] is not None:
        return False, "first IterationLoop attempt should receive no failure signal"
    if calls[1].kind is not FailureKind.TEST_FAILURE:
        return False, f"second IterationLoop attempt received {calls[1].kind!r}"
    return True, ""


async def _run_improvement_loop() -> tuple[bool, str]:
    from cemaf.improvement import (
        ExecutionSummary,
        ImprovementOutcome,
        create_improvement_runtime,
    )

    runtime = create_improvement_runtime()
    result = await runtime.loop.process(
        ExecutionSummary(
            run_id="run_loop_ops",
            task_description="draft release notes",
            approach="local-first verifier",
            success=True,
            total_tokens=120,
            latency_ms=25.0,
            tool_executions=({"tool_id": "docs-check", "success": True, "latency_ms": 10.0},),
        )
    )
    if not result.success:
        return False, result.error or "SelfImprovementLoop failed"
    if not isinstance(result.data, ImprovementOutcome):
        return False, "SelfImprovementLoop did not return ImprovementOutcome"
    if result.data.run_id != "run_loop_ops":
        return False, "ImprovementOutcome.run_id did not mirror ExecutionSummary"
    if result.data.strategies_updated != 1:
        return False, "SelfImprovementLoop did not record strategy outcome"
    if result.data.quality_score <= 0:
        return False, "SelfImprovementLoop returned non-positive quality score"
    return True, ""


def _check_runtime_paths(failures: list[str]) -> None:
    try:
        _check_operator_snapshot(failures)
    except Exception as exc:  # pragma: no cover - failure printer path
        failures.append(f"operator snapshot check raised {type(exc).__name__}: {exc}")

    for label, coro in (
        ("IterationLoop", _run_iteration_loop()),
        ("SelfImprovementLoop", _run_improvement_loop()),
    ):
        try:
            ok, message = asyncio.run(coro)
        except Exception as exc:  # pragma: no cover - failure printer path
            failures.append(f"{label} check raised {type(exc).__name__}: {exc}")
            continue
        if not ok:
            failures.append(message)


def main() -> int:
    logging.getLogger("cemaf.improvement.loop").setLevel(logging.WARNING)
    failures: list[str] = []
    _check_static_contracts(failures)
    _check_runtime_paths(failures)

    if failures:
        print("Loop/operator contract check failed:")
        for failure in failures:
            print(f"  {failure}")
        return 1

    print("Loop/operator contract check passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

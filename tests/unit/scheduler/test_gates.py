"""Tests for execution gates — TDD contract tests + unit tests."""

from datetime import timedelta

import pytest

from cemaf.core.utils import utc_now
from cemaf.scheduler.gates import (
    ExecutionGate,
    GateResult,
    LockGate,
    SessionCountGate,
    TimeGate,
    evaluate_gates,
)

# ---------------------------------------------------------------------------
# Contract tests — ExecutionGate protocol compliance
# ---------------------------------------------------------------------------


class TestExecutionGateProtocol:
    """Any gate implementation must satisfy the ExecutionGate protocol."""

    def test_time_gate_satisfies_protocol(self) -> None:
        gate = TimeGate(min_interval=timedelta(hours=1))
        assert isinstance(gate, ExecutionGate)

    def test_session_count_gate_satisfies_protocol(self) -> None:
        gate = SessionCountGate(min_sessions=5)
        assert isinstance(gate, ExecutionGate)

    def test_lock_gate_satisfies_protocol(self) -> None:
        gate = LockGate()
        assert isinstance(gate, ExecutionGate)

    def test_structural_typing_custom_gate(self) -> None:
        """A plain class with name + evaluate satisfies the protocol."""

        class CustomGate:
            @property
            def name(self) -> str:
                return "custom"

            async def evaluate(self) -> GateResult:
                return GateResult.allow(gate_name="custom")

        assert isinstance(CustomGate(), ExecutionGate)


# ---------------------------------------------------------------------------
# GateResult
# ---------------------------------------------------------------------------


class TestGateResult:
    def test_allow(self) -> None:
        result = GateResult.allow(gate_name="test")
        assert result.passed is True
        assert result.gate_name == "test"

    def test_deny(self) -> None:
        result = GateResult.deny(gate_name="test", reason="not ready")
        assert result.passed is False
        assert result.reason == "not ready"

    def test_frozen(self) -> None:
        result = GateResult.allow(gate_name="test")
        with pytest.raises(AttributeError):
            result.passed = False  # type: ignore[misc]


# ---------------------------------------------------------------------------
# TimeGate
# ---------------------------------------------------------------------------


class TestTimeGate:
    @pytest.mark.asyncio
    async def test_passes_when_never_executed(self) -> None:
        gate = TimeGate(min_interval=timedelta(hours=24))
        result = await gate.evaluate()
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_fails_when_recently_executed(self) -> None:
        gate = TimeGate(
            min_interval=timedelta(hours=24),
            last_execution=utc_now(),
        )
        result = await gate.evaluate()
        assert result.passed is False
        assert "remaining" in result.reason

    @pytest.mark.asyncio
    async def test_passes_when_interval_elapsed(self) -> None:
        gate = TimeGate(
            min_interval=timedelta(seconds=1),
            last_execution=utc_now() - timedelta(seconds=2),
        )
        result = await gate.evaluate()
        assert result.passed is True

    def test_record_execution_updates_timestamp(self) -> None:
        gate = TimeGate(min_interval=timedelta(hours=1))
        assert gate._last_execution is None
        gate.record_execution()
        assert gate._last_execution is not None

    def test_name(self) -> None:
        gate = TimeGate(min_interval=timedelta(hours=1))
        assert gate.name == "time_gate"


# ---------------------------------------------------------------------------
# SessionCountGate
# ---------------------------------------------------------------------------


class TestSessionCountGate:
    @pytest.mark.asyncio
    async def test_fails_when_below_threshold(self) -> None:
        gate = SessionCountGate(min_sessions=5, current_count=3)
        result = await gate.evaluate()
        assert result.passed is False
        assert "3/5" in result.reason

    @pytest.mark.asyncio
    async def test_passes_when_at_threshold(self) -> None:
        gate = SessionCountGate(min_sessions=5, current_count=5)
        result = await gate.evaluate()
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_passes_when_above_threshold(self) -> None:
        gate = SessionCountGate(min_sessions=5, current_count=10)
        result = await gate.evaluate()
        assert result.passed is True

    def test_increment(self) -> None:
        gate = SessionCountGate(min_sessions=5, current_count=0)
        gate.increment()
        gate.increment()
        assert gate._current_count == 2

    def test_reset(self) -> None:
        gate = SessionCountGate(min_sessions=5, current_count=5)
        gate.reset()
        assert gate._current_count == 0

    def test_name(self) -> None:
        gate = SessionCountGate(min_sessions=1)
        assert gate.name == "session_count_gate"


# ---------------------------------------------------------------------------
# LockGate
# ---------------------------------------------------------------------------


class TestLockGate:
    @pytest.mark.asyncio
    async def test_passes_when_unlocked(self) -> None:
        gate = LockGate()
        result = await gate.evaluate()
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_fails_when_locked(self) -> None:
        gate = LockGate()
        acquired = await gate.acquire()
        assert acquired is True

        result = await gate.evaluate()
        assert result.passed is False
        assert "in progress" in result.reason

        gate.release()

    @pytest.mark.asyncio
    async def test_passes_after_release(self) -> None:
        gate = LockGate()
        await gate.acquire()
        gate.release()

        result = await gate.evaluate()
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_acquire_fails_when_already_locked(self) -> None:
        gate = LockGate()
        await gate.acquire()
        second = await gate.acquire()
        assert second is False
        gate.release()

    def test_name(self) -> None:
        gate = LockGate()
        assert gate.name == "lock_gate"


# ---------------------------------------------------------------------------
# evaluate_gates (AND composition)
# ---------------------------------------------------------------------------


class TestEvaluateGates:
    @pytest.mark.asyncio
    async def test_all_pass(self) -> None:
        gates = (
            TimeGate(min_interval=timedelta(hours=1)),  # never run = pass
            SessionCountGate(min_sessions=1, current_count=5),
        )
        result = await evaluate_gates(gates=gates)
        assert result.all_passed is True
        assert len(result.results) == 2
        assert len(result.failed_gates) == 0

    @pytest.mark.asyncio
    async def test_one_fails_blocks_all(self) -> None:
        gates = (
            TimeGate(min_interval=timedelta(hours=1)),  # pass
            SessionCountGate(min_sessions=10, current_count=1),  # fail
        )
        result = await evaluate_gates(gates=gates)
        assert result.all_passed is False
        assert len(result.failed_gates) == 1
        assert result.failed_gates[0].gate_name == "session_count_gate"

    @pytest.mark.asyncio
    async def test_empty_gates_pass(self) -> None:
        result = await evaluate_gates(gates=())
        assert result.all_passed is True
        assert len(result.results) == 0

    @pytest.mark.asyncio
    async def test_three_gate_trigger(self) -> None:
        """Full three-gate system: time + session + lock — all pass."""
        gates = (
            TimeGate(
                min_interval=timedelta(hours=24),
                last_execution=utc_now() - timedelta(hours=25),
            ),
            SessionCountGate(min_sessions=5, current_count=7),
            LockGate(),
        )
        result = await evaluate_gates(gates=gates)
        assert result.all_passed is True
        assert len(result.results) == 3

"""Execution gates — composable preconditions for autonomous agent execution.

Inspired by Claude Code's three-gate trigger system (time + session + lock).
Gates are Protocol-based, composable via AND logic, and fully injectable.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Protocol, runtime_checkable

from cemaf.core.provider_registry import ProviderRegistry
from cemaf.core.utils import utc_now

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GateResult:
    """Result of evaluating an execution gate."""

    passed: bool
    gate_name: str
    reason: str = ""

    @classmethod
    def allow(cls, *, gate_name: str) -> GateResult:
        return cls(passed=True, gate_name=gate_name)

    @classmethod
    def deny(cls, *, gate_name: str, reason: str) -> GateResult:
        return cls(passed=False, gate_name=gate_name, reason=reason)


@runtime_checkable
class ExecutionGate(Protocol):
    """Protocol for execution preconditions — structural typing, BYO gate."""

    @property
    def name(self) -> str:
        """Human-readable gate name."""
        ...

    async def evaluate(self) -> GateResult:
        """Check if the gate allows execution."""
        ...


class TimeGate:
    """Gate that opens after a minimum interval since last execution."""

    def __init__(self, *, min_interval: timedelta, last_execution: datetime | None = None) -> None:
        self._min_interval = min_interval
        self._last_execution = last_execution

    @property
    def name(self) -> str:
        return "time_gate"

    def record_execution(self) -> None:
        """Record that execution happened now."""
        self._last_execution = utc_now()

    async def evaluate(self) -> GateResult:
        if self._last_execution is None:
            return GateResult.allow(gate_name=self.name)
        elapsed = utc_now() - self._last_execution
        if elapsed >= self._min_interval:
            return GateResult.allow(gate_name=self.name)
        remaining = self._min_interval - elapsed
        return GateResult.deny(
            gate_name=self.name,
            reason=f"{remaining.total_seconds():.0f}s remaining until next allowed execution",
        )


class SessionCountGate:
    """Gate that opens after N sessions have occurred."""

    def __init__(self, *, min_sessions: int, current_count: int = 0) -> None:
        self._min_sessions = min_sessions
        self._current_count = current_count

    @property
    def name(self) -> str:
        return "session_count_gate"

    def increment(self) -> None:
        """Record a session completion."""
        self._current_count += 1

    def reset(self) -> None:
        """Reset counter after gate passes."""
        self._current_count = 0

    async def evaluate(self) -> GateResult:
        if self._current_count >= self._min_sessions:
            return GateResult.allow(gate_name=self.name)
        return GateResult.deny(
            gate_name=self.name,
            reason=f"{self._current_count}/{self._min_sessions} sessions completed",
        )


class LockGate:
    """Gate that ensures only one execution at a time via async lock."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()

    @property
    def name(self) -> str:
        return "lock_gate"

    async def evaluate(self) -> GateResult:
        if self._lock.locked():
            return GateResult.deny(
                gate_name=self.name,
                reason="Another execution is in progress",
            )
        return GateResult.allow(gate_name=self.name)

    async def acquire(self) -> bool:
        """Acquire the lock for execution (non-blocking)."""
        if self._lock.locked():
            return False
        await self._lock.acquire()
        return True

    def release(self) -> None:
        """Release the lock after execution."""
        if self._lock.locked():
            self._lock.release()


@dataclass(frozen=True)
class CompositeGateResult:
    """Result of evaluating multiple gates."""

    all_passed: bool
    results: tuple[GateResult, ...] = field(default_factory=tuple)

    @property
    def failed_gates(self) -> tuple[GateResult, ...]:
        return tuple(r for r in self.results if not r.passed)


async def evaluate_gates(*, gates: tuple[ExecutionGate, ...]) -> CompositeGateResult:
    """Evaluate all gates with AND logic — all must pass."""
    results: list[GateResult] = []
    for gate in gates:
        result = await gate.evaluate()
        results.append(result)
    all_passed = all(r.passed for r in results)
    return CompositeGateResult(all_passed=all_passed, results=tuple(results))


execution_gate_registry: ProviderRegistry[ExecutionGate] = ProviderRegistry(name="execution_gate")


def _coerce_timedelta(value: timedelta | float | int | str | None, *, default_seconds: float) -> timedelta:
    if value is None:
        return timedelta(seconds=default_seconds)
    if isinstance(value, timedelta):
        return value
    return timedelta(seconds=float(value))


def _create_time_gate(**kwargs: Any) -> ExecutionGate:
    interval = _coerce_timedelta(
        kwargs.get("min_interval") or kwargs.get("min_interval_seconds"),
        default_seconds=86_400.0,
    )
    return TimeGate(
        min_interval=interval,
        last_execution=kwargs.get("last_execution"),
    )


def _create_session_count_gate(**kwargs: Any) -> ExecutionGate:
    return SessionCountGate(
        min_sessions=int(kwargs.get("min_sessions", 1)),
        current_count=int(kwargs.get("current_count", 0)),
    )


def _create_lock_gate(**kwargs: Any) -> ExecutionGate:
    return LockGate()


execution_gate_registry.register(backend="time", factory=_create_time_gate)
execution_gate_registry.register(backend="time_gate", factory=_create_time_gate)
execution_gate_registry.register(backend="session_count", factory=_create_session_count_gate)
execution_gate_registry.register(backend="session_count_gate", factory=_create_session_count_gate)
execution_gate_registry.register(backend="lock", factory=_create_lock_gate)
execution_gate_registry.register(backend="lock_gate", factory=_create_lock_gate)


def create_execution_gate(
    gate_type: str,
    **gate_options: Any,
) -> ExecutionGate:
    """Create an execution gate through the registry."""
    return execution_gate_registry.create(backend=gate_type, **gate_options)


def create_execution_gates(
    gate_specs: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
) -> tuple[ExecutionGate, ...]:
    """Create execution gates from declarative specs."""
    gates: list[ExecutionGate] = []
    for spec in gate_specs or ():
        spec_copy = dict(spec)
        gate_type = str(spec_copy.pop("type", spec_copy.pop("gate_type", "")))
        if not gate_type:
            raise ValueError("Execution gate spec requires 'type' or 'gate_type'.")
        gates.append(create_execution_gate(gate_type, **spec_copy))
    return tuple(gates)

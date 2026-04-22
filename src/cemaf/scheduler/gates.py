"""Execution gates — composable preconditions for autonomous agent execution.

Inspired by Claude Code's three-gate trigger system (time + session + lock).
Gates are Protocol-based, composable via AND logic, and fully injectable.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Protocol, runtime_checkable

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

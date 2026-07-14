"""Dreaming-mode composition built on the scheduler primitives."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from cemaf.agents.base import AgentContext
from cemaf.core.types import JSON
from cemaf.core.utils import generate_id, safe_json
from cemaf.memory.manager import MemoryManager
from cemaf.meta.agents import DreamAgent
from cemaf.meta.goals import DreamGoal
from cemaf.scheduler.gates import ExecutionGate, LockGate, SessionCountGate, TimeGate
from cemaf.scheduler.nightshift import NightShiftGate, NightShiftTrigger, NightShiftWindow
from cemaf.scheduler.primitives import JobDefinition, JobKind
from cemaf.scheduler.protocols import Trigger
from cemaf.scheduler.triggers import IntervalTrigger


@dataclass(frozen=True)
class DreamingModeHandle:
    """Materialized dreaming-mode job plus its mutable execution gates."""

    definition: JobDefinition
    handler: Callable[[], Awaitable[JSON]]
    gates: tuple[ExecutionGate, ...]
    time_gate: TimeGate | None = None
    session_gate: SessionCountGate | None = None
    lock_gate: LockGate | None = None

    def record_session(self, count: int = 1) -> None:
        """Advance the session-count gate used by dreaming mode."""
        if self.session_gate is None:
            return
        for _ in range(max(0, count)):
            self.session_gate.increment()

    def record_execution(self) -> None:
        """Advance the time gate after a successful dream cycle."""
        if self.time_gate is not None:
            self.time_gate.record_execution()


@dataclass(frozen=True)
class DreamingMode:
    """High-level builder for recurring autonomous DreamAgent runs."""

    job_id: str = "dreaming_mode"
    job_name: str = "Dreaming Mode"
    goal: DreamGoal = field(default_factory=DreamGoal)
    trigger: Trigger = field(default_factory=lambda: IntervalTrigger(hours=1, name="dreaming.interval"))
    min_interval: timedelta | None = timedelta(hours=4)
    min_sessions: int | None = None
    use_lock_gate: bool = True
    nightshift: NightShiftWindow | None = None
    metadata: JSON = field(default_factory=dict)

    def create_job_definition(self) -> JobDefinition:
        """Build the managed-job definition for this dreaming mode."""
        effective_trigger = self.trigger
        tags = ["dream"]
        if self.nightshift is not None:
            effective_trigger = NightShiftTrigger(
                base_trigger=self.trigger,
                window=self.nightshift,
                name=f"{self.job_id}.nightshift",
            )
            tags.append("nightshift")
        return JobDefinition(
            id=self.job_id,
            name=self.job_name,
            trigger=effective_trigger,
            kind=JobKind.DREAM,
            tags=tuple(tags),
            metadata=safe_json(
                {
                    **self.metadata,
                    "dream_goal": self.goal.model_dump(),
                }
            ),
        )

    def build(
        self,
        *,
        memory_manager: MemoryManager,
        current_sessions: int = 0,
        last_execution: datetime | None = None,
    ) -> DreamingModeHandle:
        """Materialize a dreaming-mode job and its reusable gates."""
        time_gate = (
            TimeGate(min_interval=self.min_interval, last_execution=last_execution)
            if self.min_interval is not None
            else None
        )
        session_gate = (
            SessionCountGate(min_sessions=self.min_sessions, current_count=current_sessions)
            if self.min_sessions is not None
            else None
        )
        lock_gate = LockGate() if self.use_lock_gate else None
        gates: list[ExecutionGate] = []
        if time_gate is not None:
            gates.append(time_gate)
        if session_gate is not None:
            gates.append(session_gate)
        if lock_gate is not None:
            gates.append(lock_gate)
        if self.nightshift is not None:
            gates.append(NightShiftGate(window=self.nightshift))

        dream_agent = DreamAgent(
            memory_manager=memory_manager,
            gates=tuple(gates),
        )
        definition = self.create_job_definition()

        async def handler() -> JSON:
            result = await dream_agent.run(
                goal=self.goal,
                context=AgentContext(
                    run_id=generate_id("dream"),
                    agent_id="MetaDream",
                ),
            )
            if not result.success or result.output is None:
                raise RuntimeError(result.error or "Dreaming mode failed")

            output: Any = safe_json(result.output.model_dump())
            if not isinstance(output, dict):
                raise RuntimeError("Dreaming mode produced a non-dict payload")

            if result.output.consolidated_count > 0:
                if time_gate is not None:
                    time_gate.record_execution()
                if session_gate is not None:
                    session_gate.reset()
            return output

        return DreamingModeHandle(
            definition=definition,
            handler=handler,
            gates=tuple(gates),
            time_gate=time_gate,
            session_gate=session_gate,
            lock_gate=lock_gate,
        )

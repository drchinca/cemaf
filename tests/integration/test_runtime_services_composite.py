"""Real local composite proof for the RuntimeServices execution root.

This deliberately crosses subsystem boundaries in one run. It is not a set of
isolated component assertions: SQLite-backed semantic memory is recalled and
compiled into the agent context, an eval gate forces a paid recovery attempt,
moderation accepts only the corrected result, the session stores only that
accepted result, and the resulting context replays exactly from audit patches.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from cemaf.agents.base import AgentContext, AgentResult, AgentState
from cemaf.agents.registry import AgentRegistry
from cemaf.bootstrap import create_executor
from cemaf.context.budget import TokenBudget
from cemaf.context.compiler import PriorityContextCompiler, SimpleTokenEstimator
from cemaf.core.enums import MemoryBackend, MemoryScope, RunStatus
from cemaf.core.types import AgentID, NodeID, RunID
from cemaf.evals.evaluators import LengthEvaluator
from cemaf.events.bus import InMemoryEventBus
from cemaf.events.protocols import Event, EventType
from cemaf.interceptors import GateEvalInterceptor, GateFailureMode, create_interceptor_pipeline
from cemaf.interceptors.types import RECOVERY_HINTS_KEY
from cemaf.memory.factories import create_memory_runtime
from cemaf.moderation.factories import create_keyword_moderation_pipeline
from cemaf.observability.budget_guard import BudgetGuard
from cemaf.observability.run_logger import InMemoryRunLogger
from cemaf.orchestration.dag import DAG, Node
from cemaf.orchestration.executor import ExecutorConfig
from cemaf.orchestration.services import RuntimeServices
from cemaf.replay.replayer import Replayer, ReplayMode


class _CompositeGoal(BaseModel):
    objective: str


class _RecoveringAgent:
    def __init__(self) -> None:
        self.contexts: list[AgentContext] = []

    @property
    def id(self) -> AgentID:
        return AgentID("CompositeWriter")

    @property
    def description(self) -> str:
        return "Revises a draft after bounded evaluator feedback"

    @property
    def skills(self) -> tuple[()]:
        return ()

    async def run(self, goal: _CompositeGoal, context: AgentContext) -> AgentResult[str]:
        self.contexts.append(context)
        hints = context.global_memory.get(RECOVERY_HINTS_KEY, [])
        if hints:
            return AgentResult.ok(
                output=(
                    "Accepted durable-worker design: workers are disposable; authority, "
                    "lineage, checkpoints, fencing, replay, and healing remain external. "
                    "A replacement worker resumes from the same durable state safely."
                ),
                state=AgentState(),
                metadata={"cost_estimate_usd": 0.02, "tokens_total": 200},
            )
        return AgentResult.ok(
            output="too short",
            state=AgentState(),
            metadata={"cost_estimate_usd": 0.01, "tokens_total": 100},
        )


class _RecordingSessionManager:
    """Thin observer around the real session manager; behavior still delegates."""

    def __init__(self, delegate: Any) -> None:
        self._delegate = delegate
        self.ingested: list[tuple[str, str, Any]] = []

    async def bootstrap(self, session_id: str, **kwargs: Any) -> Any:
        return await self._delegate.bootstrap(session_id=session_id, **kwargs)

    async def ingest(self, session_id: str, key: str, value: Any, **kwargs: Any) -> Any:
        self.ingested.append((session_id, key, value))
        return await self._delegate.ingest(session_id=session_id, key=key, value=value, **kwargs)

    async def dispose(self, session_id: str, **kwargs: Any) -> Any:
        return await self._delegate.dispose(session_id=session_id, **kwargs)


@pytest.mark.asyncio
async def test_real_runtime_root_crosses_memory_context_recovery_safety_audit_and_replay(
    tmp_path: Path,
) -> None:
    bus = InMemoryEventBus()
    events: list[Event] = []

    async def capture(event: Event) -> None:
        events.append(event)

    bus.subscribe_all(capture)
    memory = create_memory_runtime(
        event_bus=bus,
        memory_backend=MemoryBackend.SQLITE,
        vector_backend="sqlite",
        embedding_provider_name="hash",
        embedding_dimension=32,
        db_path=str(tmp_path / "composite.sqlite3"),
    )
    await memory.memory_manager.remember(
        scope=MemoryScope.PROJECT,
        key="operating_rule",
        value="workers disposable; durable authority external",
        content_for_embedding="durable worker authority checkpoints replay fencing",
    )

    agent = _RecoveringAgent()
    registry = AgentRegistry()
    registry.register_agent(agent_instance=agent, goal_type=_CompositeGoal)

    interceptor_pipeline = create_interceptor_pipeline(
        interceptors=(
            GateEvalInterceptor(
                evaluators=(LengthEvaluator(min_length=100),),
                node_pattern="write",
                threshold=0.5,
                on_failure=GateFailureMode.RECOVER,
            ),
        )
    )
    sessions = _RecordingSessionManager(memory.session_manager)
    run_logger = InMemoryRunLogger()
    guard = BudgetGuard(max_cost_usd=1.0, max_total_tokens=10_000)
    estimator = SimpleTokenEstimator(chars_per_token=3.5)
    services = RuntimeServices(
        run_logger=run_logger,
        event_bus=bus,
        budget_guard=guard,
        memory_manager=memory.memory_manager,
        session_manager=sessions,  # type: ignore[arg-type]
        context_compiler=PriorityContextCompiler(token_estimator=estimator),
        token_budget=TokenBudget(max_tokens=120, reserved_for_output=30),
        interceptor_pipeline=interceptor_pipeline,
        max_recovery_attempts=2,
        moderation_pipeline=create_keyword_moderation_pipeline(blocked_words=("FORBIDDEN",), event_bus=bus),
    )
    executor = create_executor(
        agent_registry=registry,
        config=ExecutorConfig(enable_events=True, enable_logging=True, enable_moderation=True),
        services=services,
    )
    node = Node.agent(
        id="write",
        name="write",
        agent_id="CompositeWriter",
        input_mapping={"objective": "design durable disposable workers"},
        output_key="design",
    )
    run = await executor.run(
        dag=DAG(name="real-composite", nodes=(node,), edges=(), entry_node=NodeID("write")),
        run_id=RunID("real-composite-run"),
    )
    await asyncio.sleep(0)  # allow moderation's observable event tasks to publish

    assert run.status == RunStatus.COMPLETED
    assert len(agent.contexts) == 2
    assert all("operating_rule" in context.global_memory for context in agent.contexts)
    compiled_messages = agent.contexts[-1].artifacts["compiled_context"]
    compiled_text = "\n".join(str(message["content"]) for message in compiled_messages)
    assert "operating_rule" in compiled_text
    assert "design durable disposable workers" in compiled_text
    assert estimator.estimate(compiled_text) <= services.token_budget.available_tokens  # type: ignore[union-attr]
    assert agent.contexts[-1].global_memory[RECOVERY_HINTS_KEY][0]["code"] == "length"

    node_result = run.node_results[0]
    assert node_result.success
    assert node_result.metadata["recovery_attempts"] == 1
    assert node_result.metadata["cost_estimate_usd"] == pytest.approx(0.03)
    assert node_result.metadata["tokens_total"] == 300
    assert node_result.metadata["_moderation_checked"] is True
    assert guard.accumulated_cost_usd == pytest.approx(0.03)
    assert guard.accumulated_tokens == 300
    assert run.final_context is not None
    assert run.final_context.get("design") == node_result.output
    assert len(run.final_context.patch_history) == 1

    # Only the accepted recovery result reaches session memory; the short draft does not.
    assert len(sessions.ingested) == 1
    assert sessions.ingested[0][1] == "CompositeWriter_output"
    assert sessions.ingested[0][2]["output"] == node_result.output

    record = run_logger.get_record("real-composite-run")
    assert record is not None
    assert record.provenance_chain is not None
    assert len(record.provenance_chain.links) == 2
    assert len(record.patches) == 1
    replay = await Replayer(record).replay(mode=ReplayMode.PATCH_ONLY)
    assert replay.success
    assert replay.final_context.data == run.final_context.data

    node_events = [event for event in events if event.payload.get("node_id") == "write"]
    completed = [event for event in node_events if event.type == EventType.TASK_COMPLETED]
    assert len(completed) == 1
    assert completed[0].payload["recovery_attempts"] == 1
    assert not any(event.type == EventType.TASK_FAILED for event in node_events)
    assert any(event.type == EventType.MODERATION_CHECK_PASSED for event in events)

    # The durable project memory survived the disposable run/session lifecycle.
    persisted = await memory.memory_manager.recall_by_key(scope=MemoryScope.PROJECT, key="operating_rule")
    assert persisted is not None

    await memory.vector_store.close()  # type: ignore[attr-defined]
    await memory.memory_store.close()  # type: ignore[attr-defined]

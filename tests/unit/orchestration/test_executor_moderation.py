"""Regression tests — ModerationPipeline must actually run on node outputs.

Before the fix, DAGExecutor accepted `moderation_pipeline` and stored it but
never called check_input/check_output. Configured safety was theater.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel

from cemaf.agents.base import Agent, AgentContext, AgentResult, AgentState
from cemaf.agents.registry import AgentRegistry
from cemaf.bootstrap import create_executor
from cemaf.core.enums import NodeType, RunStatus
from cemaf.core.types import AgentID, NodeID
from cemaf.events.bus import InMemoryEventBus
from cemaf.events.protocols import Event, EventType
from cemaf.moderation.pipeline import ModerationPipeline
from cemaf.moderation.protocols import (
    ModerationContent,
    ModerationResult,
    ModerationViolation,
)
from cemaf.orchestration.dag import DAG, Node
from cemaf.orchestration.executor import ExecutorConfig
from cemaf.orchestration.services import RuntimeServices


class _EchoGoal(BaseModel):
    payload: str


class _EchoResult(BaseModel):
    text: str


class _EchoAgent(Agent[_EchoGoal, _EchoResult]):
    @property
    def id(self) -> AgentID:
        return AgentID("Echo")

    @property
    def description(self) -> str:
        return "Echoes its input payload back as output"

    @property
    def skills(self) -> tuple[()]:
        return ()

    async def run(self, goal: _EchoGoal, context: AgentContext) -> AgentResult[_EchoResult]:
        return AgentResult.ok(output=_EchoResult(text=goal.payload), state=AgentState())


class _KeywordBlockGate:
    """Test gate: block output containing the phrase 'BLOCKED'."""

    def __init__(self) -> None:
        self._name = "keyword_block"

    @property
    def name(self) -> str:
        return self._name

    async def check(
        self,
        content: ModerationContent,
        context: Any | None = None,
    ) -> ModerationResult:
        text = content if isinstance(content, str) else str(content)
        if "BLOCKED" in text:
            return ModerationResult.blocked(
                violations=(
                    ModerationViolation(
                        code="keyword.forbidden",
                        message="Output contains forbidden keyword",
                        severity="error",
                    ),
                )
            )
        return ModerationResult.success()


def _single_node_dag(*, payload: str) -> DAG:
    node = Node(
        id=NodeID("n1"),
        type=NodeType.AGENT,
        name="echo",
        ref_id="Echo",
        input_mapping={"payload": payload},
        output_key="echo_out",
        retry_on_failure=False,
    )
    return DAG(name="mod-test", nodes=(node,), edges=(), entry_node=node.id)


def _registry() -> AgentRegistry:
    registry = AgentRegistry()
    registry.register_agent(agent_instance=_EchoAgent(), goal_type=_EchoGoal)
    return registry


@pytest.mark.asyncio
async def test_clean_output_is_allowed() -> None:
    pipeline = ModerationPipeline(post_flight=_KeywordBlockGate())
    executor = create_executor(
        agent_registry=_registry(),
        config=ExecutorConfig(enable_events=False, enable_moderation=True),
        services=RuntimeServices(moderation_pipeline=pipeline),
    )
    result = await executor.run(dag=_single_node_dag(payload="a clean response"))
    assert result.status == RunStatus.COMPLETED
    assert result.node_results[0].success is True


@pytest.mark.asyncio
async def test_blocked_output_fails_node_and_dag() -> None:
    """Blocked content never reaches context, memory, or a success event."""
    ingested: list[tuple[str, str, Any]] = []
    events: list[Event] = []

    class _RecordingSessions:
        async def bootstrap(self, session_id: str) -> None:
            return None

        async def ingest(self, session_id: str, key: str, value: Any, **kwargs: Any) -> None:
            ingested.append((session_id, key, value))

        async def dispose(self, session_id: str) -> None:
            return None

    async def capture(event: Event) -> None:
        events.append(event)

    bus = InMemoryEventBus()
    bus.subscribe_all(capture)
    pipeline = ModerationPipeline(post_flight=_KeywordBlockGate())
    executor = create_executor(
        agent_registry=_registry(),
        config=ExecutorConfig(enable_events=True, enable_moderation=True),
        services=RuntimeServices(
            moderation_pipeline=pipeline,
            session_manager=_RecordingSessions(),  # type: ignore[arg-type]
            event_bus=bus,
        ),
    )
    result = await executor.run(dag=_single_node_dag(payload="this is BLOCKED content"))
    node_result = result.node_results[0]
    assert node_result.success is False
    assert "moderation" in (node_result.error or "").lower()
    assert node_result.metadata.get("moderation_blocked") is True
    assert "keyword.forbidden" in node_result.metadata.get("moderation_violations", [])
    assert result.final_context is not None
    assert result.final_context.get("echo_out") is None
    assert result.final_context.patch_history == ()
    assert ingested == []
    node_events = [event for event in events if event.payload.get("node_id") == "n1"]
    assert not any(event.type == EventType.TASK_COMPLETED for event in node_events)
    assert any(event.type == EventType.TASK_FAILED for event in node_events)


@pytest.mark.asyncio
async def test_no_pipeline_configured_is_passthrough() -> None:
    executor = create_executor(
        agent_registry=_registry(),
        config=ExecutorConfig(enable_events=False),
        services=RuntimeServices(),
    )
    result = await executor.run(dag=_single_node_dag(payload="anything BLOCKED goes"))
    assert result.status == RunStatus.COMPLETED
    assert result.node_results[0].success is True

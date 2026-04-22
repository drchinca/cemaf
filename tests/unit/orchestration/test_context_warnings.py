"""Regression tests — failures in memory recall / context compile / session
ingest must surface to NodeResult.metadata['context_warnings'] instead of
being silently swallowed.

Before the fix, ContextNodeExecutor had three `except Exception: logger.warning;
return {}` paths. Agents ran with empty context and hallucinated; nobody knew.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel

from cemaf.agents.base import Agent, AgentContext, AgentResult, AgentState
from cemaf.agents.registry import AgentRegistry
from cemaf.bootstrap import create_executor
from cemaf.core.enums import MemoryScope, NodeType, RunStatus
from cemaf.core.types import AgentID, NodeID
from cemaf.memory.base import MemoryItem
from cemaf.memory.manager import MemoryManager
from cemaf.memory.semantic import MemoryQuery, MemorySearchResult
from cemaf.orchestration.dag import DAG, Node
from cemaf.orchestration.executor import ExecutorConfig
from cemaf.orchestration.services import RuntimeServices


class _PingGoal(BaseModel):
    topic: str = "anything"


class _PingResult(BaseModel):
    seen_memory: int


class _PingAgent(Agent[_PingGoal, _PingResult]):
    """Agent that reports how much global_memory it received."""

    @property
    def id(self) -> AgentID:
        return AgentID("Ping")

    @property
    def description(self) -> str:
        return "Reports len(context.global_memory) back to the caller"

    @property
    def skills(self) -> tuple[()]:
        return ()

    async def run(self, goal: _PingGoal, context: AgentContext) -> AgentResult[_PingResult]:
        return AgentResult.ok(
            output=_PingResult(seen_memory=len(context.global_memory)),
            state=AgentState(),
        )


class _ExplodingMemoryManager(MemoryManager):
    """MemoryManager that raises on recall — simulates backend outage."""

    async def remember(self, *args: Any, **kwargs: Any) -> MemoryItem:  # pragma: no cover
        raise NotImplementedError

    async def recall(self, query: MemoryQuery) -> tuple[MemorySearchResult, ...]:
        raise RuntimeError("vector store unavailable")

    async def recall_by_key(self, scope: MemoryScope, key: str) -> MemoryItem | None:  # pragma: no cover
        return None

    async def forget(self, scope: MemoryScope, key: str) -> bool:  # pragma: no cover
        return False

    async def start_episode(self, *args: Any, **kwargs: Any) -> Any:  # pragma: no cover
        raise NotImplementedError

    async def record_event(self, *args: Any, **kwargs: Any) -> None:  # pragma: no cover
        raise NotImplementedError

    async def end_episode(self, *args: Any, **kwargs: Any) -> Any:  # pragma: no cover
        raise NotImplementedError

    async def get_recent_history(self, *args: Any, **kwargs: Any) -> tuple[Any, ...]:  # pragma: no cover
        return ()

    async def cleanup(self) -> int:  # pragma: no cover
        return 0


def _single_node_dag() -> DAG:
    node = Node(
        id=NodeID("n1"),
        type=NodeType.AGENT,
        name="ping",
        ref_id="Ping",
        input_mapping={"topic": "x"},
        output_key="ping_out",
        retry_on_failure=False,
    )
    return DAG(name="ctx-warnings", nodes=(node,), edges=(), entry_node=node.id)


@pytest.mark.asyncio
async def test_memory_recall_failure_surfaces_as_context_warning() -> None:
    """Regression: exploding memory backend no longer silently returns {}."""
    registry = AgentRegistry()
    registry.register_agent(agent_instance=_PingAgent(), goal_type=_PingGoal)
    executor = create_executor(
        agent_registry=registry,
        config=ExecutorConfig(enable_events=False),
        services=RuntimeServices(memory_manager=_ExplodingMemoryManager()),
    )

    result = await executor.run(dag=_single_node_dag())

    assert result.status == RunStatus.COMPLETED  # agent still runs
    node_result = result.node_results[0]
    assert node_result.success is True
    warnings = node_result.metadata.get("context_warnings")
    assert warnings is not None, "context_warnings must surface in NodeResult.metadata"
    stages = {w["stage"] for w in warnings}
    assert "memory_recall" in stages
    recall_warning = next(w for w in warnings if w["stage"] == "memory_recall")
    assert recall_warning["error_type"] == "RuntimeError"
    assert "vector store unavailable" in recall_warning["error_message"]


@pytest.mark.asyncio
async def test_no_warnings_when_all_stages_succeed() -> None:
    """Happy path: no context_warnings key when nothing failed."""
    registry = AgentRegistry()
    registry.register_agent(agent_instance=_PingAgent(), goal_type=_PingGoal)
    executor = create_executor(
        agent_registry=registry,
        config=ExecutorConfig(enable_events=False),
        services=RuntimeServices(),  # no memory manager at all
    )
    result = await executor.run(dag=_single_node_dag())
    assert result.status == RunStatus.COMPLETED
    assert "context_warnings" not in result.node_results[0].metadata

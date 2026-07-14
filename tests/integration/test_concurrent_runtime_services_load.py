"""Concurrent composite load against shared durable local authority."""

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
from cemaf.memory.factories import MemoryRuntime, create_memory_runtime
from cemaf.memory.semantic import MemoryQuery
from cemaf.moderation.factories import create_keyword_moderation_pipeline
from cemaf.observability.budget_guard import BudgetGuard
from cemaf.observability.run_logger import InMemoryRunLogger
from cemaf.orchestration.dag import DAG, Node
from cemaf.orchestration.executor import ExecutorConfig
from cemaf.orchestration.services import RuntimeServices


class _LoadGoal(BaseModel):
    tag: str


class _LoadAgent:
    def __init__(self) -> None:
        self.contexts: list[AgentContext] = []

    @property
    def id(self) -> AgentID:
        return AgentID("LoadAgent")

    @property
    def description(self) -> str:
        return "Returns a run-specific value after consuming compiled durable context"

    @property
    def skills(self) -> tuple[()]:
        return ()

    async def run(self, goal: _LoadGoal, context: AgentContext) -> AgentResult[str]:
        await asyncio.sleep(0)
        self.contexts.append(context)
        return AgentResult.ok(
            output=f"accepted:{goal.tag}",
            state=AgentState(),
            metadata={"cost_estimate_usd": 0.001, "tokens_total": 10},
        )


class _IngestBarrier:
    """Hold disposal until every pipeline has persisted its identical key."""

    def __init__(self, *, parties: int, inspector: MemoryRuntime) -> None:
        self._parties = parties
        self._inspector = inspector
        self._arrivals = 0
        self._release = asyncio.Event()
        self.observed_counts: list[int] = []

    async def arrive(self) -> None:
        self._arrivals += 1
        if self._arrivals == self._parties:
            results = await self._inspector.memory_manager.recall(
                query=MemoryQuery(scope=MemoryScope.SESSION, limit=100)
            )
            self.observed_counts.append(len(results))
            self._release.set()
        await asyncio.wait_for(self._release.wait(), timeout=5)


class _BarrierSessionManager:
    def __init__(self, *, delegate: Any, barrier: _IngestBarrier) -> None:
        self._delegate = delegate
        self._barrier = barrier
        self.ingested: list[tuple[str, str, Any]] = []

    async def bootstrap(self, session_id: str, **kwargs: Any) -> Any:
        return await self._delegate.bootstrap(session_id=session_id, **kwargs)

    async def ingest(self, session_id: str, key: str, value: Any, **kwargs: Any) -> Any:
        item = await self._delegate.ingest(
            session_id=session_id,
            key=key,
            value=value,
            **kwargs,
        )
        self.ingested.append((session_id, key, value))
        await self._barrier.arrive()
        return item

    async def dispose(self, session_id: str, **kwargs: Any) -> Any:
        return await self._delegate.dispose(session_id=session_id, **kwargs)


def _dag(tag: str) -> DAG:
    node = Node.agent(
        id="load",
        name="load",
        agent_id="LoadAgent",
        input_mapping={"tag": tag},
        output_key="result",
    )
    return DAG(name="concurrent-composite", nodes=(node,), edges=(), entry_node=NodeID("load"))


@pytest.mark.asyncio
async def test_three_runtime_roots_keep_identical_session_keys_isolated_under_load(
    tmp_path: Path,
) -> None:
    db_path = str(tmp_path / "shared-authority.sqlite3")
    runtimes = [
        create_memory_runtime(
            memory_backend=MemoryBackend.SQLITE,
            vector_backend="sqlite",
            embedding_provider_name="hash",
            embedding_dimension=32,
            db_path=db_path,
        )
        for _ in range(3)
    ]
    await runtimes[0].memory_manager.remember(
        scope=MemoryScope.PROJECT,
        key="durable_rule",
        value="session outputs must remain owned by their run",
        content_for_embedding="durable session ownership isolation",
    )

    agents = [_LoadAgent() for _ in runtimes]
    registries = [AgentRegistry() for _ in runtimes]
    for registry, agent in zip(registries, agents, strict=True):
        registry.register_agent(agent_instance=agent, goal_type=_LoadGoal)

    guards = [BudgetGuard(max_cost_usd=1.0, max_total_tokens=10_000) for _ in runtimes]
    all_ingests: list[_BarrierSessionManager] = []

    try:
        for wave in range(10):
            barrier = _IngestBarrier(parties=3, inspector=runtimes[0])
            sessions = [
                _BarrierSessionManager(delegate=runtime.session_manager, barrier=barrier)
                for runtime in runtimes
            ]
            all_ingests.extend(sessions)
            executors = []
            for runtime, registry, session_manager, guard in zip(
                runtimes, registries, sessions, guards, strict=True
            ):
                executors.append(
                    create_executor(
                        agent_registry=registry,
                        config=ExecutorConfig(
                            enable_events=False,
                            enable_logging=True,
                            enable_moderation=True,
                        ),
                        services=RuntimeServices(
                            run_logger=InMemoryRunLogger(),
                            budget_guard=guard,
                            memory_manager=runtime.memory_manager,
                            session_manager=session_manager,  # type: ignore[arg-type]
                            context_compiler=PriorityContextCompiler(
                                token_estimator=SimpleTokenEstimator(chars_per_token=3.5)
                            ),
                            token_budget=TokenBudget(max_tokens=100, reserved_for_output=20),
                            moderation_pipeline=create_keyword_moderation_pipeline(
                                blocked_words=("FORBIDDEN",)
                            ),
                        ),
                    )
                )

            results = await asyncio.gather(
                *(
                    executor.run(
                        dag=_dag(tag=f"wave-{wave}-pipeline-{index}"),
                        run_id=RunID(f"wave-{wave}-pipeline-{index}"),
                    )
                    for index, executor in enumerate(executors)
                )
            )

            assert barrier.observed_counts == [3]
            assert all(result.status == RunStatus.COMPLETED for result in results)
            for index, result in enumerate(results):
                expected = f"accepted:wave-{wave}-pipeline-{index}"
                assert result.final_context is not None
                assert result.final_context.get("result") == expected
                assert result.node_results[0].metadata["_moderation_checked"] is True

        assert sum(len(session.ingested) for session in all_ingests) == 30
        assert all(guard.accumulated_cost_usd == pytest.approx(0.01) for guard in guards)
        assert all(guard.accumulated_tokens == 100 for guard in guards)
        assert all(len(agent.contexts) == 10 for agent in agents)
        assert all(context.run_id for agent in agents for context in agent.contexts)
        assert all("durable_rule" in context.global_memory for agent in agents for context in agent.contexts)
        remaining_session = await runtimes[0].memory_manager.recall(
            query=MemoryQuery(scope=MemoryScope.SESSION, limit=100)
        )
        assert remaining_session == ()
    finally:
        for runtime in runtimes:
            await runtime.vector_store.close()  # type: ignore[attr-defined]
            await runtime.memory_store.close()  # type: ignore[attr-defined]

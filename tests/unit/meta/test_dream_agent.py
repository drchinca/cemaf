"""Tests for DreamAgent — autonomous memory consolidation (TDD).

Contract tests written before implementation per CEMAF testing discipline.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest

from cemaf.agents.base import Agent, AgentContext
from cemaf.core.enums import MemoryScope
from cemaf.meta.goals import DreamGoal, DreamResult
from cemaf.scheduler.gates import SessionCountGate, TimeGate

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeMemoryManager:
    """In-memory MemoryManager for testing DreamAgent."""

    def __init__(self, *, items: dict[str, dict[str, Any]] | None = None) -> None:
        self._items: dict[str, dict[str, Any]] = items or {}
        self._remembered: list[dict[str, Any]] = []
        self._forgotten: list[str] = []

    async def remember(
        self,
        scope: MemoryScope,
        key: str,
        value: Any,
        *,
        confidence: float = 1.0,
        content_for_embedding: str | None = None,
    ) -> Any:
        self._remembered.append({"scope": scope, "key": key, "value": value})
        return {"scope": scope.value, "key": key, "value": value}

    async def recall(self, query: Any) -> tuple[Any, ...]:
        # Mirror the real manager: recall returns MemorySearchResult wrapping
        # a MemoryItem, not a raw dict.
        from cemaf.core.enums import MemoryScope as _Scope
        from cemaf.core.types import Confidence
        from cemaf.memory.base import MemoryItem
        from cemaf.memory.semantic import MemorySearchResult

        results = []
        for rank, raw in enumerate(self._items.values()):
            item = MemoryItem(
                scope=_Scope.PROJECT,
                key=str(raw["key"]),
                value=raw["value"],
                confidence=Confidence(float(raw.get("confidence", 1.0))),
            )
            results.append(MemorySearchResult(item=item, similarity=1.0, combined_score=1.0, rank=rank))
        return tuple(results)

    async def recall_by_key(self, scope: MemoryScope, key: str) -> Any | None:
        return self._items.get(key)

    async def forget(self, scope: MemoryScope, key: str) -> bool:
        self._forgotten.append(key)
        return key in self._items

    async def start_episode(self, session_id: str) -> Any:
        return {"id": session_id}

    async def record_event(self, episode_id: str, event: Any) -> None:
        pass

    async def end_episode(self, episode_id: str) -> Any:
        return {"id": episode_id}

    async def get_recent_history(self, session_id: str, *, limit: int = 20) -> tuple[Any, ...]:
        return ()

    async def cleanup(self) -> int:
        return 0


# ---------------------------------------------------------------------------
# Contract tests — DreamAgent protocol compliance
# ---------------------------------------------------------------------------


class TestDreamAgentContract:
    """DreamAgent must be a standard CEMAF Agent[DreamGoal, DreamResult]."""

    def test_is_agent_instance(self) -> None:
        from cemaf.meta.agents import DreamAgent

        agent = DreamAgent(memory_manager=FakeMemoryManager())  # type: ignore[arg-type]
        assert isinstance(agent, Agent)

    def test_id(self) -> None:
        from cemaf.meta.agents import DreamAgent

        agent = DreamAgent(memory_manager=FakeMemoryManager())  # type: ignore[arg-type]
        assert agent.id == "MetaDream"

    def test_description_mentions_consolidation(self) -> None:
        from cemaf.meta.agents import DreamAgent

        agent = DreamAgent(memory_manager=FakeMemoryManager())  # type: ignore[arg-type]
        assert "consolidat" in agent.description.lower() or "dream" in agent.description.lower()


# ---------------------------------------------------------------------------
# DreamGoal / DreamResult models
# ---------------------------------------------------------------------------


class TestDreamModels:
    def test_dream_goal_defaults(self) -> None:
        goal = DreamGoal()
        assert goal.max_consolidations > 0

    def test_dream_result_fields(self) -> None:
        result = DreamResult(
            consolidated_count=3,
            pruned_count=1,
            summary="Consolidated 3 memories, pruned 1 stale entry",
        )
        assert result.consolidated_count == 3
        assert result.pruned_count == 1


# ---------------------------------------------------------------------------
# DreamAgent execution
# ---------------------------------------------------------------------------


class TestDreamAgentExecution:
    @pytest.mark.asyncio
    async def test_run_consolidates_memories(self) -> None:
        from cemaf.meta.agents import DreamAgent

        mm = FakeMemoryManager(
            items={
                "fact1": {"scope": "project", "key": "fact1", "value": "old data"},
                "fact2": {"scope": "project", "key": "fact2", "value": "stale data"},
            }
        )
        agent = DreamAgent(memory_manager=mm)  # type: ignore[arg-type]
        ctx = AgentContext(run_id="dream-run", agent_id="MetaDream")
        goal = DreamGoal()

        result = await agent.run(goal=goal, context=ctx)

        assert result.success
        assert isinstance(result.output, DreamResult)
        assert result.output.summary != ""

    @pytest.mark.asyncio
    async def test_consolidation_merges_duplicate_memories(self) -> None:
        """Real consolidation: duplicate-content items are merged away (store shrinks).

        This is the test the old tautology (consolidated_count = item_count)
        could never pass: two items with identical content must collapse to one,
        and consolidated_count must equal the number actually removed.
        """
        from cemaf.meta.agents import DreamAgent

        mm = FakeMemoryManager(
            items={
                "f1": {"key": "f1", "value": {"summary": "CEMAF self-hosts"}, "confidence": 0.6},
                "f2": {"key": "f2", "value": {"summary": "CEMAF self-hosts"}, "confidence": 0.9},
                "f3": {"key": "f3", "value": {"summary": "unique fact"}, "confidence": 1.0},
            }
        )
        agent = DreamAgent(memory_manager=mm)  # type: ignore[arg-type]
        ctx = AgentContext(run_id="dream-run", agent_id="MetaDream")

        result = await agent.run(goal=DreamGoal(), context=ctx)

        assert result.success
        # One redundant duplicate ("f1", the lower-confidence twin) was removed.
        assert result.output.consolidated_count == 1
        assert "f1" in mm._forgotten
        # The higher-confidence twin and the unique fact are NOT forgotten.
        assert "f2" not in mm._forgotten
        assert "f3" not in mm._forgotten

    @pytest.mark.asyncio
    async def test_consolidation_is_noop_when_all_unique(self) -> None:
        """No duplicates → nothing merged, nothing forgotten."""
        from cemaf.meta.agents import DreamAgent

        mm = FakeMemoryManager(
            items={
                "a": {"key": "a", "value": {"summary": "alpha"}, "confidence": 1.0},
                "b": {"key": "b", "value": {"summary": "beta"}, "confidence": 1.0},
            }
        )
        agent = DreamAgent(memory_manager=mm)  # type: ignore[arg-type]
        ctx = AgentContext(run_id="dream-run", agent_id="MetaDream")

        result = await agent.run(goal=DreamGoal(), context=ctx)

        assert result.success
        assert result.output.consolidated_count == 0
        assert mm._forgotten == []

    @pytest.mark.asyncio
    async def test_run_with_empty_memory(self) -> None:
        from cemaf.meta.agents import DreamAgent

        mm = FakeMemoryManager()
        agent = DreamAgent(memory_manager=mm)  # type: ignore[arg-type]
        ctx = AgentContext(run_id="dream-run", agent_id="MetaDream")
        goal = DreamGoal()

        result = await agent.run(goal=goal, context=ctx)

        assert result.success
        assert result.output.consolidated_count == 0

    @pytest.mark.asyncio
    async def test_run_with_gates_blocking(self) -> None:
        """DreamAgent respects execution gates — denied gates prevent execution."""
        from cemaf.meta.agents import DreamAgent

        mm = FakeMemoryManager()
        # Session gate requires 10 sessions but only 1 completed
        gates = (SessionCountGate(min_sessions=10, current_count=1),)
        agent = DreamAgent(memory_manager=mm, gates=gates)  # type: ignore[arg-type]
        ctx = AgentContext(run_id="dream-run", agent_id="MetaDream")
        goal = DreamGoal()

        result = await agent.run(goal=goal, context=ctx)

        assert result.success
        assert result.output.consolidated_count == 0
        assert "gate" in result.output.summary.lower()

    @pytest.mark.asyncio
    async def test_run_with_gates_passing(self) -> None:
        """DreamAgent executes when all gates pass."""
        from cemaf.meta.agents import DreamAgent

        mm = FakeMemoryManager(items={"fact1": {"scope": "project", "key": "fact1", "value": "data"}})
        gates = (
            TimeGate(min_interval=timedelta(hours=1)),  # never run = pass
            SessionCountGate(min_sessions=1, current_count=5),  # pass
        )
        agent = DreamAgent(memory_manager=mm, gates=gates)  # type: ignore[arg-type]
        ctx = AgentContext(run_id="dream-run", agent_id="MetaDream")
        goal = DreamGoal()

        result = await agent.run(goal=goal, context=ctx)

        assert result.success


# ---------------------------------------------------------------------------
# Dream DAG
# ---------------------------------------------------------------------------


class TestDreamDag:
    def test_dream_dag_structure(self) -> None:
        from cemaf.meta.dags import create_dream_dag

        dag = create_dream_dag()
        assert dag.validate_structure() is True
        assert dag.name == "dream"
        assert len(dag.nodes) == 1
        node = dag.nodes[0]
        assert node.ref_id == "MetaDream"

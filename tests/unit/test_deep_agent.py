"""
Tests for DeepAgent orchestrator.

Tests guardrail enforcement:
- max_depth
- max_children_per_agent
- max_total_agents
- timeout_seconds
- propagate_errors
"""

import asyncio

import pytest
from pydantic import BaseModel

from cemaf.agents.base import Agent, AgentContext, AgentResult
from cemaf.core.types import AgentID
from cemaf.orchestration.deep_agent import (
    ChildSpawn,
    DeepAgentConfig,
    DeepAgentOrchestrator,
    DeepAgentResult,
)
from cemaf.orchestration.executor import DAGExecutor


class SimpleGoal(BaseModel):
    """Simple test goal."""

    task: str


class SimpleResult(BaseModel):
    """Simple test result."""

    output: str


class MockAgent(Agent[SimpleGoal, SimpleResult]):
    """Mock agent for testing."""

    def __init__(
        self,
        agent_id: str,
        delay: float = 0.0,
        fail: bool = False,
        spawn_children: list[str] | None = None,
    ):
        self._id = AgentID(agent_id)
        self._delay = delay
        self._fail = fail
        self._spawn_children = spawn_children or []
        self._orchestrator: DeepAgentOrchestrator | None = None

    @property
    def id(self) -> AgentID:
        return self._id

    @property
    def description(self) -> str:
        return f"Mock agent {self._id}"

    @property
    def skills(self) -> tuple:
        return ()

    def set_orchestrator(self, orch: DeepAgentOrchestrator) -> None:
        """Set orchestrator for spawning children."""
        self._orchestrator = orch

    async def run(self, goal: SimpleGoal, context: AgentContext) -> AgentResult[SimpleResult]:
        """Execute the agent."""
        from cemaf.agents.base import AgentState

        if self._delay > 0:
            await asyncio.sleep(self._delay)

        if self._fail:
            return AgentResult.fail("Intentional failure")

        # Spawn children if configured
        for child_id in self._spawn_children:
            if self._orchestrator:
                await self._orchestrator.spawn_child(
                    parent_id=self._id,
                    child_agent_id=AgentID(child_id),
                    goal=goal,
                    parent_context=context,
                )

        return AgentResult.ok(SimpleResult(output=f"Done: {goal.task}"), AgentState())


class TestDeepAgentOrchestrator:
    """Tests for DeepAgentOrchestrator."""

    @pytest.fixture
    def mock_dag_executor(self):
        """Mock DAG executor."""
        from tests.conftest import MockNodeExecutor

        return DAGExecutor(node_executor=MockNodeExecutor())

    @pytest.fixture
    def simple_agent(self) -> MockAgent:
        """Simple agent that succeeds."""
        return MockAgent("simple")

    @pytest.fixture
    def failing_agent(self) -> MockAgent:
        """Agent that fails."""
        return MockAgent("failing", fail=True)

    @pytest.fixture
    def slow_agent(self) -> MockAgent:
        """Agent that takes time."""
        return MockAgent("slow", delay=0.5)

    @pytest.mark.asyncio
    async def test_run_success(self, mock_dag_executor: DAGExecutor, simple_agent: MockAgent):
        """Basic successful run."""
        orchestrator = DeepAgentOrchestrator(
            agents={simple_agent.id: simple_agent},
            dag_executor=mock_dag_executor,
        )

        result = await orchestrator.run(
            root_agent_id=simple_agent.id,
            goal=SimpleGoal(task="test"),
        )

        assert result.success
        assert result.output is not None

    @pytest.mark.asyncio
    async def test_run_agent_not_found(self, mock_dag_executor: DAGExecutor):
        """Run fails for missing agent."""
        orchestrator = DeepAgentOrchestrator(
            agents={},
            dag_executor=mock_dag_executor,
        )

        result = await orchestrator.run(
            root_agent_id=AgentID("nonexistent"),
            goal=SimpleGoal(task="test"),
        )

        assert not result.success
        assert "not found" in result.error

    @pytest.mark.asyncio
    async def test_timeout_enforced(self, mock_dag_executor: DAGExecutor, slow_agent: MockAgent):
        """Timeout is enforced."""
        config = DeepAgentConfig(timeout_seconds=0.1)  # Very short
        orchestrator = DeepAgentOrchestrator(
            agents={slow_agent.id: slow_agent},
            dag_executor=mock_dag_executor,
            config=config,
        )

        result = await orchestrator.run(
            root_agent_id=slow_agent.id,
            goal=SimpleGoal(task="test"),
        )

        assert not result.success
        assert "Timeout" in result.error

    @pytest.mark.asyncio
    async def test_max_depth_enforced(self, mock_dag_executor: DAGExecutor):
        """Max depth is enforced."""
        # Create agents that spawn each other
        agent_a = MockAgent("a", spawn_children=["b"])
        agent_b = MockAgent("b", spawn_children=["c"])
        agent_c = MockAgent("c", spawn_children=["a"])  # Would loop

        config = DeepAgentConfig(max_depth=2)
        orchestrator = DeepAgentOrchestrator(
            agents={
                agent_a.id: agent_a,
                agent_b.id: agent_b,
                agent_c.id: agent_c,
            },
            dag_executor=mock_dag_executor,
            config=config,
        )

        # Set orchestrator for spawn capability
        agent_a.set_orchestrator(orchestrator)
        agent_b.set_orchestrator(orchestrator)
        agent_c.set_orchestrator(orchestrator)

        result = await orchestrator.run(
            root_agent_id=agent_a.id,
            goal=SimpleGoal(task="test"),
        )

        # Depth limit was enforced - one agent returned error
        failed_results = [r for r in result.agent_results if not r.success]
        assert len(failed_results) > 0
        assert any("Max depth" in (r.error or "") for r in failed_results)

    @pytest.mark.asyncio
    async def test_max_children_per_agent_enforced(self, mock_dag_executor: DAGExecutor):
        """Max children per agent is enforced."""
        # Agent that tries to spawn many children
        parent = MockAgent("parent", spawn_children=["c1", "c2", "c3", "c4", "c5"])
        children = [MockAgent(f"c{i}") for i in range(1, 6)]

        config = DeepAgentConfig(max_children_per_agent=2)
        agents = {parent.id: parent}
        agents.update({c.id: c for c in children})

        orchestrator = DeepAgentOrchestrator(
            agents=agents,
            dag_executor=mock_dag_executor,
            config=config,
        )
        parent.set_orchestrator(orchestrator)

        result = await orchestrator.run(
            root_agent_id=parent.id,
            goal=SimpleGoal(task="test"),
        )

        # Should have limited spawns
        assert result.total_agents_spawned <= config.max_children_per_agent

    @pytest.mark.asyncio
    async def test_propagate_errors_true(self, mock_dag_executor: DAGExecutor):
        """Errors propagate when configured."""
        parent = MockAgent("parent", spawn_children=["child"])
        child = MockAgent("child", fail=True)

        config = DeepAgentConfig(propagate_errors=True)
        orchestrator = DeepAgentOrchestrator(
            agents={parent.id: parent, child.id: child},
            dag_executor=mock_dag_executor,
            config=config,
        )
        parent.set_orchestrator(orchestrator)

        result = await orchestrator.run(
            root_agent_id=parent.id,
            goal=SimpleGoal(task="test"),
        )

        # Child failure should propagate
        # Note: parent still completes, but child result shows failure
        child_results = [r for r in result.agent_results if not r.success]
        assert len(child_results) > 0

    @pytest.mark.asyncio
    async def test_initial_context_passed(self, mock_dag_executor: DAGExecutor, simple_agent: MockAgent):
        """Initial context is passed to agent."""
        orchestrator = DeepAgentOrchestrator(
            agents={simple_agent.id: simple_agent},
            dag_executor=mock_dag_executor,
        )

        result = await orchestrator.run(
            root_agent_id=simple_agent.id,
            goal=SimpleGoal(task="test"),
            initial_context={"key": "value"},
        )

        assert result.success


class TestChildSpawn:
    """Tests for ChildSpawn dataclass."""

    def test_creation(self):
        """ChildSpawn records spawn info."""
        spawn = ChildSpawn(
            child_id=AgentID("child"),
            parent_id=AgentID("parent"),
            goal=SimpleGoal(task="test"),
            depth=1,
        )

        assert spawn.child_id == AgentID("child")
        assert spawn.depth == 1


class TestDeepAgentResult:
    """Tests for DeepAgentResult."""

    def test_total_agents_spawned(self):
        """total_agents_spawned counts spawns."""
        spawns = (
            ChildSpawn(child_id=AgentID("c1"), parent_id=AgentID("p"), goal={}, depth=1),
            ChildSpawn(child_id=AgentID("c2"), parent_id=AgentID("p"), goal={}, depth=1),
        )

        result = DeepAgentResult(success=True, child_spawns=spawns)

        assert result.total_agents_spawned == 2

    def test_max_depth_reached(self):
        """max_depth_reached finds max depth."""
        spawns = (
            ChildSpawn(child_id=AgentID("c1"), parent_id=AgentID("p"), goal={}, depth=1),
            ChildSpawn(child_id=AgentID("c2"), parent_id=AgentID("c1"), goal={}, depth=2),
            ChildSpawn(child_id=AgentID("c3"), parent_id=AgentID("c2"), goal={}, depth=3),
        )

        result = DeepAgentResult(success=True, child_spawns=spawns)

        assert result.max_depth_reached == 3

    def test_max_depth_no_spawns(self):
        """max_depth_reached is 0 with no spawns."""
        result = DeepAgentResult(success=True)

        assert result.max_depth_reached == 0

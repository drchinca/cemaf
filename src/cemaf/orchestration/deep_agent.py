"""
DeepAgent Orchestrator - Hierarchical multi-agent with context isolation.

DeepAgent pattern:
- Parent agent can spawn child agents
- Each child gets ISOLATED context scope
- Parent can see child outputs but not internals
- Enables recursive task decomposition
- Dynamic DAG creation based on goals
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, TypeVar

from pydantic import BaseModel

from cemaf.agents.base import Agent, AgentContext, AgentResult
from cemaf.core.constants import (
    DEFAULT_DEEP_AGENT_MAX_CHILDREN,
    DEFAULT_DEEP_AGENT_MAX_DEPTH,
    DEFAULT_DEEP_AGENT_MAX_TOTAL,
    DEFAULT_DEEP_AGENT_TIMEOUT_SECONDS,
)
from cemaf.core.enums import RunStatus
from cemaf.core.types import JSON, AgentID, RunID
from cemaf.core.utils import generate_id, utc_now
from cemaf.orchestration.dag import DAG
from cemaf.orchestration.executor import DAGExecutor, ExecutionResult

GoalT = TypeVar("GoalT", bound=BaseModel)
ResultT = TypeVar("ResultT", bound=BaseModel)


@dataclass(frozen=True)
class ChildSpawn:
    """Record of a child agent spawn."""

    child_id: AgentID
    parent_id: AgentID
    goal: Any
    depth: int
    spawned_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True)
class DeepAgentResult[ResultT: BaseModel]:
    """
    Result of DeepAgent orchestration.

    Includes full trace of child agent executions.
    """

    success: bool
    output: ResultT | None = None
    error: str | None = None

    # Execution trace
    root_agent_id: AgentID | None = None
    child_spawns: tuple[ChildSpawn, ...] = field(default_factory=tuple)
    agent_results: tuple[AgentResult[Any], ...] = field(default_factory=tuple)
    dag_executions: tuple[ExecutionResult, ...] = field(default_factory=tuple)

    # Timing
    started_at: datetime = field(default_factory=utc_now)
    completed_at: datetime | None = None

    metadata: JSON = field(default_factory=dict)

    @property
    def total_agents_spawned(self) -> int:
        return len(self.child_spawns)

    @property
    def max_depth_reached(self) -> int:
        if not self.child_spawns:
            return 0
        return max(s.depth for s in self.child_spawns)


class DeepAgentConfig(BaseModel):
    """Configuration for DeepAgent orchestration."""

    model_config = {"frozen": True}

    max_depth: int = DEFAULT_DEEP_AGENT_MAX_DEPTH
    max_children_per_agent: int = DEFAULT_DEEP_AGENT_MAX_CHILDREN
    max_total_agents: int = DEFAULT_DEEP_AGENT_MAX_TOTAL
    timeout_seconds: float = DEFAULT_DEEP_AGENT_TIMEOUT_SECONDS
    isolate_child_memory: bool = True
    propagate_errors: bool = True


class DeepAgentOrchestrator:
    """
    Orchestrator for DeepAgent pattern.

    Enables hierarchical multi-agent execution with:
    - Context isolation between parent/child
    - Dynamic DAG creation
    - Recursive task decomposition
    - Enforced guardrails (depth, children, timeout, errors)

    Usage:
        orchestrator = DeepAgentOrchestrator(
            agents={"analyst": analyst_agent, "writer": writer_agent},
            dag_executor=dag_executor,
        )

        result = await orchestrator.run(
            root_agent_id=AgentID("analyst"),
            goal=AnalysisGoal(topic="market trends"),
            initial_context={"data": data},
        )
    """

    def __init__(
        self,
        agents: dict[AgentID, Agent[Any, Any]],
        dag_executor: DAGExecutor,
        config: DeepAgentConfig | None = None,
    ) -> None:
        self._agents = agents
        self._dag_executor = dag_executor
        self._config = config or DeepAgentConfig()

        # Runtime state (reset each run)
        self._spawns: list[ChildSpawn] = []
        self._agent_results: list[AgentResult[Any]] = []
        self._dag_executions: list[ExecutionResult] = []
        self._children_per_agent: dict[AgentID, int] = {}
        self._start_time: datetime | None = None

    async def run(
        self,
        root_agent_id: AgentID,
        goal: GoalT,
        initial_context: JSON | None = None,
        run_id: RunID | None = None,
    ) -> DeepAgentResult[ResultT]:
        """
        Execute the DeepAgent orchestration.

        Args:
            root_agent_id: The agent to start with
            goal: What to accomplish
            initial_context: Starting context
            run_id: Optional run ID

        Returns:
            DeepAgentResult with full execution trace
        """
        # Reset state
        self._spawns = []
        self._agent_results = []
        self._dag_executions = []
        self._children_per_agent = {}
        self._start_time = utc_now()

        run_id = run_id or RunID(generate_id("deep"))
        started_at = self._start_time

        try:
            # Get root agent
            root_agent = self._agents.get(root_agent_id)
            if not root_agent:
                return DeepAgentResult(
                    success=False,
                    error=f"Agent {root_agent_id} not found",
                    root_agent_id=root_agent_id,
                    started_at=started_at,
                    completed_at=utc_now(),
                )

            # Create root context
            context = AgentContext(
                run_id=str(run_id),
                agent_id=str(root_agent_id),
                depth=0,
                global_memory=initial_context or {},
            )

            # Execute root agent with timeout
            result = await asyncio.wait_for(
                self._execute_agent(
                    agent=root_agent,
                    goal=goal,
                    context=context,
                    depth=0,
                    parent_id=None,
                ),
                timeout=self._config.timeout_seconds,
            )

            self._agent_results.append(result)

            return DeepAgentResult(
                success=result.success,
                output=result.output,
                error=result.error,
                root_agent_id=root_agent_id,
                child_spawns=tuple(self._spawns),
                agent_results=tuple(self._agent_results),
                dag_executions=tuple(self._dag_executions),
                started_at=started_at,
                completed_at=utc_now(),
            )

        except TimeoutError:
            return DeepAgentResult(
                success=False,
                error=f"Timeout exceeded: {self._config.timeout_seconds}s",
                root_agent_id=root_agent_id,
                child_spawns=tuple(self._spawns),
                agent_results=tuple(self._agent_results),
                dag_executions=tuple(self._dag_executions),
                started_at=started_at,
                completed_at=utc_now(),
            )

        except Exception as e:
            return DeepAgentResult(
                success=False,
                error=str(e),
                root_agent_id=root_agent_id,
                child_spawns=tuple(self._spawns),
                agent_results=tuple(self._agent_results),
                dag_executions=tuple(self._dag_executions),
                started_at=started_at,
                completed_at=utc_now(),
            )

    def _check_timeout(self) -> None:
        """Check if timeout has been exceeded. Raises TimeoutError if so."""
        if self._start_time is None:
            return
        elapsed = (utc_now() - self._start_time).total_seconds()
        if elapsed > self._config.timeout_seconds:
            raise TimeoutError(f"Timeout exceeded: {elapsed:.1f}s > {self._config.timeout_seconds}s")

    async def _execute_agent(
        self,
        agent: Agent[Any, Any],
        goal: Any,
        context: AgentContext,
        depth: int,
        parent_id: AgentID | None,
    ) -> AgentResult[Any]:
        """Execute a single agent with guardrails enforced."""
        # Check timeout
        self._check_timeout()

        # Check depth limit
        if depth > self._config.max_depth:
            return AgentResult.fail(f"Max depth {self._config.max_depth} exceeded")

        # Check total agents limit
        if len(self._spawns) >= self._config.max_total_agents:
            return AgentResult.fail(f"Max agents {self._config.max_total_agents} exceeded")

        # Execute the agent
        try:
            result = await agent.run(goal, context)

            # Handle error propagation
            if not result.success and self._config.propagate_errors and parent_id is not None:
                # Error will bubble up to parent
                pass

            return result

        except Exception as e:
            if self._config.propagate_errors:
                raise
            return AgentResult.fail(str(e))

    async def spawn_child(
        self,
        parent_id: AgentID,
        child_agent_id: AgentID,
        goal: Any,
        parent_context: AgentContext,
    ) -> AgentResult[Any]:
        """
        Spawn a child agent from a parent.

        Called by agents that need to delegate to child agents.
        Enforces max_children_per_agent guardrail.

        Args:
            parent_id: The parent agent's ID
            child_agent_id: Which agent to spawn
            goal: What the child should accomplish
            parent_context: Parent's context (used for isolation)

        Returns:
            AgentResult from the child
        """
        # Check timeout
        self._check_timeout()

        # Check max_children_per_agent
        current_children = self._children_per_agent.get(parent_id, 0)
        if current_children >= self._config.max_children_per_agent:
            error_msg = (
                f"Max children per agent ({self._config.max_children_per_agent}) exceeded for {parent_id}"
            )
            if self._config.propagate_errors:
                return AgentResult.fail(error_msg)
            return AgentResult.fail(error_msg)

        child_agent = self._agents.get(child_agent_id)
        if not child_agent:
            return AgentResult.fail(f"Child agent {child_agent_id} not found")

        # Create isolated context for child
        child_context = AgentContext(
            run_id=parent_context.run_id,
            agent_id=str(child_agent_id),
            parent_agent_id=str(parent_id),
            depth=parent_context.depth + 1,
            global_memory=parent_context.global_memory,  # Read-only global
            parent_memory=parent_context.agent_memory if not self._config.isolate_child_memory else {},
            artifacts=parent_context.artifacts,
        )

        # Record spawn
        spawn = ChildSpawn(
            child_id=child_agent_id,
            parent_id=parent_id,
            goal=goal,
            depth=parent_context.depth + 1,
        )
        self._spawns.append(spawn)

        # Track children count
        self._children_per_agent[parent_id] = current_children + 1

        # Execute child
        try:
            result = await self._execute_agent(
                agent=child_agent,
                goal=goal,
                context=child_context,
                depth=parent_context.depth + 1,
                parent_id=parent_id,
            )

            self._agent_results.append(result)

            # Propagate errors if configured
            if not result.success and self._config.propagate_errors:
                return result

            return result

        except Exception as e:
            if self._config.propagate_errors:
                raise
            return AgentResult.fail(str(e))

    async def run_dynamic_dag(
        self,
        dag: DAG,
        context: JSON,
        from_agent: AgentID,
    ) -> ExecutionResult:
        """
        Execute a dynamically created DAG.

        Agents can create DAGs at runtime and execute them.
        Respects timeout guardrail.

        Args:
            dag: The DAG to execute
            context: Starting context
            from_agent: Which agent created this DAG

        Returns:
            ExecutionResult from DAG execution
        """
        # Check timeout before starting DAG
        self._check_timeout()

        # Calculate remaining time for DAG execution
        remaining_timeout = self._config.timeout_seconds
        if self._start_time:
            elapsed = (utc_now() - self._start_time).total_seconds()
            remaining_timeout = max(0.1, self._config.timeout_seconds - elapsed)

        try:
            result = await asyncio.wait_for(
                self._dag_executor.run(dag, context),
                timeout=remaining_timeout,
            )
            self._dag_executions.append(result)
            return result

        except TimeoutError:
            # Create failed result on timeout
            from cemaf.orchestration.executor import ExecutionResult

            result = ExecutionResult(
                run_id=RunID(generate_id("dag")),
                dag_name=dag.name,
                status=RunStatus.FAILED,
                error=f"DAG timeout: remaining time {remaining_timeout:.1f}s exceeded",
                completed_at=utc_now(),
            )
            self._dag_executions.append(result)
            return result

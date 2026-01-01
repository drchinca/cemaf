"""
Orchestration protocols - Abstract interfaces for DAG execution.

Supports:
- DAG execution with parallel node processing
- Checkpoint/resume capability
- Event emission for observability
- DeepAgent hierarchical orchestration

## Protocol-First Design

This module provides structural typing via @runtime_checkable protocols.
Any class that implements the required methods is automatically compatible.

Extension Point:
    Implement these protocols for custom orchestration strategies.
    No registration needed - structural typing ensures compatibility.
"""

from typing import Any, Protocol, runtime_checkable

# Re-export data classes (not changed)
from cemaf.orchestration.dag import DAG, Edge, EdgeCondition, Node
from cemaf.orchestration.executor import ExecutionResult

__all__ = [
    "DAGExecutor",
    "DeepAgentOrchestrator",
    # Data classes
    "DAG",
    "Node",
    "Edge",
    "EdgeCondition",
    "ExecutionResult",
]


@runtime_checkable
class DAGExecutor(Protocol):
    """
    Protocol for DAG executor implementations.

    A DAGExecutor runs directed acyclic graphs:
    - Execute nodes in topological order
    - Parallel execution of independent nodes
    - Handle node dependencies and edges
    - Support checkpoint/resume
    - Emit events for observability

    Extension Point:
        - Simple executor (sequential)
        - Parallel executor (thread/async pool)
        - Distributed executor (Celery, Ray, Dask)
        - Conditional executor (skip nodes based on conditions)
        - Streaming executor (emit results as they complete)

    Example:
        >>> class SimpleDAGExecutor:
        ...     async def execute(self, dag: DAG, context: Any) -> ExecutionResult:
        ...         # Execute nodes in topological order
        ...         results = {}
        ...         for node in dag.nodes:
        ...             result = await node.execute(context)
        ...             results[node.id] = result
        ...         return ExecutionResult(success=True, outputs=results)
        >>>
        >>> executor = SimpleDAGExecutor()
        >>> assert isinstance(executor, DAGExecutor)
    """

    async def execute(self, dag: DAG, context: Any) -> ExecutionResult:
        """
        Execute a DAG with the given context.

        Args:
            dag: DAG to execute
            context: Execution context (passed to all nodes)

        Returns:
            ExecutionResult with outputs from all nodes

        Example:
            >>> dag = DAG(nodes=[node1, node2], edges=[edge1])
            >>> context = {"input": "data"}
            >>> result = await executor.execute(dag, context)
            >>> print(f"Success: {result.success}")
            >>> print(f"Outputs: {result.outputs}")
        """
        ...


@runtime_checkable
class DeepAgentOrchestrator(Protocol):
    """
    Protocol for deep agent orchestrator implementations.

    A DeepAgent orchestrator enables hierarchical agent composition:
    - Parent agents can spawn child agents
    - Context isolation between agent levels
    - Depth limits and safeguards
    - Aggregation of child results

    Extension Point:
        - Simple orchestrator (sequential child execution)
        - Parallel orchestrator (concurrent children)
        - Budget-aware orchestrator (distribute tokens across children)
        - Adaptive orchestrator (spawn children based on results)

    Example:
        >>> class SimpleDeepAgentOrchestrator:
        ...     async def orchestrate(self, parent_agent: Any, child_agents: list) -> Any:
        ...         # Run parent, then children, then aggregate
        ...         parent_result = await parent_agent.run()
        ...         child_results = []
        ...         for child in child_agents:
        ...             result = await child.run()
        ...             child_results.append(result)
        ...         return aggregate(parent_result, child_results)
        >>>
        >>> orchestrator = SimpleDeepAgentOrchestrator()
        >>> assert isinstance(orchestrator, DeepAgentOrchestrator)
    """

    async def orchestrate(self, parent_agent: Any, child_agents: list[Any]) -> Any:
        """
        Orchestrate parent and child agents hierarchically.

        Args:
            parent_agent: Parent agent (coordinator)
            child_agents: List of child agents to execute

        Returns:
            Aggregated result from parent and children

        Example:
            >>> parent = CoordinatorAgent()
            >>> children = [AnalystAgent(), ResearchAgent(), WriterAgent()]
            >>> result = await orchestrator.orchestrate(parent, children)
            >>> print(f"Report: {result.final_output}")
        """
        ...

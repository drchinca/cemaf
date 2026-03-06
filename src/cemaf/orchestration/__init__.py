"""
Orchestration module - Dynamic DAG execution with DeepAgent pattern.

This module provides:
- DAG: Directed Acyclic Graph for workflow definition
- Node: Atomic unit of execution in a DAG
- Edge: Connection between nodes with conditions
- DeepAgent: Hierarchical orchestrator with context isolation
- Executor: Runs DAGs with parallel execution support
"""

from cemaf.orchestration.checkpointer import (
    Checkpointer,
    CheckpointingDAGExecutor,
    DAGCheckpoint,
    InMemoryCheckpointer,
)
from cemaf.orchestration.context_node_executor import ContextNodeExecutor
from cemaf.orchestration.dag import DAG, Edge, EdgeCondition, Node
from cemaf.orchestration.deep_agent import DeepAgentOrchestrator
from cemaf.orchestration.dependency_resolver import resolve_dependencies, resolve_node_input
from cemaf.orchestration.executor import (
    DAGExecutor,
    ExecutionResult,
    ExecutorConfig,
    NodeExecutor,
    NodeResult,
)
from cemaf.orchestration.factories import create_dag_executor, create_dag_executor_from_config
from cemaf.orchestration.planner import Planner

__all__ = [
    "DAG",
    "Node",
    "Edge",
    "EdgeCondition",
    "ContextNodeExecutor",
    "DAGExecutor",
    "ExecutionResult",
    "ExecutorConfig",
    "NodeExecutor",
    "NodeResult",
    "DeepAgentOrchestrator",
    "Planner",
    "resolve_dependencies",
    "resolve_node_input",
    # Checkpointing
    "Checkpointer",
    "CheckpointingDAGExecutor",
    "DAGCheckpoint",
    "InMemoryCheckpointer",
    # Factories
    "create_dag_executor",
    "create_dag_executor_from_config",
]

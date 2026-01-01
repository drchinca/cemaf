"""
Orchestration module - Dynamic DAG execution with DeepAgent pattern.

This module provides:
- DAG: Directed Acyclic Graph for workflow definition
- Node: Atomic unit of execution in a DAG
- Edge: Connection between nodes with conditions
- DeepAgent: Hierarchical orchestrator with context isolation
- Executor: Runs DAGs with parallel execution support
"""

from cemaf.orchestration.dag import DAG, Edge, EdgeCondition, Node
from cemaf.orchestration.deep_agent import DeepAgentOrchestrator
from cemaf.orchestration.executor import DAGExecutor, ExecutionResult

__all__ = [
    "DAG",
    "Node",
    "Edge",
    "EdgeCondition",
    "DAGExecutor",
    "ExecutionResult",
    "DeepAgentOrchestrator",
]

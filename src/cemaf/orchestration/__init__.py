"""Orchestration — DAG execution, composition root, runtime services.

The top of Layer 1: this package wires everything together and is allowed
to import from every other Layer 1 package. Nothing below `orchestration/`
imports from `orchestration/` (except via the EventBus).

Key concepts:
- **DAG / Node / Edge** — the workflow data model (immutable, frozen dataclasses)
- **DAGExecutor** — runs a DAG; concurrent-safe via `contextvars.ContextVar`
- **ContextNodeExecutor** — dispatches AGENT nodes through the AgentRegistry
- **RuntimeServices** — frozen dataclass bundling 15+ optional dependencies;
  the typed DI container injected at the composition root
- **ExecutorConfig** — sizing, timeouts, enable/disable flags
- **HaltSignal / HaltReason** — structured halt reporting (BUDGET_EXHAUSTED,
  QUALITY_DEGRADED, …). Propagates into LOOP bodies so runaway loops stop
  mid-flight instead of wasting N-1 calls after halt fires
- **NodeHandlerContext** — per-run state passed to router/loop/parallel/
  conditional handlers; includes `should_halt` callback for cooperative
  cancellation
- **Checkpointer** — replay checkpoint support

Canonical wiring — prefer `cemaf.bootstrap.create_executor` over instantiating
DAGExecutor directly. The bootstrap hooks event subscriptions and health
checks that individual construction skips.

    from cemaf.bootstrap import create_executor
    executor = create_executor(
        agent_registry=registry,
        services=RuntimeServices(...),
        config=ExecutorConfig(...),
    )
    result = await executor.run(dag=dag)

See docs/architecture.md for the full architecture and
docs/patterns.md for the RuntimeServices / composition-root patterns.
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
from cemaf.orchestration.file_checkpointer import FileCheckpointer
from cemaf.orchestration.planner import Planner
from cemaf.orchestration.run_lease import (
    FencedCheckpointer,
    FileRunLeaseStore,
    RunLease,
    RunLeaseStore,
    StaleRunLeaseError,
)

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
    "FileCheckpointer",
    "RunLease",
    "RunLeaseStore",
    "FileRunLeaseStore",
    "FencedCheckpointer",
    "StaleRunLeaseError",
    # Factories
    "create_dag_executor",
    "create_dag_executor_from_config",
]

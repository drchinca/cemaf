"""
Factory functions for orchestration components.

Provides convenient ways to create executor instances
with sensible defaults while maintaining dependency injection principles.

Note: Uses PEP 563 (from __future__ import annotations) to defer annotation evaluation
and avoid circular imports.
"""

from __future__ import annotations

import os

from cemaf.orchestration.executor import DAGExecutor, ExecutorConfig, NodeExecutor


def create_dag_executor(
    node_executor: NodeExecutor,
    config: ExecutorConfig | None = None,
    run_logger: RunLogger | None = None,  # noqa: F821
    event_bus: EventBus | None = None,  # noqa: F821
    moderation_pipeline: ModerationPipeline | None = None,  # noqa: F821
) -> DAGExecutor:
    """
    Factory for DAGExecutor with sensible defaults.

    Args:
        node_executor: Required node execution strategy
        config: Executor configuration (optional)
        run_logger: Run logging for replay (optional)
        event_bus: Event bus integration (optional)
        moderation_pipeline: Content moderation (optional)

    Returns:
        Configured DAGExecutor instance

    Example:
        # Minimal setup
        executor = create_dag_executor(node_executor=my_executor)

        # With logging
        executor = create_dag_executor(
            node_executor=my_executor,
            run_logger=InMemoryRunLogger(),
        )

        # With custom config
        config = ExecutorConfig(max_parallel=20)
        executor = create_dag_executor(
            node_executor=my_executor,
            config=config,
        )
    """
    cfg = config or ExecutorConfig()

    return DAGExecutor(
        node_executor=node_executor,
        max_parallel=cfg.max_parallel,
        run_logger=run_logger if cfg.enable_logging else None,
        event_bus=event_bus if cfg.enable_events else None,
        moderation_pipeline=moderation_pipeline if cfg.enable_moderation else None,
    )


def create_dag_executor_from_config(
    node_executor: NodeExecutor,
    run_logger: RunLogger | None = None,  # noqa: F821
    event_bus: EventBus | None = None,  # noqa: F821
    moderation_pipeline: ModerationPipeline | None = None,  # noqa: F821
) -> DAGExecutor:
    """
    Create DAGExecutor from environment configuration.

    Reads from environment variables:
    - CEMAF_ORCHESTRATION_MAX_PARALLEL_NODES: Max parallel execution (default: 10)
    - CEMAF_ORCHESTRATION_ENABLE_LOGGING: Enable logging (default: true)
    - CEMAF_ORCHESTRATION_ENABLE_EVENTS: Enable events (default: true)
    - CEMAF_ORCHESTRATION_ENABLE_MODERATION: Enable moderation (default: false)

    Args:
        node_executor: Required node execution strategy
        run_logger: Run logging for replay (optional)
        event_bus: Event bus integration (optional)
        moderation_pipeline: Content moderation (optional)

    Returns:
        Configured DAGExecutor instance

    Example:
        # From environment
        executor = create_dag_executor_from_config(node_executor=my_executor)
    """
    max_parallel = int(os.getenv("CEMAF_ORCHESTRATION_MAX_PARALLEL_NODES", "10"))
    enable_logging = os.getenv("CEMAF_ORCHESTRATION_ENABLE_LOGGING", "true").lower() == "true"
    enable_events = os.getenv("CEMAF_ORCHESTRATION_ENABLE_EVENTS", "true").lower() == "true"
    enable_moderation = os.getenv("CEMAF_ORCHESTRATION_ENABLE_MODERATION", "false").lower() == "true"

    config = ExecutorConfig(
        max_parallel=max_parallel,
        enable_logging=enable_logging,
        enable_events=enable_events,
        enable_moderation=enable_moderation,
    )

    return create_dag_executor(
        node_executor=node_executor,
        config=config,
        run_logger=run_logger,
        event_bus=event_bus,
        moderation_pipeline=moderation_pipeline,
    )

"""
Factory functions for orchestration components.

Provides convenient ways to create executor instances
with sensible defaults while maintaining dependency injection principles.

Note: Uses PEP 563 () to defer annotation evaluation
and avoid circular imports.
"""

import os

from cemaf.events.protocols import EventBus
from cemaf.memory.session import SessionManager
from cemaf.moderation.pipeline import ModerationPipeline
from cemaf.observability.run_logger import RunLogger
from cemaf.orchestration.executor import DAGExecutor, ExecutorConfig, NodeExecutor
from cemaf.orchestration.services import RuntimeServices


def create_executor_config(
    *,
    max_parallel: int | None = None,
    enable_logging: bool = True,
    enable_events: bool = True,
    enable_moderation: bool = False,
    merge_strategy: str = "last_write_wins",
    node_timeout_seconds: float = 300.0,
) -> ExecutorConfig:
    """Create an ExecutorConfig with explicit execution settings."""
    kwargs: dict[str, object] = {
        "enable_logging": enable_logging,
        "enable_events": enable_events,
        "enable_moderation": enable_moderation,
        "merge_strategy": merge_strategy,
        "node_timeout_seconds": node_timeout_seconds,
    }
    if max_parallel is not None:
        kwargs["max_parallel"] = max_parallel
    return ExecutorConfig(**kwargs)


def create_dag_executor(
    node_executor: NodeExecutor,
    config: ExecutorConfig | None = None,
    run_logger: RunLogger | None = None,
    event_bus: EventBus | None = None,
    moderation_pipeline: ModerationPipeline | None = None,
    session_manager: SessionManager | None = None,
) -> DAGExecutor:
    """Factory for DAGExecutor with sensible defaults.

    Bundles the per-executor services into a RuntimeServices then hands
    the executor a single services parameter — mirrors bootstrap.create_executor.
    """
    cfg = config or create_executor_config()
    services = RuntimeServices(
        run_logger=run_logger if cfg.enable_logging else None,
        event_bus=event_bus if cfg.enable_events else None,
        moderation_pipeline=moderation_pipeline if cfg.enable_moderation else None,
        session_manager=session_manager,
    )
    return DAGExecutor(
        node_executor=node_executor,
        services=services,
        config=cfg,
    )


def create_dag_executor_from_config(
    node_executor: NodeExecutor,
    run_logger: RunLogger | None = None,
    event_bus: EventBus | None = None,
    moderation_pipeline: ModerationPipeline | None = None,
    session_manager: SessionManager | None = None,
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

    config = create_executor_config(
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
        session_manager=session_manager,
    )

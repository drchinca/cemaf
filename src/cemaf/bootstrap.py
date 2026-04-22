"""Composition root -- single entry point for creating a fully-wired executor."""

from cemaf.agents.registry import AgentRegistry
from cemaf.orchestration.context_node_executor import ContextNodeExecutor
from cemaf.orchestration.executor import DAGExecutor, ExecutorConfig
from cemaf.orchestration.services import RuntimeServices


def create_executor(
    *,
    agent_registry: AgentRegistry,
    config: ExecutorConfig | None = None,
    services: RuntimeServices | None = None,
) -> DAGExecutor:
    """Create a fully-wired DAGExecutor from registry and optional services."""
    cfg = config or ExecutorConfig()
    svc = services or RuntimeServices()

    node_executor = ContextNodeExecutor(
        agent_registry=agent_registry,
        run_logger=svc.run_logger if cfg.enable_logging else None,
        domain_context=svc.domain_context,
        llm_client=svc.llm_client,
        vector_store=svc.vector_store,
        memory_manager=svc.memory_manager,
        session_manager=svc.session_manager,
        context_compiler=svc.context_compiler,
        token_budget=svc.token_budget,
    )

    # Wire online eval pipeline and quality police subscriptions
    if svc.event_bus and cfg.enable_events:
        if svc.online_eval_pipeline:
            svc.online_eval_pipeline.subscribe()
        if svc.quality_police:
            svc.quality_police.subscribe(event_bus=svc.event_bus)

    return DAGExecutor(
        node_executor=node_executor,
        max_parallel=cfg.max_parallel,
        run_logger=svc.run_logger if cfg.enable_logging else None,
        event_bus=svc.event_bus if cfg.enable_events else None,
        moderation_pipeline=svc.moderation_pipeline if cfg.enable_moderation else None,
        health_registry=svc.health_monitor,
        auto_heal_manager=svc.auto_heal_manager,
        budget_guard=svc.budget_guard,
        session_manager=svc.session_manager,
        node_timeout_seconds=cfg.node_timeout_seconds,
        quality_police=svc.quality_police,
    )

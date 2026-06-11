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
        blueprint_selector=svc.blueprint_selector,
        agent_selector=svc.agent_selector,
        budget_guard=svc.budget_guard,
        council_aggregator=svc.council_aggregator,
        interceptor_pipeline=svc.interceptor_pipeline,
        max_recovery_attempts=svc.max_recovery_attempts,
    )

    # Wire online eval pipeline and quality police subscriptions
    if svc.event_bus and cfg.enable_events:
        if svc.online_eval_pipeline:
            svc.online_eval_pipeline.subscribe()
        if svc.quality_police:
            svc.quality_police.subscribe(event_bus=svc.event_bus)

    # Build a filtered RuntimeServices view honoring the config's enable_* flags.
    # DAGExecutor now takes a single services bundle instead of 13 kwargs.
    from dataclasses import replace

    effective_services = replace(
        svc,
        run_logger=svc.run_logger if cfg.enable_logging else None,
        event_bus=svc.event_bus if cfg.enable_events else None,
        moderation_pipeline=svc.moderation_pipeline if cfg.enable_moderation else None,
    )
    executor: DAGExecutor = DAGExecutor(
        node_executor=node_executor,
        services=effective_services,
        config=cfg,
    )

    if effective_services.tracer is not None:
        from cemaf.orchestration.instrumented_executor import InstrumentedDAGExecutor

        return InstrumentedDAGExecutor(inner=executor, tracer=effective_services.tracer)  # type: ignore[return-value]

    return executor

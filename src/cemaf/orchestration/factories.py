"""
Factory functions for orchestration components.

Provides convenient ways to create executor instances
with sensible defaults while maintaining dependency injection principles.

Note: Uses PEP 563 () to defer annotation evaluation
and avoid circular imports.
"""

import os

from cemaf.agents.selection import AgentSelector
from cemaf.blueprint.library import BlueprintLibrary
from cemaf.context.budget import TokenBudget
from cemaf.context.compiler import ContextCompiler
from cemaf.core.domain import DomainContext
from cemaf.core.recovery import AutoHealManager
from cemaf.council.protocols import VoteAggregator
from cemaf.datasources.registry import DataSourceRegistry
from cemaf.evals.online import OnlineEvalPipeline
from cemaf.evals.police import QualityPolice
from cemaf.events.protocols import EventBus
from cemaf.interceptors.pipeline import InterceptorPipeline
from cemaf.interceptors.pull import PullInterceptor
from cemaf.knowledge.protocols import KnowledgeGraph
from cemaf.llm.protocols import LLMClient
from cemaf.memory.manager import MemoryManager
from cemaf.memory.session import SessionManager
from cemaf.moderation.pipeline import ModerationPipeline
from cemaf.observability.budget_guard import BudgetGuard
from cemaf.observability.health import HealthMonitor
from cemaf.observability.protocols import Tracer
from cemaf.observability.run_logger import RunLogger
from cemaf.orchestration.blueprint_hook import BlueprintSelectorHook
from cemaf.orchestration.executor import DAGExecutor, ExecutorConfig, NodeExecutor
from cemaf.orchestration.services import RuntimeServices
from cemaf.retrieval.protocols import VectorStore


def create_runtime_services(
    *,
    run_logger: RunLogger | None = None,
    event_bus: EventBus | None = None,
    health_monitor: HealthMonitor | None = None,
    budget_guard: BudgetGuard | None = None,
    online_eval_pipeline: OnlineEvalPipeline | None = None,
    quality_police: QualityPolice | None = None,
    memory_manager: MemoryManager | None = None,
    session_manager: SessionManager | None = None,
    moderation_pipeline: ModerationPipeline | None = None,
    context_compiler: ContextCompiler | None = None,
    token_budget: TokenBudget | None = None,
    domain_context: DomainContext | None = None,
    llm_client: LLMClient | None = None,
    vector_store: VectorStore | None = None,
    knowledge_graph: KnowledgeGraph | None = None,
    data_source_registry: DataSourceRegistry | None = None,
    agent_selector: AgentSelector | None = None,
    council_aggregator: VoteAggregator | None = None,
    interceptor_pipeline: InterceptorPipeline | None = None,
    max_recovery_attempts: int = 2,
    blueprint_library: BlueprintLibrary | None = None,
    blueprint_selector: BlueprintSelectorHook | None = None,
    auto_heal_manager: AutoHealManager | None = None,
    tracer: Tracer | None = None,
) -> RuntimeServices:
    """Create a RuntimeServices bundle with explicit per-concern dependencies."""
    return RuntimeServices(
        run_logger=run_logger,
        event_bus=event_bus,
        health_monitor=health_monitor,
        budget_guard=budget_guard,
        online_eval_pipeline=online_eval_pipeline,
        quality_police=quality_police,
        memory_manager=memory_manager,
        session_manager=session_manager,
        moderation_pipeline=moderation_pipeline,
        context_compiler=context_compiler,
        token_budget=token_budget,
        domain_context=domain_context,
        llm_client=llm_client,
        vector_store=vector_store,
        knowledge_graph=knowledge_graph,
        data_source_registry=data_source_registry,
        agent_selector=agent_selector,
        council_aggregator=council_aggregator,
        interceptor_pipeline=interceptor_pipeline,
        max_recovery_attempts=max_recovery_attempts,
        blueprint_library=blueprint_library,
        blueprint_selector=blueprint_selector,
        auto_heal_manager=auto_heal_manager,
        tracer=tracer,
    )


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
    services = create_runtime_services(
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


def create_pull_interceptor(
    *, services: RuntimeServices, pull_tokens: int, **kwargs: object
) -> PullInterceptor:
    """Build a PullInterceptor wired from RuntimeServices.knowledge_graph and
    .data_source_registry — the composition-root call that gives
    RuntimeServices.data_source_registry a real consumer. RuntimeServices
    itself never calls DataSourceRegistry directly (see services.py); this
    factory is where a caller turns "I configured a registry" into "there is
    now a PullInterceptor reading from it." Pass the result into
    `create_interceptor_pipeline(interceptors=(create_pull_interceptor(...), ...))`.
    """
    return PullInterceptor(
        pull_tokens=pull_tokens,
        knowledge_graph=services.knowledge_graph,
        data_source_registry=services.data_source_registry,
        token_budget=services.token_budget,
        **kwargs,  # type: ignore[arg-type]
    )

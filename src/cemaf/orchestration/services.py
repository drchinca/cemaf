"""RuntimeServices — the typed DI container at CEMAF's composition root.

`RuntimeServices` is the single, frozen, type-checked bundle that wires every
cross-cutting dependency into `DAGExecutor`. It replaces what would otherwise
be a 15+ kwarg constructor with one field-per-concern:

    services = RuntimeServices(
        # Observability
        run_logger=logger,            # records LLM calls, patches, metrics per run
        event_bus=bus,                # pub/sub seam between modules
        health_monitor=health,        # pre-execution health gates
        budget_guard=guard,           # hard cost cap with HaltSignal
        # Quality
        online_eval_pipeline=evals,   # subscribes to TASK_COMPLETED
        quality_police=police,        # rolling-window quality monitor + halt
        # Memory
        memory_manager=memory,        # semantic + episodic recall
        session_manager=sessions,     # per-run session lifecycle + ingest
        # Content Safety
        moderation_pipeline=mod,      # pre/post-flight moderation on agent I/O
        # Context
        context_compiler=compiler,    # token-budgeted context compilation
        token_budget=budget,          # per-call token cap
        domain_context=domain,        # cross-run domain knowledge
        # LLM + Retrieval
        llm_client=llm,               # the LLMClient protocol impl (may be wrapped)
        vector_store=vectors,         # embedding-backed retrieval
        # Knowledge
        knowledge_graph=kg,           # shared KG (SPEC-02), optionally hub-spoke cached (SPEC-07)
        # Recovery
        auto_heal_manager=heal,       # autonomous heal on node failure
    )

Why this shape:
- **Type-checked wiring**. Mypy catches misconfiguration at write time, not
  at 3am.
- **Request-scoped DI for free**. One `RuntimeServices` per HTTP request /
  per tenant / per user gives per-request observability, budget, quality —
  no framework support needed beyond passing the bundle.
- **Graceful degradation**. Every field is `| None = None`. Absence of a
  service means "that behavior is off" — nothing crashes when it isn't
  configured.
- **Future-proof**. New cross-cutting controllers (rate limits, SLO trackers,
  tenant quotas) add a field here. The `DAGExecutor` constructor stays
  stable.

Anti-pattern — do **not** add a new kwarg to `DAGExecutor.__init__` for a
cross-cutting concern. It lands on `RuntimeServices`. The legacy 13-kwarg
constructor on `DAGExecutor` is a 0.3.x-only migration bridge; it is
removed in 0.4.

Self-hosting (Layer 2) adds `MetaServices` on top of this with audit + KG +
OpenSpec deps. See `cemaf.meta.bootstrap`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from cemaf.agents.selection import AgentSelector
from cemaf.blueprint.harvest import BlueprintHarvesterEngine
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
from cemaf.retrieval.protocols import VectorStore

if TYPE_CHECKING:
    from cemaf.orchestration.checkpointer import Checkpointer


@dataclass(frozen=True)
class RuntimeServices:
    """Bundles optional runtime dependencies for orchestration."""

    # Observability
    run_logger: RunLogger | None = None
    event_bus: EventBus | None = None
    health_monitor: HealthMonitor | None = None
    budget_guard: BudgetGuard | None = None

    # Quality
    online_eval_pipeline: OnlineEvalPipeline | None = None
    quality_police: QualityPolice | None = None

    # Memory
    memory_manager: MemoryManager | None = None
    session_manager: SessionManager | None = None

    # Content safety
    moderation_pipeline: ModerationPipeline | None = None

    # Context
    context_compiler: ContextCompiler | None = None
    token_budget: TokenBudget | None = None
    domain_context: DomainContext | None = None

    # LLM + Retrieval
    llm_client: LLMClient | None = None
    vector_store: VectorStore | None = None

    # Knowledge (SPEC-02 / SPEC-07) — shared KG, optionally hub-and-spoke cached
    knowledge_graph: KnowledgeGraph | None = None

    # DataSources (SPEC-02) — read-only enterprise connector registry. RuntimeServices
    # never calls this directly; it's the DI slot composition-root code reads when
    # building a PullInterceptor for interceptor_pipeline.
    data_source_registry: DataSourceRegistry | None = None

    # Agent selection (SPEC-09) — opt-in auction; None → static ref_id only
    agent_selector: AgentSelector | None = None

    # Council vote aggregation (SPEC-10) — None → DefaultVoteAggregator when a council node runs
    council_aggregator: VoteAggregator | None = None

    # Interceptor spine (SPEC-01a) — PRE→execute→POST chain per AGENT node; None/empty = no-op
    interceptor_pipeline: InterceptorPipeline | None = None

    # Recovery budget — caps how many times a POST RECOVER decision may re-run an
    # agent with a hint (SPEC-01a RECOVER extension). 0 disables recovery (RECOVER
    # decisions degrade to REJECT at the executor); default matches
    # ContextNodeExecutor's own default so behaviour is unchanged when omitted.
    max_recovery_attempts: int = 2

    # Blueprints
    blueprint_library: BlueprintLibrary | None = None
    blueprint_selector: BlueprintSelectorHook | None = None
    blueprint_harvester: BlueprintHarvesterEngine | None = None

    # Recovery
    auto_heal_manager: AutoHealManager | None = None

    # Durable execution
    checkpointer: Checkpointer | None = None
    checkpoint_interval: int = 1

    # Distributed tracing
    tracer: Tracer | None = None

"""Runtime services bundle for orchestration components."""

from dataclasses import dataclass

from cemaf.context.budget import TokenBudget
from cemaf.context.compiler import ContextCompiler
from cemaf.core.domain import DomainContext
from cemaf.core.recovery import AutoHealManager
from cemaf.evals.online import OnlineEvalPipeline
from cemaf.evals.police import QualityPolice
from cemaf.events.protocols import EventBus
from cemaf.llm.protocols import LLMClient
from cemaf.mcp.bridges.openspec.protocols import OpenSpecRuntime
from cemaf.mcp.bridges.openspec.workspace import OpenSpecWorkspace
from cemaf.memory.manager import MemoryManager
from cemaf.memory.session import SessionManager
from cemaf.moderation.pipeline import ModerationPipeline
from cemaf.observability.budget_guard import BudgetGuard
from cemaf.observability.health import HealthMonitor
from cemaf.observability.run_logger import RunLogger
from cemaf.retrieval.protocols import VectorStore


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

    # Recovery
    auto_heal_manager: AutoHealManager | None = None

    # Self-hosting / OpenSpec
    openspec_runtime: OpenSpecRuntime | None = None
    openspec_workspace: OpenSpecWorkspace | None = None

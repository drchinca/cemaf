"""Self-hosting composition root — create a DAGExecutor with meta-agents wired in."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from cemaf.agents.registry import AgentRegistry
from cemaf.audit.factories import create_audit_system
from cemaf.audit.protocols import AuditLog, AuditTrail
from cemaf.blueprint.factories import create_blueprint_harvester
from cemaf.blueprint.harvest import (
    BlueprintDistiller,
    HarvestPolicy,
    RunCorrelator,
)
from cemaf.blueprint.library import WritableBlueprintSource
from cemaf.bootstrap import create_executor
from cemaf.knowledge.factories import create_knowledge_graph
from cemaf.knowledge.hub_spoke import (
    SpokeCacheConfig,
    SpokeReadHubWriteKG,
    create_hub_spoke_kg,
)
from cemaf.knowledge.protocols import KnowledgeGraph
from cemaf.mcp.bridges.openspec.protocols import OpenSpecRuntime
from cemaf.mcp.bridges.openspec.workspace import OpenSpecWorkspace
from cemaf.meta.registry import (
    register_blueprint_selector,
    register_meta_agents,
    register_meta_scaffolder,
    register_meta_specifier,
)
from cemaf.orchestration.executor import DAGExecutor, ExecutorConfig
from cemaf.orchestration.services import RuntimeServices
from cemaf.tools.registry import ToolRegistry


@dataclass(frozen=True)
class MetaServices:
    """Additional services for meta-mode, extending RuntimeServices.

    OpenSpec deps live here, not in RuntimeServices, so the orchestration core
    has no static dependency on the mcp.bridges.openspec module. Similarly,
    the blueprint-harvest machinery lives here rather than on `RuntimeServices`
    to keep the base framework free of harvest-specific coupling.
    """

    audit_log: AuditLog | None = None
    audit_trail: AuditTrail | None = None
    knowledge_graph: KnowledgeGraph | None = None
    openspec_runtime: OpenSpecRuntime | None = None
    openspec_workspace: OpenSpecWorkspace | None = None
    scaffold_output_dir: Path | None = None

    # Hub-and-spoke KG caching (SPEC-07) — opt-in. When True and an EventBus is
    # present, the resolved KG is wrapped in a HubKnowledgeGraph and meta-agents
    # read through a shared spoke cache. Bounded by hub_spoke_config.
    enable_hub_spoke_kg: bool = False
    hub_spoke_config: SpokeCacheConfig | None = None

    # Blueprint harvest — fully opt-in. To enable, set enable_blueprint_harvester=True
    # and provide a writable_blueprint_source (e.g. SqliteBlueprintSource). The
    # three decision protocols default to the opt-in bundled impls in
    # harvest_defaults; pass your own to swap any single piece.
    enable_blueprint_harvester: bool = False
    writable_blueprint_source: WritableBlueprintSource | None = None
    blueprint_harvest_threshold: float = 0.8
    harvest_policy: HarvestPolicy | None = None
    harvest_correlator: RunCorrelator | None = None
    harvest_distiller: BlueprintDistiller | None = None


def create_meta_executor(
    *,
    agent_registry: AgentRegistry,
    tool_registry: ToolRegistry | None = None,
    config: ExecutorConfig | None = None,
    services: RuntimeServices | None = None,
    meta_services: MetaServices | None = None,
) -> DAGExecutor:
    """Create a DAGExecutor with meta-agents for self-hosting."""
    svc = services or RuntimeServices()
    tool_reg = tool_registry or ToolRegistry()

    # Resolve audit system
    audit_log: AuditLog | None = None
    audit_trail: AuditTrail | None = None
    if meta_services and meta_services.audit_log and meta_services.audit_trail:
        audit_log = meta_services.audit_log
        audit_trail = meta_services.audit_trail
    elif svc.event_bus is not None:
        audit_log, audit_trail = create_audit_system(event_bus=svc.event_bus)

    # Resolve knowledge graph — precedence: explicit MetaServices KG, then the
    # shared RuntimeServices KG (SPEC-02), then build one from the MemoryManager.
    kg: KnowledgeGraph | None = None
    if meta_services and meta_services.knowledge_graph:
        kg = meta_services.knowledge_graph
    elif svc.knowledge_graph is not None:
        kg = svc.knowledge_graph
    elif svc.memory_manager is not None:
        kg = create_knowledge_graph(memory_manager=svc.memory_manager)

    # Optionally front the KG with a hub-and-spoke cache (SPEC-07). Meta-agents
    # share one spoke; writes still hit the hub-of-record and invalidate it.
    if (
        kg is not None
        and meta_services is not None
        and meta_services.enable_hub_spoke_kg
        and svc.event_bus is not None
    ):
        hub, spokes = create_hub_spoke_kg(
            backing_kg=kg,
            event_bus=svc.event_bus,
            spoke_configs={"meta": meta_services.hub_spoke_config or SpokeCacheConfig()},
        )
        kg = SpokeReadHubWriteKG(hub=hub, spoke=spokes["meta"])

    # Register meta-agents if we have all required services
    if audit_trail is not None and kg is not None:
        register_meta_agents(
            agent_registry,
            tool_registry=tool_reg,
            audit_trail=audit_trail,
            knowledge_graph=kg,
        )

    # Register MetaSpecifier when an OpenSpec workspace is available
    if meta_services is not None and meta_services.openspec_workspace is not None:
        register_meta_specifier(
            agent_registry,
            tool_registry=tool_reg,
            workspace=meta_services.openspec_workspace,
            runtime=meta_services.openspec_runtime,
            llm_client=svc.llm_client,
        )

    # Register MetaScaffolder unconditionally — it's stateless and safe to
    # register even when no target dir is configured. Callers who want to
    # synthesize apps pass target_dir via ScaffoldGoal.
    register_meta_scaffolder(agent_registry)

    # Register BlueprintSelectorAgent when a library is available.
    if svc.blueprint_library is not None:
        register_blueprint_selector(
            agent_registry,
            library=svc.blueprint_library,
        )

    # Wire the blueprint harvester engine when enabled + all required deps present.
    # The engine is a pure orchestrator; every decision (policy, correlator,
    # distiller) is pluggable — callers who don't override get the bundled
    # defaults from harvest_defaults. Subscription happens here so the engine's
    # lifecycle is owned by the composition root, not by the application.
    if (
        meta_services is not None
        and meta_services.enable_blueprint_harvester
        and meta_services.writable_blueprint_source is not None
        and svc.event_bus is not None
    ):
        create_blueprint_harvester(
            writable_source=meta_services.writable_blueprint_source,
            event_bus=svc.event_bus,
            library=svc.blueprint_library,
            threshold=meta_services.blueprint_harvest_threshold,
            policy=meta_services.harvest_policy,
            correlator=meta_services.harvest_correlator,
            distiller=meta_services.harvest_distiller,
        )

    # Delegate to standard bootstrap
    return create_executor(
        agent_registry=agent_registry,
        config=config,
        services=svc,
    )

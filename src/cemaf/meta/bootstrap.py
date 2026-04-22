"""Self-hosting composition root — create a DAGExecutor with meta-agents wired in."""

from __future__ import annotations

from dataclasses import dataclass

from cemaf.agents.registry import AgentRegistry
from cemaf.audit.factories import create_audit_system
from cemaf.audit.protocols import AuditLog, AuditTrail
from cemaf.bootstrap import create_executor
from cemaf.knowledge.factories import create_knowledge_graph
from cemaf.knowledge.protocols import KnowledgeGraph
from cemaf.mcp.bridges.openspec.protocols import OpenSpecRuntime
from cemaf.mcp.bridges.openspec.workspace import OpenSpecWorkspace
from cemaf.meta.registry import register_meta_agents, register_meta_specifier
from cemaf.orchestration.executor import DAGExecutor, ExecutorConfig
from cemaf.orchestration.services import RuntimeServices
from cemaf.tools.registry import ToolRegistry


@dataclass(frozen=True)
class MetaServices:
    """Additional services for meta-mode, extending RuntimeServices.

    OpenSpec deps live here, not in RuntimeServices, so the orchestration core
    has no static dependency on the mcp.bridges.openspec module.
    """

    audit_log: AuditLog | None = None
    audit_trail: AuditTrail | None = None
    knowledge_graph: KnowledgeGraph | None = None
    openspec_runtime: OpenSpecRuntime | None = None
    openspec_workspace: OpenSpecWorkspace | None = None


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

    # Resolve knowledge graph
    kg: KnowledgeGraph | None = None
    if meta_services and meta_services.knowledge_graph:
        kg = meta_services.knowledge_graph
    elif svc.memory_manager is not None:
        kg = create_knowledge_graph(memory_manager=svc.memory_manager)

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

    # Delegate to standard bootstrap
    return create_executor(
        agent_registry=agent_registry,
        config=config,
        services=svc,
    )

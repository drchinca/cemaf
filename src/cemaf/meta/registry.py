"""Registration helper — wire all meta-tools and meta-agents into existing registries."""

from __future__ import annotations

from cemaf.agents.registry import AgentRegistry
from cemaf.audit.protocols import AuditTrail
from cemaf.knowledge.protocols import KnowledgeGraph
from cemaf.llm.protocols import LLMClient
from cemaf.mcp.bridges.openspec.protocols import OpenSpecRuntime
from cemaf.mcp.bridges.openspec.tools import create_openspec_tools
from cemaf.mcp.bridges.openspec.workspace import OpenSpecWorkspace
from cemaf.meta.agents import (
    AgentSynthesizer,
    ArchitectAgent,
    AuditAgent,
    KnowledgeGraphAgent,
    SolutionDesignerAgent,
)
from cemaf.meta.goals import (
    ArchitectGoal,
    AuditGoal,
    KnowledgeGraphGoal,
    SolutionGoal,
    SpecGoal,
    SynthesizerGoal,
)
from cemaf.meta.specifier import MetaSpecifier
from cemaf.meta.tools import (
    GenerateDAGTool,
    IntrospectRegistryTool,
    KnowledgeGraphTool,
    TraceAnalyzerTool,
)
from cemaf.tools.registry import ToolRegistry


def register_meta_agents(
    agent_registry: AgentRegistry,
    *,
    tool_registry: ToolRegistry,
    audit_trail: AuditTrail,
    knowledge_graph: KnowledgeGraph,
) -> None:
    """Register all meta-tools and meta-agents into existing registries."""
    # Create meta-tools
    introspect_tool = IntrospectRegistryTool(
        agent_registry=agent_registry,
        tool_registry=tool_registry,
    )
    generate_dag_tool = GenerateDAGTool()
    trace_tool = TraceAnalyzerTool(audit_trail=audit_trail)
    kg_tool = KnowledgeGraphTool(knowledge_graph=knowledge_graph)

    # Register tools
    for tool in (introspect_tool, generate_dag_tool, trace_tool, kg_tool):
        tool_registry.register_instance(item=tool)

    # Create and register agents
    architect = ArchitectAgent(
        introspect_tool=introspect_tool,
        generate_dag_tool=generate_dag_tool,
    )
    agent_registry.register_agent(agent_instance=architect, goal_type=ArchitectGoal)

    synthesizer = AgentSynthesizer()
    agent_registry.register_agent(agent_instance=synthesizer, goal_type=SynthesizerGoal)

    auditor = AuditAgent(trace_analyzer_tool=trace_tool)
    agent_registry.register_agent(agent_instance=auditor, goal_type=AuditGoal)

    kg_agent = KnowledgeGraphAgent(kg_tool=kg_tool)
    agent_registry.register_agent(agent_instance=kg_agent, goal_type=KnowledgeGraphGoal)

    # Solution designer — the full self-hosting loop
    solution_designer = SolutionDesignerAgent(
        introspect_tool=introspect_tool,
        generate_dag_tool=generate_dag_tool,
        kg_tool=kg_tool,
    )
    agent_registry.register_agent(
        agent_instance=solution_designer,
        goal_type=SolutionGoal,
    )


def register_meta_specifier(
    agent_registry: AgentRegistry,
    *,
    tool_registry: ToolRegistry,
    workspace: OpenSpecWorkspace,
    runtime: OpenSpecRuntime | None = None,
    llm_client: LLMClient | None = None,
) -> None:
    """Register MetaSpecifier + the OpenSpec tool surface.

    Separate from register_meta_agents so callers without OpenSpec can opt out
    entirely. Both are composable: register_meta_agents first, then this when
    you have a workspace.
    """
    if runtime is not None:
        for tool in create_openspec_tools(runtime=runtime, workspace=workspace):
            tool_registry.register_instance(item=tool)

    specifier = MetaSpecifier(
        workspace=workspace,
        runtime=runtime,
        llm_client=llm_client,
    )
    agent_registry.register_agent(agent_instance=specifier, goal_type=SpecGoal)

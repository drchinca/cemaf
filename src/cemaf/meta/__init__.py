"""Self-hosting layer — CEMAF uses CEMAF to spec, scaffold, audit, and extend itself.

This is Layer 2 of the architecture: opt-in modules that CONSUME base-
framework primitives. Nothing in Layer 1 imports from `meta/`. The
dependency arrow is strictly one-way.

Key agents:
- `MetaArchitect` — designs DAGs from feature descriptions via registry
  introspection
- `MetaSpecifier` — authors OpenSpec change proposals (proposal + tasks +
  spec deltas), validates them via the OpenSpec MCP bridge
- `MetaSynthesizer` — generates CEMAF agent Python source from templates
- `MetaAuditor` — analyzes execution traces from the audit trail
- `MetaKnowledgeGraph` — queries and refreshes the entity knowledge graph
- `MetaScaffolder` — emits a runnable CEMAF-based app on disk (pyproject,
  package, bootstrap, tests) from a ProposalDoc + generated agents

Pre-built DAGs (in `meta.dags`):
- `create_self_audit_dag()` — MetaAuditor on recent execution traces
- `create_feature_synthesis_dag()` — Architect → Synthesizer
- `create_self_spec_dag()` — Specifier → Auditor
- `create_knowledge_refresh_dag()` — Auditor → KG refresh
- `create_app_synthesis_dag()` — Specifier → Architect → Synthesizer →
  Scaffolder (the headline: feature description → runnable CEMAF app)

Entry point:
    from cemaf.meta.bootstrap import create_meta_executor, MetaServices

    executor = create_meta_executor(
        agent_registry=registry,
        services=RuntimeServices(...),
        meta_services=MetaServices(
            audit_log=..., audit_trail=..., knowledge_graph=...,
            openspec_runtime=..., openspec_workspace=...,
        ),
    )
"""

from __future__ import annotations

from cemaf.meta.agents import (
    AgentSynthesizer,
    ArchitectAgent,
    AuditAgent,
    DreamAgent,
    KnowledgeGraphAgent,
)
from cemaf.meta.bootstrap import MetaServices, create_meta_executor
from cemaf.meta.dags import (
    create_dream_dag,
    create_feature_synthesis_dag,
    create_knowledge_refresh_dag,
    create_self_audit_dag,
)
from cemaf.meta.dreaming import DreamingMode, DreamingModeHandle
from cemaf.meta.goals import (
    ArchitectGoal,
    ArchitectResult,
    AuditGoal,
    AuditResult,
    DreamGoal,
    DreamResult,
    KnowledgeGraphGoal,
    KnowledgeGraphResult,
    SynthesizerGoal,
    SynthesizerResult,
)
from cemaf.meta.registry import register_dream_agent, register_meta_agents
from cemaf.meta.tools import (
    GenerateDAGTool,
    IntrospectRegistryTool,
    KnowledgeGraphTool,
    TraceAnalyzerTool,
)

__all__ = [
    # Agents
    "AgentSynthesizer",
    "ArchitectAgent",
    "AuditAgent",
    "DreamAgent",
    "KnowledgeGraphAgent",
    # Bootstrap
    "MetaServices",
    "create_meta_executor",
    # DAGs
    "create_dream_dag",
    "create_feature_synthesis_dag",
    "create_knowledge_refresh_dag",
    "create_self_audit_dag",
    # Dreaming mode
    "DreamingMode",
    "DreamingModeHandle",
    # Goals
    "ArchitectGoal",
    "ArchitectResult",
    "AuditGoal",
    "AuditResult",
    "DreamGoal",
    "DreamResult",
    "KnowledgeGraphGoal",
    "KnowledgeGraphResult",
    "SynthesizerGoal",
    "SynthesizerResult",
    # Registry
    "register_dream_agent",
    "register_meta_agents",
    # Tools
    "GenerateDAGTool",
    "IntrospectRegistryTool",
    "KnowledgeGraphTool",
    "TraceAnalyzerTool",
]

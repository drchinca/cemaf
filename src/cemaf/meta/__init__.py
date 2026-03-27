"""Meta-agents and meta-tools for CEMAF self-introspection and graph manipulation."""

from __future__ import annotations

from cemaf.meta.agents import (
    AgentSynthesizer,
    ArchitectAgent,
    AuditAgent,
    KnowledgeGraphAgent,
)
from cemaf.meta.bootstrap import MetaServices, create_meta_executor
from cemaf.meta.dags import (
    create_feature_synthesis_dag,
    create_knowledge_refresh_dag,
    create_self_audit_dag,
)
from cemaf.meta.goals import (
    ArchitectGoal,
    ArchitectResult,
    AuditGoal,
    AuditResult,
    KnowledgeGraphGoal,
    KnowledgeGraphResult,
    SynthesizerGoal,
    SynthesizerResult,
)
from cemaf.meta.registry import register_meta_agents
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
    "KnowledgeGraphAgent",
    # Bootstrap
    "MetaServices",
    "create_meta_executor",
    # DAGs
    "create_feature_synthesis_dag",
    "create_knowledge_refresh_dag",
    "create_self_audit_dag",
    # Goals
    "ArchitectGoal",
    "ArchitectResult",
    "AuditGoal",
    "AuditResult",
    "KnowledgeGraphGoal",
    "KnowledgeGraphResult",
    "SynthesizerGoal",
    "SynthesizerResult",
    # Registry
    "register_meta_agents",
    # Tools
    "GenerateDAGTool",
    "IntrospectRegistryTool",
    "KnowledgeGraphTool",
    "TraceAnalyzerTool",
]

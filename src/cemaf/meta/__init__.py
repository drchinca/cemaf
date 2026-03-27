"""Meta-agents and meta-tools for CEMAF self-introspection and graph manipulation."""

from __future__ import annotations

from cemaf.meta.agents import (
    AgentSynthesizer,
    ArchitectAgent,
    AuditAgent,
    KnowledgeGraphAgent,
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
    # Goals
    "ArchitectGoal",
    "ArchitectResult",
    "AuditGoal",
    "AuditResult",
    "KnowledgeGraphGoal",
    "KnowledgeGraphResult",
    "SynthesizerGoal",
    "SynthesizerResult",
    # Tools
    "GenerateDAGTool",
    "IntrospectRegistryTool",
    "KnowledgeGraphTool",
    "TraceAnalyzerTool",
]

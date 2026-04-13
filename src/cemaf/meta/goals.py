"""Pydantic goal/result models for CEMAF meta-agents."""

from __future__ import annotations

from pydantic import BaseModel, Field

from cemaf.core.types import JSON

# ---------------------------------------------------------------------------
# ArchitectAgent
# ---------------------------------------------------------------------------


class ArchitectGoal(BaseModel):
    """Design a DAG from a feature description."""

    feature_description: str = Field(description="What the DAG should accomplish")
    constraints: JSON = Field(default_factory=dict, description="Constraints on the design")


class ArchitectResult(BaseModel):
    """DAG specification produced by ArchitectAgent."""

    dag_spec: JSON = Field(description="Serialized DAG as dict")
    rationale: str = Field(description="Why this design was chosen")


# ---------------------------------------------------------------------------
# AgentSynthesizer
# ---------------------------------------------------------------------------


class SynthesizerGoal(BaseModel):
    """Generate agent code from a specification."""

    agent_name: str = Field(description="Name for the new agent")
    description: str = Field(description="What the agent should do")
    goal_fields: JSON = Field(default_factory=dict, description="Fields for the goal model")
    result_fields: JSON = Field(default_factory=dict, description="Fields for the result model")


class SynthesizerResult(BaseModel):
    """Generated Python source from AgentSynthesizer."""

    agent_code: str = Field(description="Python source for the agent")
    validation_notes: str = Field(default="", description="Notes on the generated code")


# ---------------------------------------------------------------------------
# AuditAgent
# ---------------------------------------------------------------------------


class AuditGoal(BaseModel):
    """Analyze execution traces."""

    run_id: str | None = Field(default=None, description="Specific run to audit")
    analysis_type: str = Field(default="full", description="full, quality, or anomalies")


class AuditResult(BaseModel):
    """Structured audit report from AuditAgent."""

    report: JSON = Field(default_factory=dict, description="Audit report data")
    summary: str = Field(default="", description="Human-readable summary")


# ---------------------------------------------------------------------------
# KnowledgeGraphAgent
# ---------------------------------------------------------------------------


class KnowledgeGraphGoal(BaseModel):
    """Manage knowledge graph operations."""

    operation: str = Field(description="refresh, query, or stats")
    query: str = Field(default="", description="Query text for search")
    entity_type: str | None = Field(default=None, description="Filter by entity type")


class KnowledgeGraphResult(BaseModel):
    """Output from KnowledgeGraphAgent."""

    entities: tuple[JSON, ...] = Field(default_factory=tuple, description="Matched entities")
    stats: JSON = Field(default_factory=dict, description="Graph statistics")


# ---------------------------------------------------------------------------
# DreamAgent
# ---------------------------------------------------------------------------


class SolutionGoal(BaseModel):
    """Design, generate, and version a multi-agent solution for a use case."""

    use_case: str = Field(description="Problem description to solve")
    constraints: JSON = Field(default_factory=dict, description="Design constraints")
    version_tag: str = Field(default="v1", description="Version label for this solution iteration")


class SolutionResult(BaseModel):
    """Complete solution output — DAG spec, generated code, version metadata."""

    dag_spec: JSON = Field(default_factory=dict, description="Designed DAG specification")
    generated_agents: tuple[JSON, ...] = Field(default_factory=tuple, description="Generated agent specs")
    version: str = Field(default="v1", description="Solution version")
    rationale: str = Field(default="", description="Design rationale")
    quality_score: float = Field(default=0.0, description="Self-evaluated quality score")


class DreamGoal(BaseModel):
    """Trigger a memory consolidation dream cycle."""

    max_consolidations: int = Field(default=50, description="Max items to consolidate per dream")


class DreamResult(BaseModel):
    """Output from DreamAgent consolidation."""

    consolidated_count: int = Field(default=0, description="Items consolidated")
    pruned_count: int = Field(default=0, description="Stale items pruned")
    summary: str = Field(default="", description="Human-readable dream summary")

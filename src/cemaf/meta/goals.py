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

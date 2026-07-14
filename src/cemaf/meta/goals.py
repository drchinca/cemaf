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


# ---------------------------------------------------------------------------
# MetaSpecifier — OpenSpec proposal authoring
# ---------------------------------------------------------------------------


class Scenario(BaseModel):
    """A single GIVEN/WHEN/THEN scenario under a requirement."""

    model_config = {"frozen": True}

    name: str = Field(min_length=1, description="Scenario name, rendered as '#### Scenario: <name>'")
    given: tuple[str, ...] = Field(min_length=1, description="GIVEN clauses (at least one)")
    when: tuple[str, ...] = Field(min_length=1, description="WHEN clauses (at least one)")
    then: tuple[str, ...] = Field(min_length=1, description="THEN clauses (at least one)")


class Requirement(BaseModel):
    """A single requirement within a capability delta."""

    model_config = {"frozen": True}

    name: str = Field(min_length=1, description="Requirement name, rendered as '### Requirement: <name>'")
    statement: str = Field(min_length=1, description="The SHALL statement")
    scenarios: tuple[Scenario, ...] = Field(min_length=1, description="At least one scenario")


class CapabilityDelta(BaseModel):
    """Deltas to apply to a capability's spec."""

    model_config = {"frozen": True}

    capability: str = Field(
        min_length=1, description="Capability directory name (specs/<capability>/spec.md)"
    )
    added_requirements: tuple[Requirement, ...] = Field(min_length=1, description="At least one requirement")


class ProposalDoc(BaseModel):
    """Typed representation of an OpenSpec change proposal."""

    model_config = {"frozen": True}

    change_id: str = Field(min_length=1, description="Change directory name under openspec/changes/")
    title: str = Field(min_length=1, description="Human-readable title for the proposal")
    why: str = Field(min_length=1, description="Motivation paragraph(s)")
    what_changes: tuple[str, ...] = Field(
        default_factory=tuple, description="Bulleted summary of what changes"
    )
    impact: tuple[str, ...] = Field(default_factory=tuple, description="Bulleted impact notes")
    tasks: tuple[str, ...] = Field(default_factory=tuple, description="Flat task list")
    deltas: tuple[CapabilityDelta, ...] = Field(min_length=1, description="At least one capability delta")


class SpecGoal(BaseModel):
    """Describe a feature for which MetaSpecifier should author an OpenSpec proposal."""

    feature_description: str = Field(description="What the feature does; why it matters")
    change_id: str = Field(description="OpenSpec change identifier (kebab-case)")
    capabilities: tuple[str, ...] = Field(
        default_factory=tuple, description="Capability directories this change touches"
    )
    constraints: JSON = Field(default_factory=dict, description="Optional constraints")


class SpecResult(BaseModel):
    """Outcome of a MetaSpecifier run."""

    model_config = {"frozen": True}

    change_id: str
    proposal: ProposalDoc
    rendered_files: dict[str, str] = Field(
        default_factory=dict, description="Map of relative path -> file contents"
    )
    validation_passed: bool = False
    diagnostics: tuple[dict[str, str], ...] = Field(
        default_factory=tuple, description="Structured diagnostics from openspec validate"
    )
    runtime: str = Field(default="", description="Display name of the OpenSpec runtime used")


# ---------------------------------------------------------------------------
# MetaScaffolder — runnable CEMAF-based app synthesis
# ---------------------------------------------------------------------------


class GeneratedAgent(BaseModel):
    """One synthesized agent — keeps class name, goal class name, and source aligned.

    Replaces the earlier parallel-tuple shape (agent_sources + class_names) where
    misalignment produced a silent NameError at import time.
    """

    model_config = {"frozen": True}

    class_name: str = Field(min_length=1, description="Agent class name")
    goal_class_name: str = Field(min_length=1, description="Pydantic goal class used for registration")
    source: str = Field(min_length=1, description="Python source defining both classes")


class ProjectSkeleton(BaseModel):
    """Typed representation of a scaffolded CEMAF-based app."""

    model_config = {"frozen": True}

    project_name: str = Field(min_length=1, description="Directory name")
    module_name: str = Field(min_length=1, description="Python module name (identifier)")
    title: str = Field(min_length=1, description="Human-readable title")
    description: str = Field(min_length=1, description="One-line app description")
    generated_agents: tuple[GeneratedAgent, ...] = Field(
        default_factory=tuple, description="Synthesized agents to register"
    )
    cemaf_source: str = Field(
        default="",
        description="pyproject spec for cemaf (e.g. 'cemaf @ git+https://…'); empty uses the package name",
    )


class ScaffoldGoal(BaseModel):
    """Input to MetaScaffolder: a ProposalDoc + synthesized agents + where to write."""

    model_config = {"arbitrary_types_allowed": True}

    proposal: ProposalDoc
    project_name: str = Field(min_length=1, description="Directory + python module name")
    target_dir: str = Field(min_length=1, description="Parent directory for project_name/")
    generated_agents: tuple[GeneratedAgent, ...] = Field(
        default_factory=tuple, description="Synthesized agents to register"
    )
    cemaf_source: str = Field(
        default="",
        description="pyproject spec for cemaf; empty uses the package name",
    )
    overwrite: bool = Field(default=False, description="If True, replace existing project dir")


class ScaffoldResult(BaseModel):
    """Outcome of a MetaScaffolder run."""

    model_config = {"frozen": True}

    project_root: str
    module_name: str
    written_files: tuple[str, ...] = Field(default_factory=tuple)

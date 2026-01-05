"""
cemaf.blueprint.schema - Semantic blueprint models for content generation.

Based on Denis Rothman's Semantic Blueprint concept for structured context engineering.
A blueprint defines HOW to accomplish a task, separate from WHAT data to use.
"""

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from cemaf.core.types import JSON

# Type aliases for role metadata
ContentStyle = Literal["narrative", "technical", "creative", "persuasive", "marketing"]
Perspective = Literal["first-person", "second-person", "third-person", "omniscient"]
AnalysisDepth = Literal["surface", "moderate", "detailed", "comprehensive"]
AnalysisMethodology = Literal["quantitative", "qualitative", "mixed", "comparative"]
AudienceLevel = Literal["beginner", "intermediate", "advanced", "expert"]
ComparisonFormat = Literal["side-by-side", "narrative", "table", "matrix"]
BiasAwareness = Literal["objective", "preferential", "neutral"]
TeachingStyle = Literal["socratic", "lecture", "demonstration", "discovery"]
KnowledgeLevel = Literal["beginner", "intermediate", "advanced"]
ValidationType = Literal["schema", "business_rules", "compliance", "quality"]


class OutputContract(BaseModel):
    """
    Defines expected deliverables and output format.

    Specifies format, required sections, and content requirements to prevent
    model from responding with unstructured prose instead of requested output.
    """

    model_config = {"frozen": True}

    format: Literal["json", "yaml", "markdown", "python", "sql"] = "yaml"
    required_sections: tuple[str, ...] = ()
    must_include: tuple[str, ...] = ()
    forbidden: tuple[str, ...] = ()
    schema_definition: str = ""  # Optional JSON Schema or YAML schema
    metadata: JSON = Field(default_factory=dict)


class ExecutionPolicy(BaseModel):
    """
    Defines execution semantics for idempotency and retry behavior.

    Specifies checkpoint strategy, retry conditions, and failure handling
    for production data pipelines.
    """

    model_config = {"frozen": True}

    # Incremental processing strategy
    incremental_strategy: Literal["full", "watermark", "checkpoint"] = "full"
    incremental_field: str = ""  # e.g., "updated_at", "event_timestamp"
    checkpoint_location: str = ""  # e.g., "s3://bucket/checkpoints"

    # Idempotency
    idempotency_key: str = "run_id"  # Field to ensure idempotent operations
    deterministic_batching: bool = True  # Use consistent batch keys

    # Retry semantics
    max_retries: int = 3
    retry_on: tuple[str, ...] = ("rate_limit", "transient_network", "timeout")
    fail_on: tuple[str, ...] = ("data_quality_fail", "schema_mismatch")

    # Execution mode
    exactly_once: bool = False  # vs effectively-once (at-least-once + idempotency)

    metadata: JSON = Field(default_factory=dict)


class SecurityPolicy(BaseModel):
    """
    Defines security requirements for data handling.

    Specifies PII handling, encryption requirements, and secret management
    for compliance with data protection regulations.
    """

    model_config = {"frozen": True}

    pii_fields: tuple[str, ...] = ()  # List of PII field names
    encryption: Literal["at_rest", "in_transit", "at_rest_and_in_transit", "none"] = "none"

    # Secret management
    secret_rotation: bool = False
    secret_provider: Literal["kms", "vault", "env", "none"] = "none"
    secret_rotation_days: int = 90

    # Compliance
    compliance_frameworks: tuple[str, ...] = ()  # e.g., ("GDPR", "HIPAA", "SOC2")

    metadata: JSON = Field(default_factory=dict)


class SCD2Config(BaseModel):
    """Configuration for Slowly Changing Dimension Type 2."""

    model_config = {"frozen": True}

    business_key: str  # Natural key field
    effective_from: str = "valid_from_ts"
    effective_to: str = "valid_to_ts"
    is_current: str = "is_current"
    record_hash: str = "attr_hash"  # For change detection


class RateLimitConfig(BaseModel):
    """Configuration for API rate limiting."""

    model_config = {"frozen": True}

    max_requests_per_minute: int = 100
    max_requests_per_day: int = 10000
    on_429_action: Literal["backoff_exponential", "backoff_linear", "fail"] = "backoff_exponential"
    backoff_initial_delay_seconds: float = 1.0
    backoff_max_delay_seconds: float = 300.0


class DataContract(BaseModel):
    """
    Defines data schema, keys, and processing requirements for an entity.

    Specifies table/object structure, identity strategies, and processing
    patterns for data engineering use cases.
    """

    model_config = {"frozen": True}

    # Schema definition
    schema_type: Literal["table", "object", "file", "stream", "api"] = "table"
    fields: tuple[str, ...] = ()  # Column/field names
    primary_key: str = ""
    partition_keys: tuple[str, ...] = ()

    # Incremental processing
    incremental_field: str = ""  # Watermark field (e.g., "updated_at")
    incremental_mode: Literal["append", "upsert", "full_refresh"] = "append"

    # Deduplication and identity
    dedup_keys: tuple[str, ...] = ()  # For deduplication
    match_features: tuple[str, ...] = ()  # For fuzzy matching

    # SCD2 configuration (for dimension tables)
    scd2_config: SCD2Config | None = None

    # Rate limiting (for APIs)
    rate_limit: RateLimitConfig | None = None

    # Data quality
    required_fields: tuple[str, ...] = ()
    nullable_fields: tuple[str, ...] = ()

    metadata: JSON = Field(default_factory=dict)


class EntityType(str, Enum):
    """
    Entity type discriminator for blueprint context entities.

    Context entities can represent ANY structured element in a prompt:
    - Narrative: characters, speakers, personas
    - Technical: components, systems, modules, services
    - Analysis: data sources, metrics, dimensions
    - Code generation: classes, functions, patterns
    - Or completely omitted if not needed (entities are OPTIONAL)
    """

    CONTENT = "content"  # Content generation (storytelling, articles, creative)
    ANALYSIS = "analysis"  # Data analysis, research, evaluation
    TECHNICAL = "technical"  # Code, documentation, specifications
    COMPARATIVE = "comparative"  # Compare/contrast options
    EDUCATIONAL = "educational"  # Teaching, explaining concepts
    VALIDATION = "validation"  # Compliance checking, verification


class ContextEntity(BaseModel):
    """
    General-purpose role abstraction for Blueprint (replaces narrative-specific Participant).

    Uses discriminated union pattern with EntityType enum. Follows CEMAF's ContextSource pattern.
    Designed for pluggable, contextual/niche-specific roles.

    Factory methods for type-safe creation:
    - ContextEntity.content() - Content generation (storytelling, articles, creative writing)
    - ContextEntity.analysis() - Data analysis, research, evaluation
    - ContextEntity.technical() - Code, documentation, technical specs
    - ContextEntity.comparative() - Compare/contrast multiple options
    - ContextEntity.educational() - Teaching, explaining concepts
    - ContextEntity.validation() - Compliance checking, verification

    Example:
        >>> role = ContextEntity.content(
        ...     name="technical_writer",
        ...     description="Create clear technical documentation",
        ...     style="technical",
        ...     traits=("precise", "clear")
        ... )
        >>> assert role.entity_type == EntityType.CONTENT
    """

    model_config = {"frozen": True}

    # Required fields
    name: str
    entity_type: EntityType

    # Common optional fields
    description: str = ""
    traits: tuple[str, ...] = ()
    voice: str = ""
    constraints: tuple[str, ...] = ()

    # Variant-specific config (immutable via Pydantic)
    metadata: JSON = Field(default_factory=dict)

    # Data contract for data engineering use cases
    data_contract: DataContract | None = None

    # Token budget integration
    token_priority: int = Field(default=5, description="Priority for token budget allocation (1-15)")
    compressible: bool = Field(default=True, description="Can role description be shortened if needed")
    min_tokens: int = Field(default=0, description="Minimum tokens to preserve")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Validate name is not empty."""
        if not v or not v.strip():
            raise ValueError("name cannot be empty or whitespace")
        return v.strip()

    @field_validator("token_priority")
    @classmethod
    def validate_priority(cls, v: int) -> int:
        """Validate priority is in valid range."""
        if not 1 <= v <= 15:
            raise ValueError("token_priority must be between 1 and 15")
        return v

    @model_validator(mode="after")
    def set_default_description(self) -> ContextEntity:
        """Auto-generate description if not provided."""
        if not self.description:
            # Use object.__setattr__ for frozen model
            object.__setattr__(self, "description", f"{self.entity_type.value.title()} role")
        return self

    @classmethod
    def content(
        cls,
        name: str,
        *,
        description: str = "",
        style: ContentStyle = "narrative",
        perspective: Perspective = "third-person",
        tone: str = "neutral",
        traits: tuple[str, ...] = (),
        voice: str = "",
        constraints: tuple[str, ...] = (),
        token_priority: int = 4,
        **extra: Any,
    ) -> ContextEntity:
        """
        Create a content generation role.

        Args:
            name: ContextEntity identifier
            description: ContextEntity description (auto-generated if empty)
            style: Content style
            perspective: Narrative point of view
            tone: Content tone
            traits: Personality characteristics
            voice: Voice/tone guidelines
            constraints: Content constraints
            token_priority: Priority for token budget (1-15, default 5)
            **extra: Additional metadata fields

        Returns:
            Immutable ContextEntity configured for content generation
        """
        metadata: dict[str, Any] = {
            "style": style,
            "perspective": perspective,
            "tone": tone,
        }
        metadata.update(extra)

        return cls(
            name=name,
            entity_type=EntityType.CONTENT,
            description=description or "Content generation role",
            traits=traits,
            voice=voice,
            constraints=constraints,
            metadata=metadata,
            token_priority=token_priority,
        )

    @classmethod
    def analysis(
        cls,
        name: str,
        *,
        description: str = "",
        methodology: AnalysisMethodology = "quantitative",
        depth: AnalysisDepth = "detailed",
        focus_areas: tuple[str, ...] = (),
        traits: tuple[str, ...] = (),
        voice: str = "",
        constraints: tuple[str, ...] = (),
        token_priority: int = 7,
        **extra: Any,
    ) -> ContextEntity:
        """
        Create an analysis role.

        Args:
            name: ContextEntity identifier
            description: ContextEntity description
            methodology: Analysis approach
            depth: Analysis depth level
            focus_areas: Specific areas to analyze
            traits: Analytical characteristics
            voice: Analytical tone
            constraints: Analysis constraints
            token_priority: Priority for token budget (1-15)
            **extra: Additional metadata

        Returns:
            Immutable ContextEntity configured for analysis
        """
        metadata: dict[str, Any] = {
            "methodology": methodology,
            "depth": depth,
            "focus_areas": focus_areas,
        }
        metadata.update(extra)

        return cls(
            name=name,
            entity_type=EntityType.ANALYSIS,
            description=description or "Analysis role",
            traits=traits,
            voice=voice,
            constraints=constraints,
            metadata=metadata,
            token_priority=token_priority,
        )

    @classmethod
    def technical(
        cls,
        name: str,
        *,
        description: str = "",
        domain: str = "software",
        audience_level: AudienceLevel = "intermediate",
        include_code_examples: bool = True,
        include_diagrams: bool = False,
        traits: tuple[str, ...] = (),
        voice: str = "",
        constraints: tuple[str, ...] = (),
        token_priority: int = 7,
        **extra: Any,
    ) -> ContextEntity:
        """
        Create a technical role.

        Args:
            name: ContextEntity identifier
            description: ContextEntity description
            domain: Technical domain
            audience_level: Target audience expertise
            include_code_examples: Include code samples
            include_diagrams: Include diagrams
            traits: Technical characteristics
            voice: Technical tone
            constraints: Technical constraints
            token_priority: Priority for token budget
            **extra: Additional metadata

        Returns:
            Immutable ContextEntity configured for technical content
        """
        metadata: dict[str, Any] = {
            "domain": domain,
            "audience_level": audience_level,
            "include_code_examples": include_code_examples,
            "include_diagrams": include_diagrams,
        }
        metadata.update(extra)

        return cls(
            name=name,
            entity_type=EntityType.TECHNICAL,
            description=description or "Technical role",
            traits=traits,
            voice=voice,
            constraints=constraints,
            metadata=metadata,
            token_priority=token_priority,
        )

    @classmethod
    def comparative(
        cls,
        name: str,
        *,
        description: str = "",
        dimensions: tuple[str, ...] = (),
        format: ComparisonFormat = "side-by-side",
        bias_awareness: BiasAwareness = "objective",
        traits: tuple[str, ...] = (),
        voice: str = "",
        constraints: tuple[str, ...] = (),
        token_priority: int = 5,
        **extra: Any,
    ) -> ContextEntity:
        """
        Create a comparative role.

        Args:
            name: ContextEntity identifier
            description: ContextEntity description
            dimensions: Comparison dimensions
            format: Comparison format
            bias_awareness: Approach to bias
            traits: Comparative characteristics
            voice: Comparative tone
            constraints: Comparison constraints
            token_priority: Priority for token budget
            **extra: Additional metadata

        Returns:
            Immutable ContextEntity configured for comparison
        """
        metadata: dict[str, Any] = {
            "dimensions": dimensions,
            "format": format,
            "bias_awareness": bias_awareness,
        }
        metadata.update(extra)

        return cls(
            name=name,
            entity_type=EntityType.COMPARATIVE,
            description=description or "Comparative role",
            traits=traits,
            voice=voice,
            constraints=constraints,
            metadata=metadata,
            token_priority=token_priority,
        )

    @classmethod
    def educational(
        cls,
        name: str,
        *,
        description: str = "",
        teaching_style: TeachingStyle = "socratic",
        knowledge_level: KnowledgeLevel = "beginner",
        include_examples: bool = True,
        include_exercises: bool = False,
        traits: tuple[str, ...] = (),
        voice: str = "",
        constraints: tuple[str, ...] = (),
        token_priority: int = 5,
        **extra: Any,
    ) -> ContextEntity:
        """
        Create an educational role.

        Args:
            name: ContextEntity identifier
            description: ContextEntity description
            teaching_style: Pedagogical approach
            knowledge_level: Student's current level
            include_examples: Include examples
            include_exercises: Include practice exercises
            traits: Teaching characteristics
            voice: Teaching tone
            constraints: Educational constraints
            token_priority: Priority for token budget
            **extra: Additional metadata

        Returns:
            Immutable ContextEntity configured for education
        """
        metadata: dict[str, Any] = {
            "teaching_style": teaching_style,
            "knowledge_level": knowledge_level,
            "include_examples": include_examples,
            "include_exercises": include_exercises,
        }
        metadata.update(extra)

        return cls(
            name=name,
            entity_type=EntityType.EDUCATIONAL,
            description=description or "Educational role",
            traits=traits,
            voice=voice,
            constraints=constraints,
            metadata=metadata,
            token_priority=token_priority,
        )

    @classmethod
    def validation(
        cls,
        name: str,
        *,
        description: str = "",
        validation_type: ValidationType = "schema",
        rules: tuple[str, ...] = (),
        severity_levels: tuple[str, ...] = ("error", "warning"),
        auto_fix: bool = False,
        traits: tuple[str, ...] = (),
        voice: str = "",
        constraints: tuple[str, ...] = (),
        token_priority: int = 9,
        **extra: Any,
    ) -> ContextEntity:
        """
        Create a validation role.

        Args:
            name: ContextEntity identifier
            description: ContextEntity description
            validation_type: Type of validation
            rules: Validation rules
            severity_levels: Issue severity categories
            auto_fix: Attempt automatic fixes
            traits: Validation characteristics
            voice: Validation tone
            constraints: Validation constraints
            token_priority: Priority for token budget
            **extra: Additional metadata

        Returns:
            Immutable ContextEntity configured for validation
        """
        metadata: dict[str, Any] = {
            "validation_type": validation_type,
            "rules": rules,
            "severity_levels": severity_levels,
            "auto_fix": auto_fix,
        }
        metadata.update(extra)

        return cls(
            name=name,
            entity_type=EntityType.VALIDATION,
            description=description or "Validation role",
            traits=traits,
            voice=voice,
            constraints=constraints,
            metadata=metadata,
            token_priority=token_priority,
        )

    def to_prompt(self) -> str:
        """
        Format role for LLM prompt (structured markdown).

        Returns:
            Formatted prompt string ready for LLM consumption
        """
        sections: list[str] = [
            f"# ContextEntity: {self.name}",
            f"Type: {self.entity_type.value.title()}",
        ]

        if self.description:
            sections.append(f"\n## Description\n{self.description}")

        if self.traits:
            sections.append(f"\n## Traits\n{', '.join(self.traits)}")

        if self.voice:
            sections.append(f"\n## Voice\n{self.voice}")

        if self.constraints:
            sections.append("\n## Constraints")
            sections.extend(f"- {c}" for c in self.constraints)

        # Add role-type-specific metadata highlights
        if self.metadata:
            type_specific = self._format_type_specific_metadata()
            if type_specific:
                sections.append(type_specific)

        # Add data contract section
        if self.data_contract:
            data_contract_section = self._format_data_contract()
            if data_contract_section:
                sections.append(data_contract_section)

        return "\n".join(sections)

    def _format_type_specific_metadata(self) -> str:
        """Format role-type-specific metadata for prompt."""
        if self.entity_type == EntityType.CONTENT:
            parts = []
            if "style" in self.metadata:
                parts.append(f"Style: {self.metadata['style']}")
            if "perspective" in self.metadata:
                parts.append(f"Perspective: {self.metadata['perspective']}")
            return "\n## Content Guidelines\n" + "\n".join(parts) if parts else ""

        elif self.entity_type == EntityType.ANALYSIS:
            parts = []
            if "methodology" in self.metadata:
                parts.append(f"Methodology: {self.metadata['methodology']}")
            if "depth" in self.metadata:
                parts.append(f"Depth: {self.metadata['depth']}")
            return "\n## Analysis Approach\n" + "\n".join(parts) if parts else ""

        elif self.entity_type == EntityType.TECHNICAL:
            parts = []
            if "domain" in self.metadata:
                parts.append(f"Domain: {self.metadata['domain']}")
            if "audience_level" in self.metadata:
                parts.append(f"Audience: {self.metadata['audience_level']}")
            return "\n## Technical Specs\n" + "\n".join(parts) if parts else ""

        elif self.entity_type == EntityType.COMPARATIVE:
            parts = []
            if "dimensions" in self.metadata and self.metadata["dimensions"]:
                parts.append(f"Compare on: {', '.join(self.metadata['dimensions'])}")
            if "format" in self.metadata:
                parts.append(f"Format: {self.metadata['format']}")
            return "\n## Comparison Setup\n" + "\n".join(parts) if parts else ""

        elif self.entity_type == EntityType.EDUCATIONAL:
            parts = []
            if "teaching_style" in self.metadata:
                parts.append(f"Teaching Style: {self.metadata['teaching_style']}")
            if "knowledge_level" in self.metadata:
                parts.append(f"Student Level: {self.metadata['knowledge_level']}")
            return "\n## Teaching Approach\n" + "\n".join(parts) if parts else ""

        elif self.entity_type == EntityType.VALIDATION:
            parts = []
            if "validation_type" in self.metadata:
                parts.append(f"Validation Type: {self.metadata['validation_type']}")
            if "rules" in self.metadata and self.metadata["rules"]:
                parts.append(f"Rules: {', '.join(self.metadata['rules'])}")
            return "\n## Validation Config\n" + "\n".join(parts) if parts else ""

        return ""

    def _format_data_contract(self) -> str:
        """Format data contract for prompt."""
        if not self.data_contract:
            return ""

        dc = self.data_contract
        parts = ["\n## Data Contract"]

        parts.append(f"Schema Type: {dc.schema_type}")

        if dc.fields:
            parts.append(f"Fields: {', '.join(dc.fields)}")

        if dc.primary_key:
            parts.append(f"Primary Key: {dc.primary_key}")

        if dc.partition_keys:
            parts.append(f"Partition Keys: {', '.join(dc.partition_keys)}")

        if dc.incremental_field:
            parts.append(f"Incremental Field: {dc.incremental_field} (mode: {dc.incremental_mode})")

        if dc.dedup_keys:
            parts.append(f"Deduplication Keys: {', '.join(dc.dedup_keys)}")

        if dc.scd2_config:
            scd2 = dc.scd2_config
            parts.append(
                f"SCD2: business_key={scd2.business_key}, "
                f"valid_from={scd2.effective_from}, "
                f"valid_to={scd2.effective_to}"
            )

        if dc.rate_limit:
            rl = dc.rate_limit
            parts.append(f"Rate Limit: {rl.max_requests_per_minute} req/min, on_429={rl.on_429_action}")

        return "\n".join(parts)


class SceneGoal(BaseModel):
    """Goal/objective of a blueprint scene."""

    model_config = {"frozen": True}

    objective: str  # REQUIRED - what should be accomplished
    success_criteria: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()
    priority: int = 1


class StyleGuide(BaseModel):
    """Style guidelines for content generation."""

    model_config = {"frozen": True}

    tone: str = ""  # e.g., "professional", "casual", "urgent"
    format: str = ""  # e.g., "markdown", "plain", "html"
    length_hint: str = ""  # e.g., "concise", "detailed", "brief"
    vocabulary: tuple[str, ...] = ()  # Preferred terms
    avoid: tuple[str, ...] = ()  # Terms to avoid
    examples: tuple[str, ...] = ()  # Example outputs

    def is_empty(self) -> bool:
        """Check if the style guide has any non-default values."""
        return (
            not self.tone
            and not self.format
            and not self.length_hint
            and not self.vocabulary
            and not self.avoid
            and not self.examples
        )


class Participant(BaseModel):
    """A participant/role in a blueprint scene."""

    model_config = {"frozen": True}

    name: str
    role: str
    traits: tuple[str, ...] = ()
    voice: str = ""  # Voice/tone description
    constraints: tuple[str, ...] = ()


class Blueprint(BaseModel):
    """
    Semantic blueprint for content generation.

    Based on Denis Rothman's structured context engineering approach.
    A blueprint defines HOW to accomplish a task, separate from WHAT data to use.
    """

    model_config = {"frozen": True}

    # Required fields
    id: str
    name: str
    scene_goal: SceneGoal

    # Optional fields
    description: str = ""
    style_guide: StyleGuide = Field(default_factory=StyleGuide)
    entities: tuple[ContextEntity, ...] = ()
    instruction: str = ""  # Detailed instructions for the task

    # Metadata
    version: str = "1.0"
    tags: tuple[str, ...] = ()
    metadata: JSON = Field(default_factory=dict)

    # Production policies and contracts
    output_contract: OutputContract | None = None
    execution_policy: ExecutionPolicy | None = None
    security_policy: SecurityPolicy | None = None

    def to_prompt(self) -> str:
        """
        Convert blueprint to a structured prompt string.

        Returns a formatted string suitable for LLM consumption.
        """
        sections: list[str] = []

        # Goal section (always included)
        sections.append(self._format_goal_section())

        # Style section (if non-empty)
        if not self.style_guide.is_empty():
            sections.append(self._format_style_section())

        # Entities section (OPTIONAL - many blueprints won't need this)
        if self.entities:
            sections.append(self._format_entities_section())

        # Instructions section (if non-empty)
        if self.instruction:
            sections.append(self._format_instructions_section())

        # Output contract section
        if self.output_contract:
            output_section = self._format_output_contract_section()
            if output_section:
                sections.append(output_section)

        # Execution policy section
        if self.execution_policy:
            exec_section = self._format_execution_policy_section()
            if exec_section:
                sections.append(exec_section)

        # Security policy section
        if self.security_policy:
            sec_section = self._format_security_policy_section()
            if sec_section:
                sections.append(sec_section)

        return "\n\n".join(sections)

    def _format_goal_section(self) -> str:
        """Format the goal section of the prompt."""
        lines = ["## Goal", f"Objective: {self.scene_goal.objective}"]

        if self.scene_goal.success_criteria:
            lines.append("Success Criteria:")
            for criterion in self.scene_goal.success_criteria:
                lines.append(f"  - {criterion}")

        if self.scene_goal.constraints:
            lines.append("Constraints:")
            for constraint in self.scene_goal.constraints:
                lines.append(f"  - {constraint}")

        if self.scene_goal.priority != 1:
            lines.append(f"Priority: {self.scene_goal.priority}")

        return "\n".join(lines)

    def _format_style_section(self) -> str:
        """Format the style section of the prompt."""
        lines = ["## Style Guide"]

        if self.style_guide.tone:
            lines.append(f"Tone: {self.style_guide.tone}")

        if self.style_guide.format:
            lines.append(f"Format: {self.style_guide.format}")

        if self.style_guide.length_hint:
            lines.append(f"Length: {self.style_guide.length_hint}")

        if self.style_guide.vocabulary:
            lines.append(f"Preferred Terms: {', '.join(self.style_guide.vocabulary)}")

        if self.style_guide.avoid:
            lines.append(f"Avoid: {', '.join(self.style_guide.avoid)}")

        if self.style_guide.examples:
            lines.append("Examples:")
            for example in self.style_guide.examples:
                lines.append(f"  - {example}")

        return "\n".join(lines)

    def _format_entities_section(self) -> str:
        """Format the entities section (OPTIONAL - omit if not needed for your use case)."""
        if not self.entities:
            return ""

        lines = ["## Context Entities"]
        for entity in self.entities:
            lines.append(entity.to_prompt())

        return "\n".join(lines)

    def _format_instructions_section(self) -> str:
        """Format the instructions section of the prompt."""
        return f"## Instructions\n{self.instruction}"

    def _format_output_contract_section(self) -> str:
        """Format output contract section."""
        if not self.output_contract:
            return ""

        oc = self.output_contract

        # Skip if all defaults
        if (
            oc.format == "yaml"
            and not oc.required_sections
            and not oc.must_include
            and not oc.forbidden
            and not oc.schema_definition
        ):
            return ""

        lines = ["## Output Contract", f"Format: {oc.format}"]

        if oc.required_sections:
            lines.append("Required Sections:")
            for section in oc.required_sections:
                lines.append(f"  - {section}")

        if oc.must_include:
            lines.append("Must Include:")
            for item in oc.must_include:
                lines.append(f"  - {item}")

        if oc.forbidden:
            lines.append("Forbidden:")
            for item in oc.forbidden:
                lines.append(f"  - {item}")

        if oc.schema_definition:
            lines.append(f"Schema:\n{oc.schema_definition}")

        return "\n".join(lines)

    def _format_execution_policy_section(self) -> str:
        """Format execution policy section."""
        if not self.execution_policy:
            return ""

        ep = self.execution_policy
        lines = ["## Execution Policy"]

        lines.append(f"Incremental Strategy: {ep.incremental_strategy}")
        if ep.incremental_field:
            lines.append(f"Incremental Field: {ep.incremental_field}")
        if ep.checkpoint_location:
            lines.append(f"Checkpoint Location: {ep.checkpoint_location}")

        lines.append(f"Idempotency Key: {ep.idempotency_key}")
        lines.append(f"Exactly-Once: {ep.exactly_once}")
        lines.append(f"Max Retries: {ep.max_retries}")

        if ep.retry_on:
            lines.append(f"Retry On: {', '.join(ep.retry_on)}")
        if ep.fail_on:
            lines.append(f"Fail On: {', '.join(ep.fail_on)}")

        return "\n".join(lines)

    def _format_security_policy_section(self) -> str:
        """Format security policy section."""
        if not self.security_policy:
            return ""

        sp = self.security_policy
        lines = ["## Security Policy"]

        if sp.pii_fields:
            lines.append(f"PII Fields: {', '.join(sp.pii_fields)}")

        lines.append(f"Encryption: {sp.encryption}")

        if sp.secret_rotation:
            lines.append(f"Secret Rotation: {sp.secret_rotation_days} days via {sp.secret_provider}")

        if sp.compliance_frameworks:
            lines.append(f"Compliance: {', '.join(sp.compliance_frameworks)}")

        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Blueprint:
        """Create blueprint from dictionary."""
        return cls.model_validate(data)

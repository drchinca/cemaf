"""
Context entities for blueprint composition.

Defines entity types, factory methods, and metadata patterns for
representing various roles and components in semantic blueprints.
"""

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from cemaf.blueprint.contracts import DataContract
from cemaf.core.types import JSON

# =============================================================================
# Type aliases for common patterns (extensible at runtime via # type: ignore)
# =============================================================================
#
# These Literal types provide IDE autocomplete and guidance for common
# patterns, but are NOT exhaustive. Python runtime doesn't enforce them.
#
# For domain-specific extensions, use custom values with # type: ignore.
# See examples/extensibility_patterns.py for demonstrations.
# =============================================================================

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


class EntityType(StrEnum):
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
    Designed for pluggable, contextual/niche-specific roles across various domains.

    Factory methods for type-safe creation:
    - ContextEntity.content() - Content generation (storytelling, articles, creative writing)
    - ContextEntity.analysis() - Data analysis, research, evaluation
    - ContextEntity.technical() - Code, documentation, technical specs
    - ContextEntity.comparative() - Compare/contrast multiple options
    - ContextEntity.educational() - Teaching, explaining concepts
    - ContextEntity.validation() - Compliance checking, verification

    Examples:
        >>> # Content generation role
        >>> writer = ContextEntity.content(
        ...     name="technical_writer",
        ...     description="Create clear technical documentation",
        ...     style="technical",
        ...     traits=("precise", "clear")
        ... )
        >>> assert writer.entity_type == EntityType.CONTENT

        >>> # Analysis role
        >>> analyst = ContextEntity.analysis(
        ...     name="data_analyst",
        ...     methodology="quantitative",
        ...     depth="comprehensive"
        ... )
        >>> assert analyst.entity_type == EntityType.ANALYSIS

        >>> # Technical role
        >>> engineer = ContextEntity.technical(
        ...     name="code_reviewer",
        ...     domain="software",
        ...     audience_level="advanced"
        ... )
        >>> assert engineer.entity_type == EntityType.TECHNICAL
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
    def _create_entity(
        cls,
        *,
        name: str,
        entity_type: EntityType,
        description: str,
        default_description: str,
        traits: tuple[str, ...],
        voice: str,
        constraints: tuple[str, ...],
        token_priority: int,
        type_specific_metadata: dict[str, Any],
        extra: dict[str, Any],
    ) -> ContextEntity:
        """
        Internal helper to reduce duplication in factory methods.

        Consolidates common entity creation logic across all factory methods.
        """
        metadata = type_specific_metadata.copy()
        metadata.update(extra)

        return cls(
            name=name,
            entity_type=entity_type,
            description=description or default_description,
            traits=traits,
            voice=voice,
            constraints=constraints,
            metadata=metadata,
            token_priority=token_priority,
        )

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
        return cls._create_entity(
            name=name,
            entity_type=EntityType.CONTENT,
            description=description,
            default_description="Content generation role",
            traits=traits,
            voice=voice,
            constraints=constraints,
            token_priority=token_priority,
            type_specific_metadata={"style": style, "perspective": perspective, "tone": tone},
            extra=extra,
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
        return cls._create_entity(
            name=name,
            entity_type=EntityType.ANALYSIS,
            description=description,
            default_description="Analysis role",
            traits=traits,
            voice=voice,
            constraints=constraints,
            token_priority=token_priority,
            type_specific_metadata={"methodology": methodology, "depth": depth, "focus_areas": focus_areas},
            extra=extra,
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
        return cls._create_entity(
            name=name,
            entity_type=EntityType.TECHNICAL,
            description=description,
            default_description="Technical role",
            traits=traits,
            voice=voice,
            constraints=constraints,
            token_priority=token_priority,
            type_specific_metadata={
                "domain": domain,
                "audience_level": audience_level,
                "include_code_examples": include_code_examples,
                "include_diagrams": include_diagrams,
            },
            extra=extra,
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
        return cls._create_entity(
            name=name,
            entity_type=EntityType.COMPARATIVE,
            description=description,
            default_description="Comparative role",
            traits=traits,
            voice=voice,
            constraints=constraints,
            token_priority=token_priority,
            type_specific_metadata={
                "dimensions": dimensions,
                "format": format,
                "bias_awareness": bias_awareness,
            },
            extra=extra,
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
        return cls._create_entity(
            name=name,
            entity_type=EntityType.EDUCATIONAL,
            description=description,
            default_description="Educational role",
            traits=traits,
            voice=voice,
            constraints=constraints,
            token_priority=token_priority,
            type_specific_metadata={
                "teaching_style": teaching_style,
                "knowledge_level": knowledge_level,
                "include_examples": include_examples,
                "include_exercises": include_exercises,
            },
            extra=extra,
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
        return cls._create_entity(
            name=name,
            entity_type=EntityType.VALIDATION,
            description=description,
            default_description="Validation role",
            traits=traits,
            voice=voice,
            constraints=constraints,
            token_priority=token_priority,
            type_specific_metadata={
                "validation_type": validation_type,
                "rules": rules,
                "severity_levels": severity_levels,
                "auto_fix": auto_fix,
            },
            extra=extra,
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

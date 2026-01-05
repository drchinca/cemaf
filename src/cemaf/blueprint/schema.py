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
        token_priority: int = 5,
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
        token_priority: int = 5,
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
        token_priority: int = 5,
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
        token_priority: int = 5,
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

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Blueprint:
        """Create blueprint from dictionary."""
        return cls.model_validate(data)

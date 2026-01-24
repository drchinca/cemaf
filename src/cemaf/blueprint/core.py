"""
Core blueprint models for semantic prompt engineering.

Based on Denis Rothman's Semantic Blueprint concept.
A blueprint defines HOW to accomplish a task, separate from WHAT data to use.
"""

from typing import Any

from pydantic import BaseModel, Field

from cemaf.blueprint.entities import ContextEntity
from cemaf.blueprint.policies import ExecutionPolicy, OutputContract, SecurityPolicy
from cemaf.core.types import JSON


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

    def get_context_priorities(self) -> dict[str, int]:
        """Get context entity priorities for token budget allocation.

        Returns dict mapping entity names to their token_priority values.
        If no entities defined, returns default priorities based on scene_goal.priority.
        """
        if self.entities:
            return {entity.name: entity.token_priority for entity in self.entities}

        # Default priorities when no entities defined
        return {
            "artifacts": self.scene_goal.priority,
            "memories": max(1, self.scene_goal.priority - 1),
        }

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Blueprint:
        """Create blueprint from dictionary."""
        return cls.model_validate(data)

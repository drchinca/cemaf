"""
cemaf.blueprint.schema - Semantic blueprint models for content generation.

Based on Denis Rothman's Semantic Blueprint concept for structured context engineering.
A blueprint defines HOW to accomplish a task, separate from WHAT data to use.
"""

from pydantic import BaseModel, Field

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
    participants: tuple[Participant, ...] = ()
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

        # Participants section (if any)
        if self.participants:
            sections.append(self._format_participants_section())

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

    def _format_participants_section(self) -> str:
        """Format the participants section of the prompt."""
        lines = ["## Participants"]

        for participant in self.participants:
            lines.append(f"### {participant.name}")
            lines.append(f"Role: {participant.role}")

            if participant.traits:
                lines.append(f"Traits: {', '.join(participant.traits)}")

            if participant.voice:
                lines.append(f"Voice: {participant.voice}")

            if participant.constraints:
                lines.append("Constraints:")
                for constraint in participant.constraints:
                    lines.append(f"  - {constraint}")

        return "\n".join(lines)

    def _format_instructions_section(self) -> str:
        """Format the instructions section of the prompt."""
        return f"## Instructions\n{self.instruction}"

    def to_dict(self) -> dict:
        """Convert to dictionary representation."""
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: dict) -> Blueprint:
        """Create blueprint from dictionary."""
        return cls.model_validate(data)

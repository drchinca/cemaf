"""
Fluent builder for creating Blueprint instances.

Provides a chainable API for constructing blueprints step by step
with validation on build.
"""

from typing import Self

from cemaf.blueprint.schema import Blueprint, Participant, SceneGoal, StyleGuide


class BlueprintBuilder:
    """
    Fluent builder for creating Blueprint instances.

    Example:
        blueprint = (
            BlueprintBuilder("bp-1", "Marketing Email")
            .with_goal("Generate compelling email copy")
            .with_style(tone="professional", format="html")
            .add_participant("writer", "Email Copywriter", traits=["persuasive", "concise"])
            .with_instruction("Write a 3-paragraph email promoting the product")
            .with_tags("marketing", "email")
            .build()
        )
    """

    def __init__(self, id: str, name: str) -> None:
        """
        Initialize the builder with required id and name.

        Args:
            id: Unique identifier for the blueprint.
            name: Human-readable name for the blueprint.
        """
        self._id = id
        self._name = name
        self._description = ""
        self._goal_objective: str | None = None
        self._goal_success_criteria: list[str] = []
        self._goal_constraints: list[str] = []
        self._goal_priority: int = 1
        self._style: dict[str, str | list[str]] = {}
        self._participants: list[Participant] = []
        self._instruction = ""
        self._version = "1.0"
        self._tags: list[str] = []
        self._metadata: dict[str, object] = {}

    def with_description(self, description: str) -> Self:
        """
        Set blueprint description.

        Args:
            description: Detailed description of the blueprint.

        Returns:
            Self for method chaining.
        """
        self._description = description
        return self

    def with_goal(
        self,
        objective: str,
        success_criteria: list[str] | None = None,
        constraints: list[str] | None = None,
        priority: int = 1,
    ) -> Self:
        """
        Set the scene goal.

        Args:
            objective: The main objective to achieve.
            success_criteria: List of criteria that define success.
            constraints: Limitations or rules to follow.
            priority: Priority level (1 = highest).

        Returns:
            Self for method chaining.
        """
        self._goal_objective = objective
        if success_criteria:
            self._goal_success_criteria = list(success_criteria)
        if constraints:
            self._goal_constraints = list(constraints)
        self._goal_priority = priority
        return self

    def with_style(
        self,
        tone: str = "",
        format: str = "",
        length_hint: str = "",
        vocabulary: list[str] | None = None,
        avoid: list[str] | None = None,
        examples: list[str] | None = None,
    ) -> Self:
        """
        Set style guide.

        Args:
            tone: The tone of voice (e.g., "professional", "casual").
            format: Output format (e.g., "html", "markdown", "plain").
            length_hint: Suggested length (e.g., "short", "500 words").
            vocabulary: Preferred words or phrases to use.
            avoid: Words or phrases to avoid.
            examples: Example outputs for reference.

        Returns:
            Self for method chaining.
        """
        if tone:
            self._style["tone"] = tone
        if format:
            self._style["format"] = format
        if length_hint:
            self._style["length_hint"] = length_hint
        if vocabulary:
            self._style["vocabulary"] = list(vocabulary)
        if avoid:
            self._style["avoid"] = list(avoid)
        if examples:
            self._style["examples"] = list(examples)
        return self

    def add_participant(
        self,
        name: str,
        role: str,
        traits: list[str] | None = None,
        voice: str = "",
        constraints: list[str] | None = None,
    ) -> Self:
        """
        Add a participant to the blueprint.

        Args:
            name: Unique identifier for the participant.
            role: The role this participant plays.
            traits: Personality traits or characteristics.
            voice: Voice/style description.
            constraints: Limitations for this participant.

        Returns:
            Self for method chaining.
        """
        participant = Participant(
            name=name,
            role=role,
            traits=tuple(traits) if traits else (),
            voice=voice,
            constraints=tuple(constraints) if constraints else (),
        )
        self._participants.append(participant)
        return self

    def with_instruction(self, instruction: str) -> Self:
        """
        Set the instruction text.

        Args:
            instruction: The main instruction/prompt for the scene.

        Returns:
            Self for method chaining.
        """
        self._instruction = instruction
        return self

    def with_version(self, version: str) -> Self:
        """
        Set version.

        Args:
            version: Version string for the blueprint.

        Returns:
            Self for method chaining.
        """
        self._version = version
        return self

    def with_tags(self, *tags: str) -> Self:
        """
        Add tags.

        Args:
            *tags: Tags for categorization.

        Returns:
            Self for method chaining.
        """
        self._tags.extend(tags)
        return self

    def with_metadata(self, **kwargs: object) -> Self:
        """
        Add metadata.

        Args:
            **kwargs: Key-value metadata pairs.

        Returns:
            Self for method chaining.
        """
        self._metadata.update(kwargs)
        return self

    def build(self) -> Blueprint:
        """
        Build the Blueprint instance.

        Returns:
            The constructed Blueprint.

        Raises:
            ValueError: If required fields (id, name, goal objective) are missing.
        """
        if not self._id:
            raise ValueError("Blueprint requires an id.")
        if not self._name:
            raise ValueError("Blueprint requires a name.")
        if not self._goal_objective:
            raise ValueError("Blueprint requires a goal objective. Call with_goal() first.")

        scene_goal = SceneGoal(
            objective=self._goal_objective,
            success_criteria=tuple(self._goal_success_criteria),
            constraints=tuple(self._goal_constraints),
            priority=self._goal_priority,
        )

        # Extract style values, handling both str and list types
        vocabulary = self._style.get("vocabulary", [])
        avoid = self._style.get("avoid", [])
        examples = self._style.get("examples", [])

        style_guide = StyleGuide(
            tone=str(self._style.get("tone", "")),
            format=str(self._style.get("format", "")),
            length_hint=str(self._style.get("length_hint", "")),
            vocabulary=tuple(vocabulary) if isinstance(vocabulary, list) else (),
            avoid=tuple(avoid) if isinstance(avoid, list) else (),
            examples=tuple(examples) if isinstance(examples, list) else (),
        )

        return Blueprint(
            id=self._id,
            name=self._name,
            description=self._description,
            scene_goal=scene_goal,
            style_guide=style_guide,
            participants=tuple(self._participants),
            instruction=self._instruction,
            version=self._version,
            tags=tuple(self._tags),
            metadata=dict(self._metadata),
        )

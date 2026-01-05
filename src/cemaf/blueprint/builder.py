"""
Fluent builder for creating Blueprint instances.

Provides a chainable API for constructing blueprints step by step
with validation on build.
"""

from typing import Self

from cemaf.blueprint.contracts import DataContract
from cemaf.blueprint.core import Blueprint, SceneGoal, StyleGuide
from cemaf.blueprint.entities import (
    ContextEntity,
)
from cemaf.blueprint.policies import (
    ExecutionPolicy,
    OutputContract,
    OutputFormat,
    RequiredSections,
    SecurityPolicy,
)


class BlueprintBuilder:
    """
    Fluent builder for creating Blueprint instances.

    Example:
        blueprint = (
            BlueprintBuilder("bp-1", "Marketing Email")
            .with_goal("Generate compelling email copy")
            .with_style(tone="professional", format="html")
            .add_content_entity("writer", style="marketing", tone="persuasive")
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
        self._entities: list[ContextEntity] = []
        self._instruction = ""
        self._version = "1.0"
        self._tags: list[str] = []
        self._metadata: dict[str, object] = {}
        self._output_contract: OutputContract | None = None
        self._execution_policy: ExecutionPolicy | None = None
        self._security_policy: SecurityPolicy | None = None

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

    def add_entity(
        self,
        entity: ContextEntity,
        data_contract: DataContract | None = None,
    ) -> Self:
        """
        Add an entity to the blueprint with optional data contract.

        Args:
            entity: The ContextEntity instance to add.
            data_contract: Optional data contract specification.

        Returns:
            Self for method chaining.

        Example:
            >>> builder.add_entity(
            ...     ContextEntity.content(name="writer", style="narrative"),
            ...     data_contract=DataContract(schema_type="table", fields=("id", "text"))
            ... )
        """
        if data_contract:
            entity = entity.model_copy(update={"data_contract": data_contract})

        self._entities.append(entity)
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

    def with_output_contract(
        self,
        format: OutputFormat = "yaml",
        required_sections: RequiredSections = (),
        must_include: tuple[str, ...] = (),
        forbidden: tuple[str, ...] = (),
        schema_definition: str = "",
        **metadata: object,
    ) -> Self:
        """
        Set output contract.

        Args:
            format: Output format (json, yaml, markdown, python, sql).
            required_sections: Sections that must be present.
            must_include: Specific requirements that must appear.
            forbidden: What to avoid.
            schema_definition: Optional schema (JSON Schema, etc.).
            **metadata: Additional metadata.

        Returns:
            Self for method chaining.
        """
        self._output_contract = OutputContract(
            format=format,
            required_sections=required_sections,
            must_include=must_include,
            forbidden=forbidden,
            schema_definition=schema_definition,
            metadata=dict(metadata),
        )
        return self

    def with_execution_policy(
        self,
        incremental_strategy: str = "full",
        incremental_field: str = "",
        checkpoint_location: str = "",
        idempotency_key: str = "run_id",
        max_retries: int = 3,
        retry_on: tuple[str, ...] = ("rate_limit", "transient_network"),
        fail_on: tuple[str, ...] = ("data_quality_fail", "schema_mismatch"),
        exactly_once: bool = False,
        **metadata: object,
    ) -> Self:
        """
        Set execution policy.

        Args:
            incremental_strategy: Strategy for incremental processing.
            incremental_field: Field for watermarking.
            checkpoint_location: Where to store checkpoints.
            idempotency_key: Field for idempotent operations.
            max_retries: Maximum retry attempts.
            retry_on: Conditions to retry on.
            fail_on: Conditions to fail immediately on.
            exactly_once: Use exactly-once semantics.
            **metadata: Additional metadata.

        Returns:
            Self for method chaining.
        """
        self._execution_policy = ExecutionPolicy(
            incremental_strategy=incremental_strategy,  # type: ignore
            incremental_field=incremental_field,
            checkpoint_location=checkpoint_location,
            idempotency_key=idempotency_key,
            max_retries=max_retries,
            retry_on=retry_on,
            fail_on=fail_on,
            exactly_once=exactly_once,
            metadata=dict(metadata),
        )
        return self

    def with_security_policy(
        self,
        pii_fields: tuple[str, ...] = (),
        encryption: str = "none",
        secret_rotation: bool = False,
        secret_provider: str = "none",
        secret_rotation_days: int = 90,
        compliance_frameworks: tuple[str, ...] = (),
        **metadata: object,
    ) -> Self:
        """
        Set security policy.

        Args:
            pii_fields: List of PII field names.
            encryption: Encryption requirements.
            secret_rotation: Enable secret rotation.
            secret_provider: Secret management provider.
            secret_rotation_days: Days between rotations.
            compliance_frameworks: Compliance requirements.
            **metadata: Additional metadata.

        Returns:
            Self for method chaining.
        """
        self._security_policy = SecurityPolicy(
            pii_fields=pii_fields,
            encryption=encryption,  # type: ignore
            secret_rotation=secret_rotation,
            secret_provider=secret_provider,  # type: ignore
            secret_rotation_days=secret_rotation_days,
            compliance_frameworks=compliance_frameworks,
            metadata=dict(metadata),
        )
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
            entities=tuple(self._entities),
            instruction=self._instruction,
            version=self._version,
            tags=tuple(self._tags),
            metadata=dict(self._metadata),
            output_contract=self._output_contract,
            execution_policy=self._execution_policy,
            security_policy=self._security_policy,
        )

"""
Blueprint validation rules.

Provides validation rules for Blueprint schemas and content quality.
"""

from typing import Any

from cemaf.blueprint.schema import Blueprint, Participant, SceneGoal
from cemaf.core.types import JSON
from cemaf.validation.protocols import (
    ValidationError,
    ValidationResult,
    ValidationWarning,
)


class BlueprintSchemaRule:
    """
    Validate that data conforms to Blueprint schema.

    Implements the Rule protocol from validation module.
    """

    def __init__(
        self,
        strict: bool = False,  # If True, require all optional fields too
        name: str = "blueprint_schema",
    ) -> None:
        self._strict = strict
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    async def check(self, data: Any, context: JSON | None = None) -> ValidationResult:
        """
        Validate data against Blueprint schema.

        Args:
            data: Dict or Blueprint to validate.
            context: Optional validation context.

        Returns:
            ValidationResult with errors if validation fails.
        """
        # If already a Blueprint, it's valid
        if isinstance(data, Blueprint):
            return ValidationResult.success()

        # Try to parse as dict
        if not isinstance(data, dict):
            return ValidationResult.error(
                code="INVALID_TYPE",
                message=f"Expected dict or Blueprint, got {type(data).__name__}",
            )

        # Check required fields
        errors: list[ValidationError] = []

        if "id" not in data:
            errors.append(
                ValidationError(
                    code="MISSING_ID",
                    message="Blueprint requires 'id' field",
                    field="id",
                    suggestion="Add an 'id' field with a unique identifier",
                )
            )

        if "name" not in data:
            errors.append(
                ValidationError(
                    code="MISSING_NAME",
                    message="Blueprint requires 'name' field",
                    field="name",
                    suggestion="Add a 'name' field with a human-readable name",
                )
            )

        if "scene_goal" not in data:
            errors.append(
                ValidationError(
                    code="MISSING_GOAL",
                    message="Blueprint requires 'scene_goal' field",
                    field="scene_goal",
                    suggestion="Add a 'scene_goal' field with objective and constraints",
                )
            )
        elif isinstance(data.get("scene_goal"), dict) and "objective" not in data["scene_goal"]:
            errors.append(
                ValidationError(
                    code="MISSING_OBJECTIVE",
                    message="scene_goal requires 'objective' field",
                    field="scene_goal.objective",
                    suggestion="Add an 'objective' field to scene_goal",
                )
            )

        if errors:
            return ValidationResult.failure(
                errors=tuple(errors),
                suggestions=tuple(e.suggestion for e in errors if e.suggestion),
            )

        # Try to actually parse using Pydantic's model_validate
        try:
            Blueprint.model_validate(data)
            return ValidationResult.success()
        except Exception as e:
            return ValidationResult.error(
                code="PARSE_ERROR",
                message=str(e),
                suggestion="Check that all field values have the correct types",
            )


class BlueprintContentRule:
    """
    Validate blueprint content quality.

    Checks for:
    - Non-empty objective
    - Reasonable instruction length
    - Valid participant roles
    """

    def __init__(
        self,
        min_objective_length: int = 10,
        max_instruction_length: int = 10000,
        name: str = "blueprint_content",
    ) -> None:
        self._min_objective_length = min_objective_length
        self._max_instruction_length = max_instruction_length
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    async def check(self, data: Any, context: JSON | None = None) -> ValidationResult:
        """
        Validate blueprint content quality.

        Args:
            data: Blueprint or dict to validate.
            context: Optional validation context.

        Returns:
            ValidationResult with errors/warnings if validation fails.
        """
        errors: list[ValidationError] = []
        warnings: list[ValidationWarning] = []

        # Extract fields based on data type
        if isinstance(data, Blueprint):
            objective = data.scene_goal.objective
            instruction = data.instruction
            participants = data.participants
            description = data.description
        elif isinstance(data, dict):
            scene_goal = data.get("scene_goal", {})
            if isinstance(scene_goal, SceneGoal):
                objective = scene_goal.objective
            else:
                objective = scene_goal.get("objective", "") if isinstance(scene_goal, dict) else ""
            instruction = data.get("instruction", "")
            participants = data.get("participants", ())
            description = data.get("description", "")
        else:
            return ValidationResult.error(
                code="INVALID_TYPE",
                message=f"Expected dict or Blueprint, got {type(data).__name__}",
            )

        # Check objective length
        if len(objective) < self._min_objective_length:
            errors.append(
                ValidationError(
                    code="OBJECTIVE_TOO_SHORT",
                    message=(
                        f"Objective must be at least {self._min_objective_length} characters, "
                        f"got {len(objective)}"
                    ),
                    field="scene_goal.objective",
                    value=objective,
                    suggestion=(
                        f"Provide a more detailed objective "
                        f"(at least {self._min_objective_length} characters)"
                    ),
                )
            )

        # Check instruction length
        if len(instruction) > self._max_instruction_length:
            errors.append(
                ValidationError(
                    code="INSTRUCTION_TOO_LONG",
                    message=(
                        f"Instruction exceeds maximum length of {self._max_instruction_length} characters"
                    ),
                    field="instruction",
                    value=len(instruction),
                    suggestion=(f"Reduce instruction to at most {self._max_instruction_length} characters"),
                )
            )

        # Check participant roles
        seen_names: set[str] = set()
        for i, participant in enumerate(participants):
            if isinstance(participant, Participant):
                p_name = participant.name
                p_role = participant.role
            elif isinstance(participant, dict):
                p_name = participant.get("name", "")
                p_role = participant.get("role", "")
            else:
                continue

            # Check for duplicate names
            if p_name in seen_names:
                errors.append(
                    ValidationError(
                        code="DUPLICATE_PARTICIPANT",
                        message=f"Duplicate participant name: '{p_name}'",
                        field=f"participants[{i}].name",
                        value=p_name,
                        suggestion="Use unique names for each participant",
                    )
                )
            seen_names.add(p_name)

            # Check for empty role
            if not p_role:
                warnings.append(
                    ValidationWarning(
                        code="EMPTY_ROLE",
                        message=f"Participant '{p_name}' has no role defined",
                        field=f"participants[{i}].role",
                        suggestion="Consider adding a role to clarify the participant's purpose",
                    )
                )

        # Warn if no description
        if not description:
            warnings.append(
                ValidationWarning(
                    code="NO_DESCRIPTION",
                    message="Blueprint has no description",
                    field="description",
                    suggestion="Consider adding a description to document the blueprint's purpose",
                )
            )

        if errors:
            return ValidationResult.failure(
                errors=tuple(errors),
                warnings=tuple(warnings),
                suggestions=tuple(e.suggestion for e in errors if e.suggestion),
            )

        return ValidationResult.success(warnings=tuple(warnings))

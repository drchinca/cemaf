"""Blueprint schema validation and repair loop (SPEC-03 §2 "Schema validation
and repair primitive").

Standalone ahead of `StructuredGenerator`: validates a raw LLM output against
a Pydantic schema and, on failure, produces re-prompt guidance a future
generator's retry can fold into its next request.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from pydantic import BaseModel, ValidationError

from cemaf.core.types import JSON

_ERROR_TYPE_GUIDANCE: dict[str, str] = {
    "missing": "Add the missing field with a value of the expected type.",
    "extra_forbidden": "Remove this field — it is not part of the schema.",
    "string_type": "Provide a string value for this field.",
    "int_type": "Provide an integer value for this field.",
    "int_parsing": "Provide a value that parses as an integer for this field.",
    "float_type": "Provide a numeric value for this field.",
    "bool_type": "Provide a boolean (true/false) value for this field.",
    "list_type": "Provide a list/array value for this field.",
    "dict_type": "Provide an object value for this field.",
    "enum": "Use one of the schema's allowed values for this field.",
    "literal_error": "Use one of the schema's allowed literal values for this field.",
    "string_too_short": "Provide a longer value for this field.",
    "string_too_long": "Provide a shorter value for this field.",
    "greater_than_equal": "Provide a value that meets the field's minimum.",
    "less_than_equal": "Provide a value that meets the field's maximum.",
    "value_error": "Correct the value so it satisfies the field's validation rule.",
}

_DEFAULT_GUIDANCE = "Correct this field so it satisfies the schema."


def _guidance_for(*, error_type: str, message: str) -> str:
    return _ERROR_TYPE_GUIDANCE.get(error_type, f"{_DEFAULT_GUIDANCE} ({message})")


def _field_path(loc: tuple[object, ...]) -> str:
    return ".".join(str(segment) for segment in loc)


@dataclass(frozen=True, slots=True)
class FieldRepairNote:
    """One pydantic validation error translated into re-prompt guidance."""

    field_path: str
    error_type: str
    message: str
    guidance: str


@dataclass(frozen=True, slots=True)
class SchemaRepairHint:
    """Every validation failure for one attempt, ready to fold into a re-prompt."""

    schema_name: str
    notes: tuple[FieldRepairNote, ...]

    def to_prompt(self) -> str:
        """Render as a numbered list of corrections for the next generation attempt."""
        lines = [f"The previous output did not match the {self.schema_name} schema:"]
        for index, note in enumerate(self.notes, start=1):
            lines.append(f"{index}. `{note.field_path}` — {note.message}. {note.guidance}")
        return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class ValidationOutcome[T: BaseModel]:
    """Result of one or more schema-validation attempts."""

    valid: bool
    output: T | None
    repair_hint: SchemaRepairHint | None
    attempts: int


def validate_structured_output[T: BaseModel](
    *, output_schema: type[T], raw_output: JSON
) -> ValidationOutcome[T]:
    """Validate `raw_output` against `output_schema`; build a `SchemaRepairHint` on failure."""
    try:
        instance = output_schema.model_validate(raw_output)
    except ValidationError as exc:
        notes = tuple(
            FieldRepairNote(
                field_path=_field_path(error["loc"]),
                error_type=error["type"],
                message=error["msg"],
                guidance=_guidance_for(error_type=error["type"], message=error["msg"]),
            )
            for error in exc.errors()
        )
        hint = SchemaRepairHint(schema_name=output_schema.__name__, notes=notes)
        return ValidationOutcome(valid=False, output=None, repair_hint=hint, attempts=1)
    return ValidationOutcome(valid=True, output=instance, repair_hint=None, attempts=1)


async def repair_and_validate[T: BaseModel](
    *,
    output_schema: type[T],
    raw_output: JSON,
    max_attempts: int,
    regenerate: Callable[[SchemaRepairHint], Awaitable[JSON]],
) -> ValidationOutcome[T]:
    """Validate; on failure, call `regenerate(repair_hint)` for a corrected raw
    output and re-validate, up to `max_attempts` total validation attempts."""
    outcome = validate_structured_output(output_schema=output_schema, raw_output=raw_output)
    attempts = outcome.attempts
    while not outcome.valid and attempts < max_attempts:
        assert outcome.repair_hint is not None
        raw_output = await regenerate(outcome.repair_hint)
        outcome = validate_structured_output(output_schema=output_schema, raw_output=raw_output)
        attempts += 1
        outcome = ValidationOutcome(
            valid=outcome.valid, output=outcome.output, repair_hint=outcome.repair_hint, attempts=attempts
        )
    return outcome

"""
Built-in validation rules.

Provides common validation rules for strings, numbers,
schemas, and custom logic.
"""

import re
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from pydantic import BaseModel

from cemaf.core.types import JSON
from cemaf.validation.protocols import (
    ValidationError,
    ValidationResult,
)


class SchemaRule:
    """
    Validate data against a Pydantic model schema.
    """

    def __init__(
        self,
        schema: type[BaseModel],
        name: str | None = None,
    ) -> None:
        """
        Initialize schema rule.

        Args:
            schema: Pydantic model to validate against.
            name: Rule name (defaults to schema class name).
        """
        self._schema = schema
        self._name = name or f"schema:{schema.__name__}"

    @property
    def name(self) -> str:
        return self._name

    async def check(self, data: Any, context: JSON | None = None) -> ValidationResult:
        """Validate data against the schema."""
        try:
            self._schema.model_validate(data)
            return ValidationResult.success()
        except Exception as e:
            return ValidationResult.error(
                code="SCHEMA_INVALID",
                message=str(e),
                suggestion=f"Ensure data matches {self._schema.__name__} schema",
            )


class LengthRule:
    """
    Validate string or collection length.
    """

    def __init__(
        self,
        min_length: int | None = None,
        max_length: int | None = None,
        field: str | None = None,
        name: str = "length",
    ) -> None:
        """
        Initialize length rule.

        Args:
            min_length: Minimum length (inclusive).
            max_length: Maximum length (inclusive).
            field: Field name for error messages.
            name: Rule name.
        """
        self._min_length = min_length
        self._max_length = max_length
        self._field = field
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    async def check(self, data: Any, context: JSON | None = None) -> ValidationResult:
        """Check length constraints."""
        try:
            length = len(data)
        except TypeError:
            return ValidationResult.error(
                code="LENGTH_NOT_SUPPORTED",
                message=f"Cannot determine length of {type(data).__name__}",
                field=self._field,
            )

        errors: list[ValidationError] = []

        if self._min_length is not None and length < self._min_length:
            errors.append(
                ValidationError(
                    code="LENGTH_TOO_SHORT",
                    message=f"Length {length} is less than minimum {self._min_length}",
                    field=self._field,
                    value=length,
                    suggestion=f"Ensure length is at least {self._min_length}",
                )
            )

        if self._max_length is not None and length > self._max_length:
            errors.append(
                ValidationError(
                    code="LENGTH_TOO_LONG",
                    message=f"Length {length} exceeds maximum {self._max_length}",
                    field=self._field,
                    value=length,
                    suggestion=f"Reduce length to at most {self._max_length}",
                )
            )

        if errors:
            return ValidationResult.failure(errors=tuple(errors))
        return ValidationResult.success()


class RegexRule:
    """
    Validate string against a regular expression.
    """

    def __init__(
        self,
        pattern: str,
        field: str | None = None,
        message: str | None = None,
        name: str = "regex",
    ) -> None:
        """
        Initialize regex rule.

        Args:
            pattern: Regular expression pattern.
            field: Field name for error messages.
            message: Custom error message.
            name: Rule name.
        """
        self._pattern = re.compile(pattern)
        self._pattern_str = pattern
        self._field = field
        self._message = message
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    async def check(self, data: Any, context: JSON | None = None) -> ValidationResult:
        """Check if data matches the pattern."""
        if not isinstance(data, str):
            return ValidationResult.error(
                code="REGEX_TYPE_ERROR",
                message=f"Expected string, got {type(data).__name__}",
                field=self._field,
            )

        if not self._pattern.match(data):
            return ValidationResult.error(
                code="REGEX_NO_MATCH",
                message=self._message or f"Value does not match pattern '{self._pattern_str}'",
                field=self._field,
                suggestion=f"Ensure value matches pattern: {self._pattern_str}",
            )

        return ValidationResult.success()


class RangeRule:
    """
    Validate numeric value is within range.
    """

    def __init__(
        self,
        min_value: float | None = None,
        max_value: float | None = None,
        field: str | None = None,
        name: str = "range",
    ) -> None:
        """
        Initialize range rule.

        Args:
            min_value: Minimum value (inclusive).
            max_value: Maximum value (inclusive).
            field: Field name for error messages.
            name: Rule name.
        """
        self._min_value = min_value
        self._max_value = max_value
        self._field = field
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    async def check(self, data: Any, context: JSON | None = None) -> ValidationResult:
        """Check if value is within range."""
        if not isinstance(data, (int, float)):
            return ValidationResult.error(
                code="RANGE_TYPE_ERROR",
                message=f"Expected number, got {type(data).__name__}",
                field=self._field,
            )

        errors: list[ValidationError] = []

        if self._min_value is not None and data < self._min_value:
            errors.append(
                ValidationError(
                    code="RANGE_TOO_LOW",
                    message=f"Value {data} is less than minimum {self._min_value}",
                    field=self._field,
                    value=data,
                    suggestion=f"Ensure value is at least {self._min_value}",
                )
            )

        if self._max_value is not None and data > self._max_value:
            errors.append(
                ValidationError(
                    code="RANGE_TOO_HIGH",
                    message=f"Value {data} exceeds maximum {self._max_value}",
                    field=self._field,
                    value=data,
                    suggestion=f"Reduce value to at most {self._max_value}",
                )
            )

        if errors:
            return ValidationResult.failure(errors=tuple(errors))
        return ValidationResult.success()


class RequiredFieldsRule:
    """
    Validate that required fields are present in a dictionary.
    """

    def __init__(
        self,
        fields: Sequence[str],
        name: str = "required_fields",
    ) -> None:
        """
        Initialize required fields rule.

        Args:
            fields: List of required field names.
            name: Rule name.
        """
        self._fields = tuple(fields)
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    async def check(self, data: Any, context: JSON | None = None) -> ValidationResult:
        """Check that all required fields are present."""
        if not isinstance(data, dict):
            return ValidationResult.error(
                code="REQUIRED_FIELDS_TYPE_ERROR",
                message=f"Expected dict, got {type(data).__name__}",
            )

        missing = [f for f in self._fields if f not in data]

        if missing:
            return ValidationResult.failure(
                errors=tuple(
                    ValidationError(
                        code="REQUIRED_FIELD_MISSING",
                        message=f"Required field '{field}' is missing",
                        field=field,
                        suggestion=f"Add the '{field}' field to the data",
                    )
                    for field in missing
                ),
                suggestions=tuple(f"Add missing field: {f}" for f in missing),
            )

        return ValidationResult.success()


class CustomRule:
    """
    Validate using a custom function.
    """

    def __init__(
        self,
        check_fn: Callable[[Any, JSON | None], Awaitable[ValidationResult]],
        name: str = "custom",
    ) -> None:
        """
        Initialize custom rule.

        Args:
            check_fn: Async function that performs validation.
            name: Rule name.
        """
        self._check_fn = check_fn
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    async def check(self, data: Any, context: JSON | None = None) -> ValidationResult:
        """Run custom validation function."""
        return await self._check_fn(data, context)

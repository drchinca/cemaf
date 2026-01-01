"""
Validation protocols and base types.

Defines the contracts for validators, rules, and validation results.
"""

from enum import Enum
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from cemaf.core.types import JSON


class ValidationSeverity(str, Enum):
    """Severity level for validation issues."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class ValidationError(BaseModel):
    """A validation error."""

    model_config = {"frozen": True}

    code: str
    message: str
    field: str | None = None
    value: Any = None
    suggestion: str | None = None


class ValidationWarning(BaseModel):
    """A validation warning (non-blocking)."""

    model_config = {"frozen": True}

    code: str
    message: str
    field: str | None = None
    suggestion: str | None = None


class ValidationResult(BaseModel):
    """
    Result of a validation operation.

    Contains errors (blocking), warnings (non-blocking),
    and suggestions for repair.
    """

    model_config = {"frozen": True}

    passed: bool
    errors: tuple[ValidationError, ...] = ()
    warnings: tuple[ValidationWarning, ...] = ()
    suggestions: tuple[str, ...] = ()
    metadata: JSON = Field(default_factory=dict)

    @classmethod
    def success(cls, warnings: tuple[ValidationWarning, ...] = ()) -> ValidationResult:
        """Create a successful validation result."""
        return cls(passed=True, warnings=warnings)

    @classmethod
    def failure(
        cls,
        errors: tuple[ValidationError, ...],
        warnings: tuple[ValidationWarning, ...] = (),
        suggestions: tuple[str, ...] = (),
    ) -> ValidationResult:
        """Create a failed validation result."""
        return cls(
            passed=False,
            errors=errors,
            warnings=warnings,
            suggestions=suggestions,
        )

    @classmethod
    def error(
        cls,
        code: str,
        message: str,
        field: str | None = None,
        suggestion: str | None = None,
    ) -> ValidationResult:
        """Create a failed result with a single error."""
        return cls.failure(
            errors=(
                ValidationError(
                    code=code,
                    message=message,
                    field=field,
                    suggestion=suggestion,
                ),
            ),
            suggestions=(suggestion,) if suggestion else (),
        )

    def merge(self, other: ValidationResult) -> ValidationResult:
        """Merge two validation results."""
        return ValidationResult(
            passed=self.passed and other.passed,
            errors=self.errors + other.errors,
            warnings=self.warnings + other.warnings,
            suggestions=self.suggestions + other.suggestions,
            metadata={**self.metadata, **other.metadata},
        )


@runtime_checkable
class Rule(Protocol):
    """
    Protocol for validation rules.

    A Rule checks a single aspect of data validity.
    """

    @property
    def name(self) -> str:
        """Unique identifier for this rule."""
        ...

    async def check(self, data: Any, context: JSON | None = None) -> ValidationResult:
        """
        Check data against this rule.

        Args:
            data: The data to validate.
            context: Optional context for validation (e.g., user info).

        Returns:
            ValidationResult indicating pass/fail with details.
        """
        ...


@runtime_checkable
class Validator(Protocol):
    """
    Protocol for validators.

    A Validator can validate data using one or more rules.
    """

    async def validate(self, data: Any, context: JSON | None = None) -> ValidationResult:
        """
        Validate data.

        Args:
            data: The data to validate.
            context: Optional context for validation.

        Returns:
            ValidationResult with all errors and warnings.
        """
        ...

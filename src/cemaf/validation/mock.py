"""
Mock implementations for testing validation.
"""

from typing import Any

from cemaf.core.types import JSON
from cemaf.validation.protocols import (
    ValidationResult,
)


class MockValidator:
    """
    Mock validator for testing.

    Can be configured to pass, fail, or record calls.
    """

    def __init__(
        self,
        should_pass: bool = True,
        error_code: str = "MOCK_ERROR",
        error_message: str = "Mock validation failed",
    ) -> None:
        """
        Initialize mock validator.

        Args:
            should_pass: Whether validation should pass.
            error_code: Error code to use on failure.
            error_message: Error message to use on failure.
        """
        self._should_pass = should_pass
        self._error_code = error_code
        self._error_message = error_message
        self._calls: list[tuple[Any, JSON | None]] = []

    @property
    def calls(self) -> list[tuple[Any, JSON | None]]:
        """Get recorded validation calls."""
        return list(self._calls)

    @property
    def call_count(self) -> int:
        """Get number of validation calls."""
        return len(self._calls)

    def set_pass(self, should_pass: bool) -> None:
        """Set whether validation should pass."""
        self._should_pass = should_pass

    async def validate(
        self,
        data: Any,
        context: JSON | None = None,
    ) -> ValidationResult:
        """Record call and return configured result."""
        self._calls.append((data, context))

        if self._should_pass:
            return ValidationResult.success()

        return ValidationResult.error(
            code=self._error_code,
            message=self._error_message,
        )

    def reset(self) -> None:
        """Reset recorded calls."""
        self._calls.clear()


class AlwaysPassRule:
    """Rule that always passes."""

    def __init__(self, name: str = "always_pass") -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    async def check(self, data: Any, context: JSON | None = None) -> ValidationResult:
        return ValidationResult.success()


class AlwaysFailRule:
    """Rule that always fails."""

    def __init__(
        self,
        error_code: str = "ALWAYS_FAIL",
        error_message: str = "This rule always fails",
        name: str = "always_fail",
    ) -> None:
        self._error_code = error_code
        self._error_message = error_message
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    async def check(self, data: Any, context: JSON | None = None) -> ValidationResult:
        return ValidationResult.error(
            code=self._error_code,
            message=self._error_message,
        )

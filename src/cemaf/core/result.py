"""
Generic Result type for consistent success/failure handling.

This eliminates the need for separate Result classes in each module.
All modules should use Result[T] instead of custom result types.

Example:
    from cemaf.core.result import Result

    async def process(data: str) -> Result[ProcessedData]:
        if not data:
            return Result.fail("Empty input")
        return Result.ok(ProcessedData(value=data.upper()))
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from cemaf.core.types import JSON


def _utc_now():
    """Local utc_now to avoid circular import."""
    from datetime import datetime

    return datetime.now(UTC)


@dataclass(frozen=True)
class Result[T]:
    """
    Generic result type for any operation.

    Replaces: ToolResult, SkillResult, AgentResult, ValidationResult,
              NotifyResult, JobResult, CompletionResult, MediaOutput, etc.

    Usage:
        # Success with data
        result = Result.ok(my_data)

        # Failure with error
        result = Result.fail("Something went wrong")

        # Check and use
        if result.success:
            print(result.data)
        else:
            print(result.error)
    """

    success: bool
    data: T | None = None
    error: str | None = None
    metadata: JSON = field(default_factory=dict)
    created_at: datetime = field(default_factory=_utc_now)

    @classmethod
    def ok(
        cls,
        data: T,
        metadata: JSON | None = None,
    ) -> Result[T]:
        """Create a successful result."""
        return cls(
            success=True,
            data=data,
            metadata=metadata or {},
        )

    @classmethod
    def fail(
        cls,
        error: str,
        metadata: JSON | None = None,
    ) -> Result[T]:
        """Create a failed result."""
        return cls(
            success=False,
            error=error,
            metadata=metadata or {},
        )

    @classmethod
    def from_exception(cls, e: Exception) -> Result[T]:
        """Create a failed result from an exception."""
        return cls.fail(str(e), metadata={"exception_type": type(e).__name__})

    def map(self, fn: Any) -> Result[Any]:
        """Transform the data if successful."""
        if not self.success or self.data is None:
            return Result(success=False, error=self.error, metadata=self.metadata)
        return Result.ok(fn(self.data), self.metadata)

    def unwrap(self) -> T:
        """
        Get the data or raise an error.

        Raises:
            ValueError: If result is a failure.
        """
        if not self.success:
            raise ValueError(self.error or "Result failed")
        if self.data is None:
            raise ValueError("Result has no data")
        return self.data

    def unwrap_or(self, default: T) -> T:
        """Get the data or return a default value."""
        if self.success and self.data is not None:
            return self.data
        return default

    def __bool__(self) -> bool:
        """Allow `if result:` checks."""
        return self.success


# Type aliases for common result types
StringResult = Result[str]
DictResult = Result[dict[str, Any]]
ListResult = Result[list[Any]]
NoneResult = Result[None]

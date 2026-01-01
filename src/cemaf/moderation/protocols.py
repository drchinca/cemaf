"""
Moderation protocols and base types.

Defines the contracts for moderation rules, gates, and moderation results.
"""

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

from cemaf.core.types import JSON

# Type alias for moderation severity levels
ModerationSeverity = Literal["error", "warning", "info"]


@dataclass(frozen=True)
class ModerationViolation:
    """
    A moderation violation detected in content.

    Immutable record of a specific policy violation found during moderation.

    Attributes:
        code: Unique identifier for the violation type (e.g., "profanity", "pii_detected").
        message: Human-readable description of the violation.
        severity: The severity level of the violation.
        field: Optional field or location where the violation was found.
        suggestion: Optional suggestion for remediation.
    """

    code: str
    message: str
    severity: ModerationSeverity
    field: str | None = None
    suggestion: str | None = None


@dataclass(frozen=True)
class ModerationResult:
    """
    Result of a moderation operation.

    Contains the decision (allowed/blocked), any violations found,
    optionally redacted content, and metadata about the check.

    Attributes:
        allowed: Whether the content passed moderation.
        violations: Tuple of violations found (empty if allowed with no warnings).
        redacted_content: Content with sensitive parts redacted (if applicable).
        metadata: Additional context about the moderation decision.
    """

    allowed: bool
    violations: tuple[ModerationViolation, ...] = ()
    redacted_content: Any | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def success(cls) -> ModerationResult:
        """
        Create a successful moderation result with no violations.

        Returns:
            ModerationResult indicating content is allowed.
        """
        return cls(allowed=True)

    @classmethod
    def blocked(
        cls,
        violations: tuple[ModerationViolation, ...],
        metadata: dict[str, Any] | None = None,
    ) -> ModerationResult:
        """
        Create a blocked moderation result.

        Args:
            violations: The violations that caused the block.
            metadata: Optional additional context.

        Returns:
            ModerationResult indicating content is blocked.
        """
        return cls(
            allowed=False,
            violations=violations,
            metadata=metadata or {},
        )

    @classmethod
    def with_warnings(
        cls,
        violations: tuple[ModerationViolation, ...],
        redacted_content: Any | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ModerationResult:
        """
        Create an allowed result that includes warnings.

        Use this when content is allowed but has minor issues
        that should be flagged (e.g., info or warning severity).

        Args:
            violations: The warnings/info violations to include.
            redacted_content: Optional redacted version of content.
            metadata: Optional additional context.

        Returns:
            ModerationResult indicating content is allowed with warnings.
        """
        return cls(
            allowed=True,
            violations=violations,
            redacted_content=redacted_content,
            metadata=metadata or {},
        )


@runtime_checkable
class ModerationRule(Protocol):
    """
    Protocol for moderation rules.

    A ModerationRule checks content against a single policy or constraint.
    Rules are composable building blocks for moderation gates.
    """

    @property
    def name(self) -> str:
        """Unique identifier for this rule."""
        ...

    async def check(
        self,
        content: Any,
        context: JSON | None = None,
    ) -> ModerationResult:
        """
        Check content against this moderation rule.

        Args:
            content: The content to moderate (text, structured data, etc.).
            context: Optional context for moderation (e.g., user info, settings).

        Returns:
            ModerationResult indicating pass/fail with violations.
        """
        ...


@runtime_checkable
class ModerationGate(Protocol):
    """
    Protocol for moderation gates.

    A ModerationGate is a checkpoint that combines multiple rules
    to make a moderation decision. Gates can be placed at input,
    output, or intermediate points in a pipeline.
    """

    @property
    def name(self) -> str:
        """Unique identifier for this gate."""
        ...

    async def check(
        self,
        content: Any,
        context: JSON | None = None,
    ) -> ModerationResult:
        """
        Check content against all rules in this gate.

        Args:
            content: The content to moderate.
            context: Optional context for moderation.

        Returns:
            ModerationResult with aggregated violations from all rules.
        """
        ...

"""
Mock implementations for testing moderation.

Provides test doubles for moderation rules, gates, and pipelines.
"""

from __future__ import annotations

from typing import Any

from cemaf.moderation.protocols import (
    ModerationResult,
    ModerationViolation,
)


class AlwaysPassRule:
    """
    A rule that always passes - for testing.

    Use this when you need a rule that never produces violations,
    useful for verifying gate behavior with passing rules.

    Example:
        >>> rule = AlwaysPassRule(name="test_rule")
        >>> result = await rule.check("any content")
        >>> assert result.allowed is True
    """

    def __init__(self, name: str = "always_pass") -> None:
        """
        Initialize the always-pass rule.

        Args:
            name: Unique identifier for this rule.
        """
        self._name = name

    @property
    def name(self) -> str:
        """Unique identifier for this rule."""
        return self._name

    async def check(
        self,
        content: Any,
        context: Context | None = None,  # noqa: F821
    ) -> ModerationResult:
        """
        Check content - always returns success.

        Args:
            content: The content to check (ignored).
            context: Optional context (ignored).

        Returns:
            ModerationResult indicating content is allowed.
        """
        return ModerationResult.success()


class AlwaysBlockRule:
    """
    A rule that always blocks - for testing.

    Use this when you need a rule that always produces an error-level
    violation, useful for verifying gate blocking behavior.

    Example:
        >>> rule = AlwaysBlockRule(code="FORBIDDEN", message="Not allowed")
        >>> result = await rule.check("any content")
        >>> assert result.allowed is False
        >>> assert len(result.violations) == 1
    """

    def __init__(
        self,
        name: str = "always_block",
        code: str = "BLOCKED",
        message: str = "Content blocked by test rule",
    ) -> None:
        """
        Initialize the always-block rule.

        Args:
            name: Unique identifier for this rule.
            code: Violation code to use when blocking.
            message: Violation message to use when blocking.
        """
        self._name = name
        self._code = code
        self._message = message

    @property
    def name(self) -> str:
        """Unique identifier for this rule."""
        return self._name

    async def check(
        self,
        content: Any,
        context: Context | None = None,  # noqa: F821
    ) -> ModerationResult:
        """
        Check content - always returns blocked.

        Args:
            content: The content to check (ignored).
            context: Optional context (ignored).

        Returns:
            ModerationResult indicating content is blocked.
        """
        violation = ModerationViolation(
            code=self._code,
            message=self._message,
            severity="error",
        )
        return ModerationResult.blocked(violations=(violation,))


class AlwaysPassGate:
    """
    A gate that always passes - for testing.

    Use this when you need a gate that never blocks content,
    useful for verifying pipeline behavior with passing gates.

    Example:
        >>> gate = AlwaysPassGate(name="test_gate")
        >>> result = await gate.check("any content")
        >>> assert result.allowed is True
    """

    def __init__(self, name: str = "always_pass") -> None:
        """
        Initialize the always-pass gate.

        Args:
            name: Unique identifier for this gate.
        """
        self._name = name

    @property
    def name(self) -> str:
        """Unique identifier for this gate."""
        return self._name

    async def check(
        self,
        content: Any,
        context: Context | None = None,  # noqa: F821
    ) -> ModerationResult:
        """
        Check content - always returns success.

        Args:
            content: The content to check (ignored).
            context: Optional context (ignored).

        Returns:
            ModerationResult indicating content is allowed.
        """
        return ModerationResult.success()


class AlwaysBlockGate:
    """
    A gate that always blocks - for testing.

    Use this when you need a gate that always blocks content,
    useful for verifying pipeline error handling.

    Example:
        >>> gate = AlwaysBlockGate(code="GATE_BLOCKED", message="Blocked by gate")
        >>> result = await gate.check("any content")
        >>> assert result.allowed is False
    """

    def __init__(
        self,
        name: str = "always_block",
        code: str = "GATE_BLOCKED",
        message: str = "Content blocked by test gate",
    ) -> None:
        """
        Initialize the always-block gate.

        Args:
            name: Unique identifier for this gate.
            code: Violation code to use when blocking.
            message: Violation message to use when blocking.
        """
        self._name = name
        self._code = code
        self._message = message

    @property
    def name(self) -> str:
        """Unique identifier for this gate."""
        return self._name

    async def check(
        self,
        content: Any,
        context: Context | None = None,  # noqa: F821
    ) -> ModerationResult:
        """
        Check content - always returns blocked.

        Args:
            content: The content to check (ignored).
            context: Optional context (ignored).

        Returns:
            ModerationResult indicating content is blocked.
        """
        violation = ModerationViolation(
            code=self._code,
            message=self._message,
            severity="error",
        )
        return ModerationResult.blocked(violations=(violation,))


class RecordingRule:
    """
    A rule that records all checks for inspection - for testing.

    Use this when you need to verify what content was passed to moderation
    rules, useful for asserting that rules receive expected inputs.

    Example:
        >>> rule = RecordingRule(name="recorder")
        >>> await rule.check("hello", context)
        >>> await rule.check("world", context)
        >>> assert rule.call_count == 2
        >>> assert rule.checks[0][0] == "hello"
    """

    def __init__(
        self,
        name: str = "recording",
        should_pass: bool = True,
    ) -> None:
        """
        Initialize the recording rule.

        Args:
            name: Unique identifier for this rule.
            should_pass: Whether checks should pass or block.
        """
        self._name = name
        self._should_pass = should_pass
        self._checks: list[tuple[Any, Context | None]] = []  # noqa: F821

    @property
    def name(self) -> str:
        """Unique identifier for this rule."""
        return self._name

    @property
    def checks(self) -> list[tuple[Any, Context | None]]:  # noqa: F821
        """Return all recorded checks."""
        return self._checks.copy()

    @property
    def call_count(self) -> int:
        """Return the number of checks performed."""
        return len(self._checks)

    def set_pass(self, should_pass: bool) -> None:
        """Set whether future checks should pass."""
        self._should_pass = should_pass

    async def check(
        self,
        content: Any,
        context: Context | None = None,  # noqa: F821
    ) -> ModerationResult:
        """
        Record the check and return configured result.

        Args:
            content: The content to check.
            context: Optional context for moderation.

        Returns:
            ModerationResult based on should_pass configuration.
        """
        self._checks.append((content, context))

        if self._should_pass:
            return ModerationResult.success()

        violation = ModerationViolation(
            code="RECORDED_BLOCK",
            message="Recording rule blocked content",
            severity="error",
        )
        return ModerationResult.blocked(violations=(violation,))

    def clear(self) -> None:
        """Clear recorded checks."""
        self._checks.clear()


class RecordingGate:
    """
    A gate that records all checks for inspection - for testing.

    Useful for verifying moderation was called with expected content
    at specific checkpoints in the pipeline.

    Example:
        >>> gate = RecordingGate(name="input_gate")
        >>> await gate.check(user_input, context)
        >>> assert gate.call_count == 1
        >>> content, ctx = gate.checks[0]
        >>> assert content == user_input
    """

    def __init__(
        self,
        name: str = "recording",
        should_pass: bool = True,
    ) -> None:
        """
        Initialize the recording gate.

        Args:
            name: Unique identifier for this gate.
            should_pass: Whether checks should pass or block.
        """
        self._name = name
        self._should_pass = should_pass
        self._checks: list[tuple[Any, Context | None]] = []  # noqa: F821

    @property
    def name(self) -> str:
        """Unique identifier for this gate."""
        return self._name

    @property
    def checks(self) -> list[tuple[Any, Context | None]]:  # noqa: F821
        """Return all recorded checks."""
        return self._checks.copy()

    @property
    def call_count(self) -> int:
        """Return the number of checks performed."""
        return len(self._checks)

    def set_pass(self, should_pass: bool) -> None:
        """Set whether future checks should pass."""
        self._should_pass = should_pass

    async def check(
        self,
        content: Any,
        context: Context | None = None,  # noqa: F821
    ) -> ModerationResult:
        """
        Record the check and return configured result.

        Args:
            content: The content to check.
            context: Optional context for moderation.

        Returns:
            ModerationResult based on should_pass configuration.
        """
        self._checks.append((content, context))

        if self._should_pass:
            return ModerationResult.success()

        violation = ModerationViolation(
            code="GATE_RECORDED_BLOCK",
            message="Recording gate blocked content",
            severity="error",
        )
        return ModerationResult.blocked(violations=(violation,))

    def clear(self) -> None:
        """Clear recorded checks."""
        self._checks.clear()


class MockModerationPipeline:
    """
    Mock pipeline for testing - configurable pass/block behavior.

    Simulates a full moderation pipeline with pre-flight and post-flight
    gates. Useful for testing components that depend on moderation.

    Example:
        >>> pipeline = MockModerationPipeline(pre_flight_passes=True, post_flight_passes=False)
        >>> pre_result = await pipeline.pre_flight("input")
        >>> assert pre_result.allowed is True
        >>> post_result = await pipeline.post_flight("output")
        >>> assert post_result.allowed is False
    """

    def __init__(
        self,
        pre_flight_passes: bool = True,
        post_flight_passes: bool = True,
        pre_flight_code: str = "PRE_FLIGHT_BLOCKED",
        pre_flight_message: str = "Pre-flight check failed",
        post_flight_code: str = "POST_FLIGHT_BLOCKED",
        post_flight_message: str = "Post-flight check failed",
    ) -> None:
        """
        Initialize the mock pipeline.

        Args:
            pre_flight_passes: Whether pre-flight checks pass.
            post_flight_passes: Whether post-flight checks pass.
            pre_flight_code: Violation code for pre-flight blocks.
            pre_flight_message: Violation message for pre-flight blocks.
            post_flight_code: Violation code for post-flight blocks.
            post_flight_message: Violation message for post-flight blocks.
        """
        self._pre_flight_passes = pre_flight_passes
        self._post_flight_passes = post_flight_passes
        self._pre_flight_code = pre_flight_code
        self._pre_flight_message = pre_flight_message
        self._post_flight_code = post_flight_code
        self._post_flight_message = post_flight_message
        self._pre_flight_checks: list[tuple[Any, Context | None]] = []  # noqa: F821
        self._post_flight_checks: list[tuple[Any, Context | None]] = []  # noqa: F821

    @property
    def pre_flight_checks(self) -> list[tuple[Any, Context | None]]:  # noqa: F821
        """Return all recorded pre-flight checks."""
        return self._pre_flight_checks.copy()

    @property
    def post_flight_checks(self) -> list[tuple[Any, Context | None]]:  # noqa: F821
        """Return all recorded post-flight checks."""
        return self._post_flight_checks.copy()

    @property
    def pre_flight_call_count(self) -> int:
        """Return the number of pre-flight checks."""
        return len(self._pre_flight_checks)

    @property
    def post_flight_call_count(self) -> int:
        """Return the number of post-flight checks."""
        return len(self._post_flight_checks)

    def set_pre_flight_passes(self, passes: bool) -> None:
        """Set whether pre-flight checks should pass."""
        self._pre_flight_passes = passes

    def set_post_flight_passes(self, passes: bool) -> None:
        """Set whether post-flight checks should pass."""
        self._post_flight_passes = passes

    async def pre_flight(
        self,
        content: Any,
        context: Context | None = None,  # noqa: F821
    ) -> ModerationResult:
        """
        Run pre-flight moderation check.

        Args:
            content: The content to check.
            context: Optional context for moderation.

        Returns:
            ModerationResult based on pre_flight_passes configuration.
        """
        self._pre_flight_checks.append((content, context))

        if self._pre_flight_passes:
            return ModerationResult.success()

        violation = ModerationViolation(
            code=self._pre_flight_code,
            message=self._pre_flight_message,
            severity="error",
        )
        return ModerationResult.blocked(violations=(violation,))

    async def post_flight(
        self,
        content: Any,
        context: Context | None = None,  # noqa: F821
    ) -> ModerationResult:
        """
        Run post-flight moderation check.

        Args:
            content: The content to check.
            context: Optional context for moderation.

        Returns:
            ModerationResult based on post_flight_passes configuration.
        """
        self._post_flight_checks.append((content, context))

        if self._post_flight_passes:
            return ModerationResult.success()

        violation = ModerationViolation(
            code=self._post_flight_code,
            message=self._post_flight_message,
            severity="error",
        )
        return ModerationResult.blocked(violations=(violation,))

    def clear(self) -> None:
        """Clear all recorded checks."""
        self._pre_flight_checks.clear()
        self._post_flight_checks.clear()

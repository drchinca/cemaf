"""
Moderation gates for pre and post execution content checking.

Provides PreFlightGate and PostFlightGate implementations that compose
multiple ModerationRule instances into checkpoints for content moderation.
"""

from __future__ import annotations

from typing import Any

from cemaf.moderation.protocols import (
    ModerationResult,
    ModerationRule,
    ModerationViolation,
)


def _extract_text_content(content: Any) -> str:
    """
    Extract text from various content types for moderation.

    Handles strings, dicts with common text fields, and other types.

    Args:
        content: The content to extract text from.

    Returns:
        String representation of the content.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        # Try common text fields
        for key in ("text", "content", "message", "body", "output", "input"):
            if key in content and isinstance(content[key], str):
                return content[key]
        # Fall back to string representation
        return str(content)
    return str(content)


class PreFlightGate:
    """
    Pre-execution moderation gate.

    Checks content BEFORE it is processed by the system. Use this gate
    to validate user inputs, prompts, or any content entering the pipeline.

    Supports fail-fast mode where the first error-level violation stops
    further checks, or full evaluation mode where all rules are applied.

    Example:
        >>> rules = [ProfanityRule(), PIIRule(), ContentPolicyRule()]
        >>> gate = PreFlightGate(rules, fail_fast=True)
        >>> result = await gate.check(user_input)
        >>> if not result.allowed:
        ...     raise ContentBlockedError(result.violations)
    """

    def __init__(
        self,
        rules: list[ModerationRule],
        fail_fast: bool = True,
        name: str = "pre_flight",
    ) -> None:
        """
        Initialize the pre-flight gate.

        Args:
            rules: List of moderation rules to apply.
            fail_fast: If True, stop on first error-level violation.
                      If False, run all rules and collect all violations.
            name: Unique identifier for this gate.
        """
        self._rules = list(rules)
        self._fail_fast = fail_fast
        self._name = name

    @property
    def name(self) -> str:
        """Unique identifier for this gate."""
        return self._name

    @property
    def rules(self) -> list[ModerationRule]:
        """The moderation rules applied by this gate."""
        return list(self._rules)

    @property
    def fail_fast(self) -> bool:
        """Whether this gate stops on first error-level violation."""
        return self._fail_fast

    async def check(
        self,
        content: Any,
        context: Context | None = None,  # noqa: F821
    ) -> ModerationResult:
        """
        Run all rules against content.

        Applies each moderation rule to the content and aggregates the results.
        In fail-fast mode, stops immediately when an error-level violation
        is encountered. Otherwise, collects all violations from all rules.

        Args:
            content: The content to moderate (string, dict, or other type).
            context: Optional context for moderation decisions.

        Returns:
            ModerationResult with aggregated violations and allow/block decision.
        """
        if not self._rules:
            return ModerationResult.success()

        all_violations: list[ModerationViolation] = []
        context_dict = context.to_dict() if context else None

        for rule in self._rules:
            result = await rule.check(content, context_dict)

            if result.violations:
                all_violations.extend(result.violations)

                # In fail-fast mode, stop on first error-level violation
                if self._fail_fast:
                    has_error = any(v.severity == "error" for v in result.violations)
                    if has_error:
                        return ModerationResult.blocked(
                            violations=tuple(all_violations),
                            metadata={
                                "gate": self._name,
                                "failed_rule": rule.name,
                                "fail_fast": True,
                            },
                        )

        # Determine final result based on collected violations
        if not all_violations:
            return ModerationResult.success()

        # Check if any error-level violations exist
        has_errors = any(v.severity == "error" for v in all_violations)

        if has_errors:
            return ModerationResult.blocked(
                violations=tuple(all_violations),
                metadata={
                    "gate": self._name,
                    "rules_checked": [r.name for r in self._rules],
                },
            )

        # Only warnings or info - allow with warnings
        return ModerationResult.with_warnings(
            violations=tuple(all_violations),
            metadata={
                "gate": self._name,
                "rules_checked": [r.name for r in self._rules],
            },
        )


class PostFlightGate:
    """
    Post-execution moderation gate.

    Checks content AFTER it has been generated by the system. Use this gate
    to validate LLM outputs, generated content, or any content leaving the
    pipeline.

    Supports optional redaction mode where instead of blocking content,
    sensitive parts are redacted and the modified content is returned.

    Example:
        >>> rules = [PIIOutputRule(), ToxicityRule()]
        >>> gate = PostFlightGate(rules, redact_on_violation=True)
        >>> result = await gate.check(llm_response)
        >>> if result.redacted_content:
        ...     return result.redacted_content
        >>> elif not result.allowed:
        ...     return fallback_response()
    """

    def __init__(
        self,
        rules: list[ModerationRule],
        redact_on_violation: bool = False,
        name: str = "post_flight",
    ) -> None:
        """
        Initialize the post-flight gate.

        Args:
            rules: List of moderation rules to apply.
            redact_on_violation: If True, attempt to redact violating content
                                instead of blocking. If False, block on errors.
            name: Unique identifier for this gate.
        """
        self._rules = list(rules)
        self._redact_on_violation = redact_on_violation
        self._name = name

    @property
    def name(self) -> str:
        """Unique identifier for this gate."""
        return self._name

    @property
    def rules(self) -> list[ModerationRule]:
        """The moderation rules applied by this gate."""
        return list(self._rules)

    @property
    def redact_on_violation(self) -> bool:
        """Whether this gate attempts redaction instead of blocking."""
        return self._redact_on_violation

    async def check(
        self,
        content: Any,
        context: Context | None = None,  # noqa: F821
    ) -> ModerationResult:
        """
        Run all rules against content.

        Applies each moderation rule to the content and aggregates the results.
        If redact_on_violation is enabled and rules provide redacted content,
        returns the redacted version. Otherwise, blocks on error-level violations.

        Args:
            content: The content to moderate (string, dict, or other type).
            context: Optional context for moderation decisions.

        Returns:
            ModerationResult with aggregated violations and potentially
            redacted content.
        """
        if not self._rules:
            return ModerationResult.success()

        all_violations: list[ModerationViolation] = []
        redacted_content: Any = None
        working_content = content
        context_dict = context.to_dict() if context else None

        for rule in self._rules:
            result = await rule.check(working_content, context_dict)

            if result.violations:
                all_violations.extend(result.violations)

                # If redaction is enabled and rule provided redacted content
                if self._redact_on_violation and result.redacted_content is not None:
                    working_content = result.redacted_content
                    redacted_content = result.redacted_content

        # Determine final result based on collected violations
        if not all_violations:
            return ModerationResult.success()

        # Check if any error-level violations exist
        has_errors = any(v.severity == "error" for v in all_violations)

        # If redaction was performed, allow the redacted content
        if self._redact_on_violation and redacted_content is not None:
            return ModerationResult.with_warnings(
                violations=tuple(all_violations),
                redacted_content=redacted_content,
                metadata={
                    "gate": self._name,
                    "rules_checked": [r.name for r in self._rules],
                    "content_redacted": True,
                },
            )

        # No redaction - block on errors
        if has_errors:
            return ModerationResult.blocked(
                violations=tuple(all_violations),
                metadata={
                    "gate": self._name,
                    "rules_checked": [r.name for r in self._rules],
                },
            )

        # Only warnings or info - allow with warnings
        return ModerationResult.with_warnings(
            violations=tuple(all_violations),
            metadata={
                "gate": self._name,
                "rules_checked": [r.name for r in self._rules],
            },
        )


class CompositeGate:
    """
    A gate that combines multiple gates into a single checkpoint.

    Runs all child gates in sequence and aggregates their results.
    Useful for creating complex moderation pipelines with multiple
    stages of checks.

    Example:
        >>> pre_gate = PreFlightGate([InputSanitizer()])
        >>> post_gate = PostFlightGate([OutputValidator()])
        >>> composite = CompositeGate([pre_gate, post_gate])
        >>> result = await composite.check(content)
    """

    def __init__(
        self,
        gates: list[PreFlightGate | PostFlightGate],
        fail_fast: bool = True,
        name: str = "composite",
    ) -> None:
        """
        Initialize the composite gate.

        Args:
            gates: List of gates to run in sequence.
            fail_fast: If True, stop on first gate that blocks content.
            name: Unique identifier for this gate.
        """
        self._gates = list(gates)
        self._fail_fast = fail_fast
        self._name = name

    @property
    def name(self) -> str:
        """Unique identifier for this gate."""
        return self._name

    @property
    def gates(self) -> list[PreFlightGate | PostFlightGate]:
        """The gates that make up this composite."""
        return list(self._gates)

    async def check(
        self,
        content: Any,
        context: Context | None = None,  # noqa: F821
    ) -> ModerationResult:
        """
        Run all gates against content.

        Args:
            content: The content to moderate.
            context: Optional context for moderation decisions.

        Returns:
            ModerationResult with aggregated violations from all gates.
        """
        if not self._gates:
            return ModerationResult.success()

        all_violations: list[ModerationViolation] = []
        redacted_content: Any = None
        working_content = content

        for gate in self._gates:
            result = await gate.check(working_content, context)

            if result.violations:
                all_violations.extend(result.violations)

            # Track any redacted content
            if result.redacted_content is not None:
                working_content = result.redacted_content
                redacted_content = result.redacted_content

            # In fail-fast mode, stop if this gate blocked content
            if self._fail_fast and not result.allowed:
                return ModerationResult.blocked(
                    violations=tuple(all_violations),
                    metadata={
                        "gate": self._name,
                        "failed_at_gate": gate.name,
                        "fail_fast": True,
                    },
                )

        # Determine final result
        if not all_violations:
            return ModerationResult.success()

        has_errors = any(v.severity == "error" for v in all_violations)

        if has_errors:
            return ModerationResult.blocked(
                violations=tuple(all_violations),
                metadata={
                    "gate": self._name,
                    "gates_checked": [g.name for g in self._gates],
                },
            )

        return ModerationResult.with_warnings(
            violations=tuple(all_violations),
            redacted_content=redacted_content,
            metadata={
                "gate": self._name,
                "gates_checked": [g.name for g in self._gates],
            },
        )

"""
Moderation rules for content safety and compliance.

Provides reusable, composable rules for detecting PII, keywords,
content length issues, and custom patterns.
"""

import re
from dataclasses import dataclass, field
from typing import Any

from cemaf.core.types import JSON
from cemaf.moderation.protocols import (
    ModerationResult,
    ModerationSeverity,
    ModerationViolation,
)


@dataclass(frozen=True)
class PIIRule:
    """
    Rule for detecting personally identifiable information (PII).

    Detects common PII patterns including:
    - Email addresses
    - Phone numbers (various formats)
    - Social Security Numbers (XXX-XX-XXXX)
    - Credit card numbers (16 digits with optional separators)

    Attributes:
        detect_email: Whether to detect email addresses.
        detect_phone: Whether to detect phone numbers.
        detect_ssn: Whether to detect SSN patterns.
        detect_credit_card: Whether to detect credit card numbers.
        severity: Severity level for PII violations.
    """

    detect_email: bool = True
    detect_phone: bool = True
    detect_ssn: bool = True
    detect_credit_card: bool = True
    severity: ModerationSeverity = "error"

    # Regex patterns for PII detection
    _email_pattern: re.Pattern[str] = field(
        default_factory=lambda: re.compile(
            r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
            re.IGNORECASE,
        ),
        repr=False,
    )
    _phone_pattern: re.Pattern[str] = field(
        default_factory=lambda: re.compile(
            r"""
            (?:
                # International format with optional country code
                (?:\+?1[-.\s]?)?
                # Area code with optional parentheses
                (?:\(?\d{3}\)?[-.\s]?)
                # First 3 digits
                \d{3}[-.\s]?
                # Last 4 digits
                \d{4}
            )
            """,
            re.VERBOSE,
        ),
        repr=False,
    )
    _ssn_pattern: re.Pattern[str] = field(
        default_factory=lambda: re.compile(
            r"\b\d{3}-\d{2}-\d{4}\b",
        ),
        repr=False,
    )
    _credit_card_pattern: re.Pattern[str] = field(
        default_factory=lambda: re.compile(
            r"""
            \b
            (?:
                # 16 digits with optional separators (space, dash)
                \d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}
                |
                # Amex format (15 digits: 4-6-5)
                \d{4}[-\s]?\d{6}[-\s]?\d{5}
            )
            \b
            """,
            re.VERBOSE,
        ),
        repr=False,
    )

    @property
    def name(self) -> str:
        """Unique identifier for this rule."""
        return "pii_detection"

    async def check(
        self,
        content: Any,
        context: JSON | None = None,
    ) -> ModerationResult:
        """
        Check content for PII patterns.

        Args:
            content: The content to check (must be string-like).
            context: Optional context (unused).

        Returns:
            ModerationResult with any PII violations found.
        """
        if not isinstance(content, str):
            content = str(content)

        violations: list[ModerationViolation] = []

        # Check for emails
        if self.detect_email:
            for match in self._email_pattern.finditer(content):
                violations.append(
                    ModerationViolation(
                        code="pii_email",
                        message="Email address detected in content",
                        severity=self.severity,
                        field=f"position:{match.start()}",
                        suggestion="Remove or redact email address",
                    )
                )

        # Check for phone numbers
        if self.detect_phone:
            for match in self._phone_pattern.finditer(content):
                # Validate it looks like a real phone number (at least 10 digits)
                digits = re.sub(r"\D", "", match.group())
                if len(digits) >= 10:
                    violations.append(
                        ModerationViolation(
                            code="pii_phone",
                            message="Phone number detected in content",
                            severity=self.severity,
                            field=f"position:{match.start()}",
                            suggestion="Remove or redact phone number",
                        )
                    )

        # Check for SSN
        if self.detect_ssn:
            for match in self._ssn_pattern.finditer(content):
                violations.append(
                    ModerationViolation(
                        code="pii_ssn",
                        message="Social Security Number pattern detected",
                        severity=self.severity,
                        field=f"position:{match.start()}",
                        suggestion="Remove or redact SSN",
                    )
                )

        # Check for credit card numbers
        if self.detect_credit_card:
            for match in self._credit_card_pattern.finditer(content):
                violations.append(
                    ModerationViolation(
                        code="pii_credit_card",
                        message="Credit card number pattern detected",
                        severity=self.severity,
                        field=f"position:{match.start()}",
                        suggestion="Remove or redact credit card number",
                    )
                )

        if violations:
            return ModerationResult.blocked(
                violations=tuple(violations),
                metadata={"rule": self.name, "pii_count": len(violations)},
            )

        return ModerationResult.success()


@dataclass(frozen=True)
class KeywordRule:
    """
    Rule for detecting blocked keywords in content.

    Performs case-insensitive matching against a list of blocked words.
    Optionally matches whole words only.

    Attributes:
        blocked_words: List of words to block.
        whole_word_only: If True, only match complete words, not substrings.
        severity: Severity level for keyword violations.
    """

    blocked_words: tuple[str, ...] = ()
    whole_word_only: bool = True
    severity: ModerationSeverity = "error"

    @property
    def name(self) -> str:
        """Unique identifier for this rule."""
        return "keyword_detection"

    async def check(
        self,
        content: Any,
        context: JSON | None = None,
    ) -> ModerationResult:
        """
        Check content for blocked keywords.

        Args:
            content: The content to check (must be string-like).
            context: Optional context (unused).

        Returns:
            ModerationResult with any keyword violations found.
        """
        if not isinstance(content, str):
            content = str(content)

        if not self.blocked_words:
            return ModerationResult.success()

        violations: list[ModerationViolation] = []
        content_lower = content.lower()

        for word in self.blocked_words:
            word_lower = word.lower()

            if self.whole_word_only:
                # Use word boundary regex for whole word matching
                pattern = re.compile(
                    rf"\b{re.escape(word_lower)}\b",
                    re.IGNORECASE,
                )
                matches = list(pattern.finditer(content))
            else:
                # Find all substring occurrences
                matches = []
                start = 0
                while True:
                    pos = content_lower.find(word_lower, start)
                    if pos == -1:
                        break
                    # Create a simple match-like object
                    matches.append(
                        type("Match", (), {"start": lambda p=pos: p, "group": lambda w=word_lower: w})()
                    )
                    start = pos + 1

            for match in matches:
                violations.append(
                    ModerationViolation(
                        code="blocked_keyword",
                        message=f"Blocked keyword detected: '{word}'",
                        severity=self.severity,
                        field=f"position:{match.start()}",
                        suggestion="Remove or replace the blocked word",
                    )
                )

        if violations:
            return ModerationResult.blocked(
                violations=tuple(violations),
                metadata={
                    "rule": self.name,
                    "keywords_found": len(violations),
                },
            )

        return ModerationResult.success()


@dataclass(frozen=True)
class LengthRule:
    """
    Rule for validating content length.

    Checks that string content falls within specified length bounds.

    Attributes:
        min_length: Minimum allowed length (None for no minimum).
        max_length: Maximum allowed length (None for no maximum).
        severity: Severity level for length violations.
    """

    min_length: int | None = None
    max_length: int | None = None
    severity: ModerationSeverity = "warning"

    @property
    def name(self) -> str:
        """Unique identifier for this rule."""
        return "length_validation"

    async def check(
        self,
        content: Any,
        context: JSON | None = None,
    ) -> ModerationResult:
        """
        Check content length against bounds.

        Args:
            content: The content to check (must be string-like).
            context: Optional context (unused).

        Returns:
            ModerationResult with any length violations found.
        """
        if not isinstance(content, str):
            content = str(content)

        content_length = len(content)
        violations: list[ModerationViolation] = []

        if self.min_length is not None and content_length < self.min_length:
            violations.append(
                ModerationViolation(
                    code="content_too_short",
                    message=f"Content length ({content_length}) is below minimum ({self.min_length})",
                    severity=self.severity,
                    suggestion=f"Add at least {self.min_length - content_length} more characters",
                )
            )

        if self.max_length is not None and content_length > self.max_length:
            violations.append(
                ModerationViolation(
                    code="content_too_long",
                    message=f"Content length ({content_length}) exceeds maximum ({self.max_length})",
                    severity=self.severity,
                    suggestion=f"Remove at least {content_length - self.max_length} characters",
                )
            )

        if violations:
            return ModerationResult.blocked(
                violations=tuple(violations),
                metadata={
                    "rule": self.name,
                    "content_length": content_length,
                    "min_length": self.min_length,
                    "max_length": self.max_length,
                },
            )

        return ModerationResult.success()


@dataclass(frozen=True)
class PatternRule:
    """
    Rule for custom regex pattern matching.

    Provides flexible pattern-based moderation for custom use cases.

    Attributes:
        pattern: The regex pattern to match.
        violation_code: Code to use for violations.
        violation_message: Message to use for violations.
        severity: Severity level for pattern violations.
        suggestion: Optional suggestion for remediation.
    """

    pattern: str
    violation_code: str
    violation_message: str
    severity: ModerationSeverity = "error"
    suggestion: str | None = None

    _compiled_pattern: re.Pattern[str] | None = field(
        default=None,
        repr=False,
    )

    def __post_init__(self) -> None:
        """Compile the regex pattern after initialization."""
        # Use object.__setattr__ since the dataclass is frozen
        object.__setattr__(
            self,
            "_compiled_pattern",
            re.compile(self.pattern, re.IGNORECASE | re.MULTILINE),
        )

    @property
    def name(self) -> str:
        """Unique identifier for this rule."""
        return f"pattern_{self.violation_code}"

    async def check(
        self,
        content: Any,
        context: JSON | None = None,
    ) -> ModerationResult:
        """
        Check content against the custom pattern.

        Args:
            content: The content to check (must be string-like).
            context: Optional context (unused).

        Returns:
            ModerationResult with any pattern violations found.
        """
        if not isinstance(content, str):
            content = str(content)

        if self._compiled_pattern is None:
            # Fallback compilation if __post_init__ wasn't called
            compiled = re.compile(self.pattern, re.IGNORECASE | re.MULTILINE)
        else:
            compiled = self._compiled_pattern

        matches = list(compiled.finditer(content))

        if not matches:
            return ModerationResult.success()

        violations: list[ModerationViolation] = []
        for match in matches:
            violations.append(
                ModerationViolation(
                    code=self.violation_code,
                    message=self.violation_message,
                    severity=self.severity,
                    field=f"position:{match.start()}",
                    suggestion=self.suggestion,
                )
            )

        return ModerationResult.blocked(
            violations=tuple(violations),
            metadata={
                "rule": self.name,
                "pattern": self.pattern,
                "matches_found": len(violations),
            },
        )

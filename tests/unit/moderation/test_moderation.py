"""Tests for moderation module."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from cemaf.core.types import JSON
from cemaf.moderation import (
    CompositeGate,
    KeywordRule,
    LengthRule,
    ModerationResult,
    ModerationSeverity,
    ModerationViolation,
    PatternRule,
    PIIRule,
    PostFlightGate,
    PreFlightGate,
)

# =============================================================================
# Mock Rules for Testing
# =============================================================================


@dataclass(frozen=True)
class AlwaysPassRule:
    """A rule that always passes moderation."""

    @property
    def name(self) -> str:
        return "always_pass"

    async def check(
        self,
        content: Any,
        context: JSON | None = None,
    ) -> ModerationResult:
        return ModerationResult.success()


@dataclass(frozen=True)
class AlwaysBlockRule:
    """A rule that always blocks content."""

    violation_code: str = "BLOCKED"
    violation_message: str = "Content was blocked"
    severity: ModerationSeverity = "error"

    @property
    def name(self) -> str:
        return "always_block"

    async def check(
        self,
        content: Any,
        context: JSON | None = None,
    ) -> ModerationResult:
        violation = ModerationViolation(
            code=self.violation_code,
            message=self.violation_message,
            severity=self.severity,
        )
        return ModerationResult.blocked((violation,))


@dataclass(frozen=True)
class WarningOnlyRule:
    """A rule that only returns warnings (allows content)."""

    @property
    def name(self) -> str:
        return "warning_only"

    async def check(
        self,
        content: Any,
        context: JSON | None = None,
    ) -> ModerationResult:
        violation = ModerationViolation(
            code="WARNING",
            message="This is a warning",
            severity="warning",
        )
        return ModerationResult.with_warnings((violation,))


@dataclass(frozen=True)
class RedactingRule:
    """A rule that provides redacted content."""

    @property
    def name(self) -> str:
        return "redacting"

    async def check(
        self,
        content: Any,
        context: JSON | None = None,
    ) -> ModerationResult:
        violation = ModerationViolation(
            code="REDACTED",
            message="Content was redacted",
            severity="warning",
        )
        redacted = "[REDACTED]" if isinstance(content, str) else content
        return ModerationResult.with_warnings(
            (violation,),
            redacted_content=redacted,
        )


# =============================================================================
# ModerationViolation Tests
# =============================================================================


class TestModerationViolation:
    """Tests for ModerationViolation dataclass."""

    def test_create_violation(self) -> None:
        """Test creating a violation with required fields."""
        violation = ModerationViolation(
            code="TEST_CODE",
            message="Test message",
            severity="error",
        )
        assert violation.code == "TEST_CODE"
        assert violation.message == "Test message"
        assert violation.severity == "error"
        assert violation.field is None
        assert violation.suggestion is None

    def test_create_violation_with_optional_fields(self) -> None:
        """Test creating a violation with all fields."""
        violation = ModerationViolation(
            code="TEST_CODE",
            message="Test message",
            severity="warning",
            field="email_field",
            suggestion="Please remove the email",
        )
        assert violation.field == "email_field"
        assert violation.suggestion == "Please remove the email"

    def test_violation_is_immutable(self) -> None:
        """Test that violations are frozen."""
        violation = ModerationViolation(
            code="TEST",
            message="Test",
            severity="error",
        )
        with pytest.raises(Exception):  # FrozenInstanceError
            violation.code = "CHANGED"  # type: ignore


# =============================================================================
# ModerationResult Tests
# =============================================================================


class TestModerationResult:
    """Tests for ModerationResult."""

    def test_success_factory(self) -> None:
        """Test creating a successful result."""
        result = ModerationResult.success()
        assert result.allowed is True
        assert len(result.violations) == 0
        assert result.redacted_content is None
        assert result.metadata == {}

    def test_blocked_factory(self) -> None:
        """Test creating a blocked result."""
        violation = ModerationViolation(
            code="TEST",
            message="Test violation",
            severity="error",
        )
        result = ModerationResult.blocked((violation,))
        assert result.allowed is False
        assert len(result.violations) == 1
        assert result.violations[0].code == "TEST"

    def test_blocked_with_metadata(self) -> None:
        """Test blocked result with metadata."""
        violation = ModerationViolation(
            code="TEST",
            message="Test",
            severity="error",
        )
        result = ModerationResult.blocked(
            (violation,),
            metadata={"rule": "test_rule"},
        )
        assert result.metadata == {"rule": "test_rule"}

    def test_with_warnings_factory(self) -> None:
        """Test creating result with warnings."""
        violation = ModerationViolation(
            code="WARN",
            message="Warning message",
            severity="warning",
        )
        result = ModerationResult.with_warnings((violation,))
        assert result.allowed is True
        assert len(result.violations) == 1
        assert result.violations[0].severity == "warning"

    def test_with_warnings_and_redacted_content(self) -> None:
        """Test warnings with redacted content."""
        violation = ModerationViolation(
            code="PII",
            message="PII detected",
            severity="warning",
        )
        result = ModerationResult.with_warnings(
            (violation,),
            redacted_content="Hello [REDACTED]",
        )
        assert result.allowed is True
        assert result.redacted_content == "Hello [REDACTED]"

    def test_with_warnings_and_metadata(self) -> None:
        """Test warnings with metadata."""
        violation = ModerationViolation(
            code="WARN",
            message="Warning",
            severity="warning",
        )
        result = ModerationResult.with_warnings(
            (violation,),
            metadata={"source": "test"},
        )
        assert result.metadata == {"source": "test"}

    def test_result_is_immutable(self) -> None:
        """Test that results are frozen."""
        result = ModerationResult.success()
        with pytest.raises(Exception):  # FrozenInstanceError
            result.allowed = False  # type: ignore


# =============================================================================
# PIIRule Tests
# =============================================================================


class TestPIIRule:
    """Tests for PIIRule."""

    @pytest.mark.asyncio
    async def test_detects_email(self) -> None:
        """Test that email addresses are detected."""
        rule = PIIRule()
        result = await rule.check("Contact me at test@example.com")
        assert result.allowed is False
        assert any(v.code == "pii_email" for v in result.violations)

    @pytest.mark.asyncio
    async def test_detects_multiple_emails(self) -> None:
        """Test detecting multiple email addresses."""
        rule = PIIRule()
        result = await rule.check("Email john@example.com or jane@test.org")
        assert result.allowed is False
        email_violations = [v for v in result.violations if v.code == "pii_email"]
        assert len(email_violations) == 2

    @pytest.mark.asyncio
    async def test_detects_phone_number(self) -> None:
        """Test that phone numbers are detected."""
        rule = PIIRule()
        result = await rule.check("Call me at 555-123-4567")
        assert result.allowed is False
        assert any(v.code == "pii_phone" for v in result.violations)

    @pytest.mark.asyncio
    async def test_detects_phone_with_parentheses(self) -> None:
        """Test phone number with area code in parentheses."""
        rule = PIIRule()
        result = await rule.check("Call (555) 123-4567")
        assert result.allowed is False
        assert any(v.code == "pii_phone" for v in result.violations)

    @pytest.mark.asyncio
    async def test_detects_phone_international(self) -> None:
        """Test international phone format."""
        rule = PIIRule()
        result = await rule.check("Call +1-555-123-4567")
        assert result.allowed is False
        assert any(v.code == "pii_phone" for v in result.violations)

    @pytest.mark.asyncio
    async def test_detects_ssn(self) -> None:
        """Test that SSN patterns are detected."""
        rule = PIIRule()
        result = await rule.check("SSN: 123-45-6789")
        assert result.allowed is False
        assert any(v.code == "pii_ssn" for v in result.violations)

    @pytest.mark.asyncio
    async def test_detects_credit_card(self) -> None:
        """Test that credit card numbers are detected."""
        rule = PIIRule()
        result = await rule.check("Card: 1234-5678-9012-3456")
        assert result.allowed is False
        assert any(v.code == "pii_credit_card" for v in result.violations)

    @pytest.mark.asyncio
    async def test_detects_credit_card_no_separators(self) -> None:
        """Test credit card without separators."""
        rule = PIIRule()
        result = await rule.check("Card: 1234567890123456")
        assert result.allowed is False
        assert any(v.code == "pii_credit_card" for v in result.violations)

    @pytest.mark.asyncio
    async def test_clean_text_passes(self) -> None:
        """Test that clean text passes."""
        rule = PIIRule()
        result = await rule.check("Hello world, this is a clean message.")
        assert result.allowed is True
        assert len(result.violations) == 0

    @pytest.mark.asyncio
    async def test_selective_detection_email_only(self) -> None:
        """Test detecting only emails when other types are disabled."""
        rule = PIIRule(
            detect_email=True,
            detect_phone=False,
            detect_ssn=False,
            detect_credit_card=False,
        )
        result = await rule.check("Email: test@example.com, SSN: 123-45-6789")
        assert result.allowed is False
        assert len(result.violations) == 1
        assert result.violations[0].code == "pii_email"

    @pytest.mark.asyncio
    async def test_all_detection_disabled(self) -> None:
        """Test when all detection is disabled."""
        rule = PIIRule(
            detect_email=False,
            detect_phone=False,
            detect_ssn=False,
            detect_credit_card=False,
        )
        result = await rule.check("Email: test@example.com")
        assert result.allowed is True

    @pytest.mark.asyncio
    async def test_custom_severity(self) -> None:
        """Test custom severity level."""
        rule = PIIRule(severity="warning")
        result = await rule.check("test@example.com")
        assert result.violations[0].severity == "warning"

    @pytest.mark.asyncio
    async def test_non_string_content(self) -> None:
        """Test with non-string content."""
        rule = PIIRule()
        result = await rule.check(12345)
        assert result.allowed is True

    @pytest.mark.asyncio
    async def test_rule_name(self) -> None:
        """Test the rule name property."""
        rule = PIIRule()
        assert rule.name == "pii_detection"

    @pytest.mark.asyncio
    async def test_metadata_includes_pii_count(self) -> None:
        """Test that metadata includes PII count."""
        rule = PIIRule()
        result = await rule.check("test@example.com and test2@example.com")
        assert result.metadata.get("pii_count") == 2


# =============================================================================
# KeywordRule Tests
# =============================================================================


class TestKeywordRule:
    """Tests for KeywordRule."""

    @pytest.mark.asyncio
    async def test_detects_blocked_word(self) -> None:
        """Test detecting a blocked word."""
        rule = KeywordRule(blocked_words=("spam", "scam"))
        result = await rule.check("This is a spam message")
        assert result.allowed is False
        assert any(v.code == "blocked_keyword" for v in result.violations)

    @pytest.mark.asyncio
    async def test_case_insensitive(self) -> None:
        """Test case insensitive matching."""
        rule = KeywordRule(blocked_words=("spam",))
        result = await rule.check("This is SPAM")
        assert result.allowed is False

    @pytest.mark.asyncio
    async def test_whole_word_matching(self) -> None:
        """Test whole word matching (default)."""
        rule = KeywordRule(blocked_words=("spam",), whole_word_only=True)

        # Should match whole word
        result = await rule.check("This is spam")
        assert result.allowed is False

        # Should NOT match as substring
        result = await rule.check("This is antispam")
        assert result.allowed is True

    @pytest.mark.asyncio
    async def test_substring_matching(self) -> None:
        """Test substring matching when whole_word_only is False."""
        rule = KeywordRule(blocked_words=("spam",), whole_word_only=False)

        # Should match substring
        result = await rule.check("This is antispam software")
        assert result.allowed is False

    @pytest.mark.asyncio
    async def test_multiple_blocked_words(self) -> None:
        """Test multiple blocked words in content."""
        rule = KeywordRule(blocked_words=("spam", "scam"))
        result = await rule.check("This spam is a scam")
        assert result.allowed is False
        assert len(result.violations) == 2

    @pytest.mark.asyncio
    async def test_clean_text_passes(self) -> None:
        """Test that clean text passes."""
        rule = KeywordRule(blocked_words=("spam", "scam"))
        result = await rule.check("This is a legitimate message")
        assert result.allowed is True

    @pytest.mark.asyncio
    async def test_empty_blocked_words(self) -> None:
        """Test with empty blocked words list."""
        rule = KeywordRule(blocked_words=())
        result = await rule.check("Any content")
        assert result.allowed is True

    @pytest.mark.asyncio
    async def test_custom_severity(self) -> None:
        """Test custom severity level."""
        rule = KeywordRule(blocked_words=("spam",), severity="warning")
        result = await rule.check("spam")
        assert result.violations[0].severity == "warning"

    @pytest.mark.asyncio
    async def test_rule_name(self) -> None:
        """Test the rule name property."""
        rule = KeywordRule(blocked_words=("spam",))
        assert rule.name == "keyword_detection"

    @pytest.mark.asyncio
    async def test_metadata_includes_keywords_found(self) -> None:
        """Test that metadata includes keywords found count."""
        rule = KeywordRule(blocked_words=("spam", "scam"))
        result = await rule.check("spam and scam")
        assert result.metadata.get("keywords_found") == 2


# =============================================================================
# LengthRule Tests
# =============================================================================


class TestLengthRule:
    """Tests for LengthRule."""

    @pytest.mark.asyncio
    async def test_min_length_pass(self) -> None:
        """Test content that meets minimum length."""
        rule = LengthRule(min_length=5)
        result = await rule.check("hello world")
        assert result.allowed is True

    @pytest.mark.asyncio
    async def test_min_length_fail(self) -> None:
        """Test content that fails minimum length."""
        rule = LengthRule(min_length=10)
        result = await rule.check("hello")
        assert result.allowed is False
        assert any(v.code == "content_too_short" for v in result.violations)

    @pytest.mark.asyncio
    async def test_max_length_pass(self) -> None:
        """Test content that meets maximum length."""
        rule = LengthRule(max_length=20)
        result = await rule.check("hello")
        assert result.allowed is True

    @pytest.mark.asyncio
    async def test_max_length_fail(self) -> None:
        """Test content that exceeds maximum length."""
        rule = LengthRule(max_length=5)
        result = await rule.check("hello world")
        assert result.allowed is False
        assert any(v.code == "content_too_long" for v in result.violations)

    @pytest.mark.asyncio
    async def test_both_bounds_pass(self) -> None:
        """Test content within both bounds."""
        rule = LengthRule(min_length=5, max_length=20)
        result = await rule.check("hello world")
        assert result.allowed is True

    @pytest.mark.asyncio
    async def test_both_bounds_fail_min(self) -> None:
        """Test content below minimum with both bounds."""
        rule = LengthRule(min_length=10, max_length=20)
        result = await rule.check("hi")
        assert result.allowed is False
        assert any(v.code == "content_too_short" for v in result.violations)

    @pytest.mark.asyncio
    async def test_both_bounds_fail_max(self) -> None:
        """Test content above maximum with both bounds."""
        rule = LengthRule(min_length=1, max_length=5)
        result = await rule.check("hello world")
        assert result.allowed is False
        assert any(v.code == "content_too_long" for v in result.violations)

    @pytest.mark.asyncio
    async def test_no_bounds(self) -> None:
        """Test with no bounds (always passes)."""
        rule = LengthRule()
        result = await rule.check("any content")
        assert result.allowed is True

    @pytest.mark.asyncio
    async def test_exact_min_length(self) -> None:
        """Test content exactly at minimum length."""
        rule = LengthRule(min_length=5)
        result = await rule.check("hello")
        assert result.allowed is True

    @pytest.mark.asyncio
    async def test_exact_max_length(self) -> None:
        """Test content exactly at maximum length."""
        rule = LengthRule(max_length=5)
        result = await rule.check("hello")
        assert result.allowed is True

    @pytest.mark.asyncio
    async def test_empty_content(self) -> None:
        """Test empty content with minimum length."""
        rule = LengthRule(min_length=1)
        result = await rule.check("")
        assert result.allowed is False

    @pytest.mark.asyncio
    async def test_violation_includes_suggestion(self) -> None:
        """Test that violations include suggestions."""
        rule = LengthRule(min_length=10)
        result = await rule.check("hi")
        assert result.violations[0].suggestion is not None

    @pytest.mark.asyncio
    async def test_rule_name(self) -> None:
        """Test the rule name property."""
        rule = LengthRule()
        assert rule.name == "length_validation"

    @pytest.mark.asyncio
    async def test_metadata_includes_lengths(self) -> None:
        """Test that metadata includes length info."""
        rule = LengthRule(min_length=10, max_length=20)
        result = await rule.check("hi")
        assert result.metadata.get("content_length") == 2
        assert result.metadata.get("min_length") == 10
        assert result.metadata.get("max_length") == 20


# =============================================================================
# PatternRule Tests
# =============================================================================


class TestPatternRule:
    """Tests for PatternRule."""

    @pytest.mark.asyncio
    async def test_pattern_match(self) -> None:
        """Test pattern matching."""
        rule = PatternRule(
            pattern=r"password\s*[:=]\s*\S+",
            violation_code="PASSWORD_EXPOSED",
            violation_message="Password detected in content",
        )
        result = await rule.check("password=test_secret_placeholder")
        assert result.allowed is False
        assert result.violations[0].code == "PASSWORD_EXPOSED"

    @pytest.mark.asyncio
    async def test_pattern_no_match(self) -> None:
        """Test when pattern does not match."""
        rule = PatternRule(
            pattern=r"password\s*[:=]\s*\S+",
            violation_code="PASSWORD_EXPOSED",
            violation_message="Password detected",
        )
        result = await rule.check("This is clean content")
        assert result.allowed is True

    @pytest.mark.asyncio
    async def test_multiple_matches(self) -> None:
        """Test multiple pattern matches."""
        rule = PatternRule(
            pattern=r"secret",
            violation_code="SECRET",
            violation_message="Secret found",
        )
        result = await rule.check("secret data and another secret")
        assert result.allowed is False
        assert len(result.violations) == 2

    @pytest.mark.asyncio
    async def test_case_insensitive(self) -> None:
        """Test case insensitive matching."""
        rule = PatternRule(
            pattern=r"password",
            violation_code="PASSWORD",
            violation_message="Password found",
        )
        result = await rule.check("PASSWORD here")
        assert result.allowed is False

    @pytest.mark.asyncio
    async def test_custom_suggestion(self) -> None:
        """Test custom suggestion in violations."""
        rule = PatternRule(
            pattern=r"api_key",
            violation_code="API_KEY",
            violation_message="API key found",
            suggestion="Remove the API key",
        )
        result = await rule.check("api_key=test_api_key_placeholder")
        assert result.violations[0].suggestion == "Remove the API key"

    @pytest.mark.asyncio
    async def test_custom_severity(self) -> None:
        """Test custom severity level."""
        rule = PatternRule(
            pattern=r"warning",
            violation_code="WARN",
            violation_message="Warning word found",
            severity="warning",
        )
        result = await rule.check("this is a warning")
        assert result.violations[0].severity == "warning"

    @pytest.mark.asyncio
    async def test_rule_name(self) -> None:
        """Test the rule name property."""
        rule = PatternRule(
            pattern=r"test",
            violation_code="TEST",
            violation_message="Test",
        )
        assert rule.name == "pattern_TEST"

    @pytest.mark.asyncio
    async def test_metadata_includes_pattern_info(self) -> None:
        """Test that metadata includes pattern info."""
        rule = PatternRule(
            pattern=r"secret",
            violation_code="SECRET",
            violation_message="Secret found",
        )
        result = await rule.check("secret")
        assert result.metadata.get("pattern") == r"secret"
        assert result.metadata.get("matches_found") == 1


# =============================================================================
# PreFlightGate Tests
# =============================================================================


class TestPreFlightGate:
    """Tests for PreFlightGate."""

    @pytest.mark.asyncio
    async def test_empty_rules_passes(self) -> None:
        """Test gate with no rules passes."""
        gate = PreFlightGate(rules=[])
        result = await gate.check("any content")
        assert result.allowed is True

    @pytest.mark.asyncio
    async def test_single_passing_rule(self) -> None:
        """Test gate with single passing rule."""
        gate = PreFlightGate(rules=[AlwaysPassRule()])
        result = await gate.check("content")
        assert result.allowed is True

    @pytest.mark.asyncio
    async def test_single_blocking_rule(self) -> None:
        """Test gate with single blocking rule."""
        gate = PreFlightGate(rules=[AlwaysBlockRule()])
        result = await gate.check("content")
        assert result.allowed is False

    @pytest.mark.asyncio
    async def test_fail_fast_stops_on_first_error(self) -> None:
        """Test fail_fast mode stops on first error."""
        gate = PreFlightGate(
            rules=[
                AlwaysBlockRule(violation_code="FIRST"),
                AlwaysBlockRule(violation_code="SECOND"),
            ],
            fail_fast=True,
        )
        result = await gate.check("content")
        assert result.allowed is False
        assert len(result.violations) == 1
        assert result.violations[0].code == "FIRST"
        assert result.metadata.get("fail_fast") is True

    @pytest.mark.asyncio
    async def test_fail_fast_false_collects_all(self) -> None:
        """Test collecting all violations when fail_fast is False."""
        gate = PreFlightGate(
            rules=[
                AlwaysBlockRule(violation_code="FIRST"),
                AlwaysBlockRule(violation_code="SECOND"),
            ],
            fail_fast=False,
        )
        result = await gate.check("content")
        assert result.allowed is False
        assert len(result.violations) == 2

    @pytest.mark.asyncio
    async def test_warnings_only_allows(self) -> None:
        """Test that only warnings allows content."""
        gate = PreFlightGate(rules=[WarningOnlyRule()])
        result = await gate.check("content")
        assert result.allowed is True
        assert len(result.violations) == 1
        assert result.violations[0].severity == "warning"

    @pytest.mark.asyncio
    async def test_mixed_pass_and_fail(self) -> None:
        """Test mixed passing and failing rules."""
        gate = PreFlightGate(
            rules=[
                AlwaysPassRule(),
                AlwaysBlockRule(),
            ],
            fail_fast=False,
        )
        result = await gate.check("content")
        assert result.allowed is False

    @pytest.mark.asyncio
    async def test_gate_name(self) -> None:
        """Test gate name property."""
        gate = PreFlightGate(rules=[], name="input_gate")
        assert gate.name == "input_gate"

    @pytest.mark.asyncio
    async def test_rules_property(self) -> None:
        """Test rules property returns list of rules."""
        rules = [AlwaysPassRule(), AlwaysBlockRule()]
        gate = PreFlightGate(rules=rules)
        assert len(gate.rules) == 2

    @pytest.mark.asyncio
    async def test_fail_fast_property(self) -> None:
        """Test fail_fast property."""
        gate = PreFlightGate(rules=[], fail_fast=False)
        assert gate.fail_fast is False

    @pytest.mark.asyncio
    async def test_metadata_includes_gate_name(self) -> None:
        """Test that metadata includes gate name."""
        gate = PreFlightGate(
            rules=[AlwaysBlockRule()],
            name="my_gate",
        )
        result = await gate.check("content")
        assert result.metadata.get("gate") == "my_gate"

    @pytest.mark.asyncio
    async def test_metadata_includes_failed_rule(self) -> None:
        """Test that fail_fast metadata includes failed rule name."""
        gate = PreFlightGate(
            rules=[AlwaysBlockRule()],
            fail_fast=True,
        )
        result = await gate.check("content")
        assert result.metadata.get("failed_rule") == "always_block"


# =============================================================================
# PostFlightGate Tests
# =============================================================================


class TestPostFlightGate:
    """Tests for PostFlightGate."""

    @pytest.mark.asyncio
    async def test_empty_rules_passes(self) -> None:
        """Test gate with no rules passes."""
        gate = PostFlightGate(rules=[])
        result = await gate.check("any content")
        assert result.allowed is True

    @pytest.mark.asyncio
    async def test_single_passing_rule(self) -> None:
        """Test gate with single passing rule."""
        gate = PostFlightGate(rules=[AlwaysPassRule()])
        result = await gate.check("content")
        assert result.allowed is True

    @pytest.mark.asyncio
    async def test_single_blocking_rule(self) -> None:
        """Test gate with single blocking rule."""
        gate = PostFlightGate(rules=[AlwaysBlockRule()])
        result = await gate.check("content")
        assert result.allowed is False

    @pytest.mark.asyncio
    async def test_redaction_enabled(self) -> None:
        """Test redaction mode with redacting rule."""
        gate = PostFlightGate(
            rules=[RedactingRule()],
            redact_on_violation=True,
        )
        result = await gate.check("sensitive content")
        assert result.allowed is True
        assert result.redacted_content == "[REDACTED]"
        assert result.metadata.get("content_redacted") is True

    @pytest.mark.asyncio
    async def test_redaction_disabled(self) -> None:
        """Test when redaction is disabled."""
        gate = PostFlightGate(
            rules=[RedactingRule()],
            redact_on_violation=False,
        )
        result = await gate.check("content")
        # Without redaction, warnings still allow
        assert result.allowed is True
        assert result.redacted_content is None

    @pytest.mark.asyncio
    async def test_warnings_only_allows(self) -> None:
        """Test that only warnings allows content."""
        gate = PostFlightGate(rules=[WarningOnlyRule()])
        result = await gate.check("content")
        assert result.allowed is True
        assert len(result.violations) == 1

    @pytest.mark.asyncio
    async def test_gate_name(self) -> None:
        """Test gate name property."""
        gate = PostFlightGate(rules=[], name="output_gate")
        assert gate.name == "output_gate"

    @pytest.mark.asyncio
    async def test_rules_property(self) -> None:
        """Test rules property returns list of rules."""
        rules = [AlwaysPassRule()]
        gate = PostFlightGate(rules=rules)
        assert len(gate.rules) == 1

    @pytest.mark.asyncio
    async def test_redact_on_violation_property(self) -> None:
        """Test redact_on_violation property."""
        gate = PostFlightGate(rules=[], redact_on_violation=True)
        assert gate.redact_on_violation is True

    @pytest.mark.asyncio
    async def test_metadata_includes_gate_name(self) -> None:
        """Test that metadata includes gate name."""
        gate = PostFlightGate(
            rules=[AlwaysBlockRule()],
            name="my_gate",
        )
        result = await gate.check("content")
        assert result.metadata.get("gate") == "my_gate"

    @pytest.mark.asyncio
    async def test_metadata_includes_rules_checked(self) -> None:
        """Test that metadata includes checked rules."""
        gate = PostFlightGate(
            rules=[AlwaysPassRule(), WarningOnlyRule()],
        )
        result = await gate.check("content")
        assert "always_pass" in result.metadata.get("rules_checked", [])
        assert "warning_only" in result.metadata.get("rules_checked", [])


# =============================================================================
# CompositeGate Tests
# =============================================================================


class TestCompositeGate:
    """Tests for CompositeGate."""

    @pytest.mark.asyncio
    async def test_empty_gates_passes(self) -> None:
        """Test composite with no gates passes."""
        composite = CompositeGate(gates=[])
        result = await composite.check("any content")
        assert result.allowed is True

    @pytest.mark.asyncio
    async def test_single_passing_gate(self) -> None:
        """Test composite with single passing gate."""
        pre_gate = PreFlightGate(rules=[AlwaysPassRule()])
        composite = CompositeGate(gates=[pre_gate])
        result = await composite.check("content")
        assert result.allowed is True

    @pytest.mark.asyncio
    async def test_single_blocking_gate(self) -> None:
        """Test composite with single blocking gate."""
        pre_gate = PreFlightGate(rules=[AlwaysBlockRule()])
        composite = CompositeGate(gates=[pre_gate])
        result = await composite.check("content")
        assert result.allowed is False

    @pytest.mark.asyncio
    async def test_multiple_gates(self) -> None:
        """Test composite with multiple gates."""
        pre_gate = PreFlightGate(rules=[AlwaysPassRule()])
        post_gate = PostFlightGate(rules=[AlwaysPassRule()])
        composite = CompositeGate(gates=[pre_gate, post_gate])
        result = await composite.check("content")
        assert result.allowed is True

    @pytest.mark.asyncio
    async def test_fail_fast_stops_on_first_blocking_gate(self) -> None:
        """Test fail_fast stops on first blocking gate."""
        gate1 = PreFlightGate(rules=[AlwaysBlockRule(violation_code="GATE1")])
        gate2 = PreFlightGate(rules=[AlwaysBlockRule(violation_code="GATE2")])
        composite = CompositeGate(gates=[gate1, gate2], fail_fast=True)
        result = await composite.check("content")
        assert result.allowed is False
        assert result.metadata.get("fail_fast") is True
        # Should stop at first gate
        assert result.metadata.get("failed_at_gate") is not None

    @pytest.mark.asyncio
    async def test_fail_fast_false_runs_all_gates(self) -> None:
        """Test all gates run when fail_fast is False."""
        gate1 = PreFlightGate(rules=[AlwaysBlockRule(violation_code="GATE1")])
        gate2 = PreFlightGate(rules=[AlwaysBlockRule(violation_code="GATE2")])
        composite = CompositeGate(gates=[gate1, gate2], fail_fast=False)
        result = await composite.check("content")
        assert result.allowed is False
        assert len(result.violations) == 2

    @pytest.mark.asyncio
    async def test_redacted_content_propagates(self) -> None:
        """Test that redacted content propagates through gates."""
        gate1 = PostFlightGate(
            rules=[RedactingRule()],
            redact_on_violation=True,
        )
        gate2 = PostFlightGate(rules=[AlwaysPassRule()])
        composite = CompositeGate(gates=[gate1, gate2])
        result = await composite.check("sensitive")
        # Content was redacted by first gate
        assert result.redacted_content is not None

    @pytest.mark.asyncio
    async def test_gate_name(self) -> None:
        """Test composite gate name property."""
        composite = CompositeGate(gates=[], name="my_composite")
        assert composite.name == "my_composite"

    @pytest.mark.asyncio
    async def test_gates_property(self) -> None:
        """Test gates property returns list of gates."""
        pre_gate = PreFlightGate(rules=[])
        composite = CompositeGate(gates=[pre_gate])
        assert len(composite.gates) == 1

    @pytest.mark.asyncio
    async def test_metadata_includes_gates_checked(self) -> None:
        """Test that metadata includes checked gates."""
        gate1 = PreFlightGate(rules=[WarningOnlyRule()], name="gate1")
        gate2 = PreFlightGate(rules=[WarningOnlyRule()], name="gate2")
        composite = CompositeGate(gates=[gate1, gate2])
        result = await composite.check("content")
        assert "gate1" in result.metadata.get("gates_checked", [])
        assert "gate2" in result.metadata.get("gates_checked", [])


# =============================================================================
# Mock Classes Tests
# =============================================================================


class TestMockRules:
    """Tests for mock moderation rules."""

    @pytest.mark.asyncio
    async def test_always_pass_rule(self) -> None:
        """Test AlwaysPassRule always passes."""
        rule = AlwaysPassRule()
        result = await rule.check("any content")
        assert result.allowed is True
        assert len(result.violations) == 0

    @pytest.mark.asyncio
    async def test_always_block_rule(self) -> None:
        """Test AlwaysBlockRule always blocks."""
        rule = AlwaysBlockRule()
        result = await rule.check("any content")
        assert result.allowed is False
        assert len(result.violations) == 1

    @pytest.mark.asyncio
    async def test_always_block_custom_code(self) -> None:
        """Test AlwaysBlockRule with custom violation code."""
        rule = AlwaysBlockRule(violation_code="CUSTOM_CODE")
        result = await rule.check("content")
        assert result.violations[0].code == "CUSTOM_CODE"

    @pytest.mark.asyncio
    async def test_always_block_custom_message(self) -> None:
        """Test AlwaysBlockRule with custom message."""
        rule = AlwaysBlockRule(violation_message="Custom message")
        result = await rule.check("content")
        assert result.violations[0].message == "Custom message"

    @pytest.mark.asyncio
    async def test_always_block_custom_severity(self) -> None:
        """Test AlwaysBlockRule with custom severity."""
        rule = AlwaysBlockRule(severity="warning")
        result = await rule.check("content")
        assert result.violations[0].severity == "warning"

    @pytest.mark.asyncio
    async def test_warning_only_rule(self) -> None:
        """Test WarningOnlyRule allows with warning."""
        rule = WarningOnlyRule()
        result = await rule.check("content")
        assert result.allowed is True
        assert len(result.violations) == 1
        assert result.violations[0].severity == "warning"

    @pytest.mark.asyncio
    async def test_redacting_rule(self) -> None:
        """Test RedactingRule provides redacted content."""
        rule = RedactingRule()
        result = await rule.check("sensitive data")
        assert result.allowed is True
        assert result.redacted_content == "[REDACTED]"


# =============================================================================
# Integration Tests
# =============================================================================


class TestModerationIntegration:
    """Integration tests for moderation components."""

    @pytest.mark.asyncio
    async def test_full_preflight_pipeline(self) -> None:
        """Test complete pre-flight moderation pipeline."""
        gate = PreFlightGate(
            rules=[
                LengthRule(min_length=5, max_length=1000),
                KeywordRule(blocked_words=("spam", "scam")),
                PIIRule(),
            ],
            fail_fast=True,
            name="input_moderation",
        )

        # Clean content passes
        result = await gate.check("Hello, this is a legitimate message.")
        assert result.allowed is True

        # Content with PII fails
        result = await gate.check("Contact me at test@example.com")
        assert result.allowed is False
        assert any(v.code == "pii_email" for v in result.violations)

    @pytest.mark.asyncio
    async def test_full_postflight_pipeline(self) -> None:
        """Test complete post-flight moderation pipeline."""
        gate = PostFlightGate(
            rules=[
                PIIRule(),
                LengthRule(max_length=10000),
            ],
            redact_on_violation=False,
            name="output_moderation",
        )

        # Clean output passes
        result = await gate.check("This is a clean response.")
        assert result.allowed is True

    @pytest.mark.asyncio
    async def test_composite_pipeline(self) -> None:
        """Test composite gate with pre and post gates."""
        pre_gate = PreFlightGate(
            rules=[LengthRule(min_length=1)],
            name="pre",
        )
        post_gate = PostFlightGate(
            rules=[LengthRule(max_length=10000)],
            name="post",
        )
        composite = CompositeGate(
            gates=[pre_gate, post_gate],
            name="full_pipeline",
        )

        result = await composite.check("Valid content")
        assert result.allowed is True

    @pytest.mark.asyncio
    async def test_pattern_rule_for_secrets(self) -> None:
        """Test using PatternRule to detect secrets."""
        secret_patterns = [
            PatternRule(
                pattern=r"api[_-]?key\s*[:=]\s*\S+",
                violation_code="API_KEY",
                violation_message="API key detected",
                severity="error",
            ),
            PatternRule(
                pattern=r"password\s*[:=]\s*\S+",
                violation_code="PASSWORD",
                violation_message="Password detected",
                severity="error",
            ),
        ]

        gate = PreFlightGate(rules=secret_patterns, fail_fast=True)

        result = await gate.check("api_key=test_api_key_placeholder")
        assert result.allowed is False
        assert result.violations[0].code == "API_KEY"

        result = await gate.check("password: test_password_placeholder")
        assert result.allowed is False
        assert result.violations[0].code == "PASSWORD"

        result = await gate.check("No secrets here")
        assert result.allowed is True

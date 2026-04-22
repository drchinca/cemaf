"""Tests for ContentBlockedError-style moderation blocking behavior.

Validates that the moderation pipeline and gates correctly block
prohibited content and pass clean content through, with proper
violation details in the result.
"""

from dataclasses import dataclass
from typing import Any

import pytest

from cemaf.core.types import JSON
from cemaf.moderation import (
    KeywordRule,
    ModerationPipeline,
    ModerationResult,
    ModerationViolation,
    PIIRule,
    PreFlightGate,
)


@dataclass(frozen=True)
class ProhibitedContentRule:
    """Rule that blocks specific prohibited phrases."""

    prohibited_phrases: tuple[str, ...] = ("DROP TABLE", "rm -rf", "exec(")

    @property
    def name(self) -> str:
        return "prohibited_content"

    async def check(
        self,
        content: Any,
        context: JSON | None = None,
    ) -> ModerationResult:
        """Block content containing prohibited phrases."""
        text = str(content).lower()
        violations = []
        for phrase in self.prohibited_phrases:
            if phrase.lower() in text:
                violations.append(
                    ModerationViolation(
                        code="prohibited_content",
                        message=f"Prohibited phrase detected: {phrase}",
                        severity="error",
                    )
                )
        if violations:
            return ModerationResult.blocked(
                violations=tuple(violations),
                metadata={"rule": self.name},
            )
        return ModerationResult.success()


class TestPipelineBlocksOnViolation:
    """Pipeline raises blocked result when content violates a rule."""

    @pytest.mark.asyncio
    async def test_pipeline_raises_content_blocked_on_violation(self) -> None:
        """Pipeline returns blocked result for violating content."""
        pre_gate = PreFlightGate(
            rules=[ProhibitedContentRule()],
            fail_fast=True,
        )
        pipeline = ModerationPipeline(pre_flight=pre_gate)

        result = await pipeline.check_input(content="DROP TABLE users;")

        assert result.allowed is False
        assert len(result.violations) >= 1
        assert any(v.code == "prohibited_content" for v in result.violations)

    @pytest.mark.asyncio
    async def test_content_blocked_error_contains_reason(self) -> None:
        """Blocked result includes the rule name and violation reason."""
        pre_gate = PreFlightGate(
            rules=[ProhibitedContentRule()],
            fail_fast=True,
        )
        pipeline = ModerationPipeline(pre_flight=pre_gate)

        result = await pipeline.check_input(content="exec(bad_code)")

        assert result.allowed is False
        violation = result.violations[0]
        assert "exec(" in violation.message
        assert violation.severity == "error"
        assert result.metadata.get("gate") is not None

    @pytest.mark.asyncio
    async def test_pipeline_passes_clean_content(self) -> None:
        """Clean content passes through the pipeline without violations."""
        pre_gate = PreFlightGate(
            rules=[
                ProhibitedContentRule(),
                KeywordRule(blocked_words=("spam",)),
            ],
            fail_fast=True,
        )
        pipeline = ModerationPipeline(pre_flight=pre_gate)

        result = await pipeline.check_input(
            content="This is a perfectly normal message about software development."
        )

        assert result.allowed is True
        assert len(result.violations) == 0


class TestGateBlocksProhibitedContent:
    """Gate directly blocks prohibited content."""

    @pytest.mark.asyncio
    async def test_gate_blocks_prohibited_content(self) -> None:
        """PreFlightGate blocks content matching a blocking rule."""
        gate = PreFlightGate(
            rules=[
                KeywordRule(blocked_words=("malware", "exploit")),
                PIIRule(),
            ],
            fail_fast=True,
        )

        result = await gate.check("Download this malware payload")

        assert result.allowed is False
        assert any(v.code == "blocked_keyword" for v in result.violations)
        assert result.metadata.get("fail_fast") is True

    @pytest.mark.asyncio
    async def test_gate_allows_clean_content(self) -> None:
        """PreFlightGate allows content that passes all rules."""
        gate = PreFlightGate(
            rules=[
                KeywordRule(blocked_words=("malware", "exploit")),
                PIIRule(),
            ],
            fail_fast=True,
        )

        result = await gate.check("This is a clean message about productivity tools.")

        assert result.allowed is True
        assert len(result.violations) == 0

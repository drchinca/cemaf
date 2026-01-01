"""
Tests for basic evaluators.
"""

import pytest

from cemaf.evals.evaluators import (
    ContainsEvaluator,
    ExactMatchEvaluator,
    JSONSchemaEvaluator,
    LengthEvaluator,
    RegexEvaluator,
)
from cemaf.evals.protocols import EvalMetric


class TestExactMatchEvaluator:
    """Tests for ExactMatchEvaluator."""

    @pytest.mark.asyncio
    async def test_exact_match_passes(self):
        """Exact match passes."""
        evaluator = ExactMatchEvaluator()

        result = await evaluator.evaluate("hello", expected="hello")

        assert result.passed
        assert result.score == 1.0

    @pytest.mark.asyncio
    async def test_mismatch_fails(self):
        """Mismatch fails."""
        evaluator = ExactMatchEvaluator()

        result = await evaluator.evaluate("hello", expected="world")

        assert not result.passed
        assert result.score == 0.0

    @pytest.mark.asyncio
    async def test_case_insensitive(self):
        """Case insensitive matching."""
        evaluator = ExactMatchEvaluator(case_sensitive=False)

        result = await evaluator.evaluate("Hello", expected="HELLO")

        assert result.passed

    @pytest.mark.asyncio
    async def test_whitespace_stripping(self):
        """Whitespace is stripped."""
        evaluator = ExactMatchEvaluator(strip_whitespace=True)

        result = await evaluator.evaluate("  hello  ", expected="hello")

        assert result.passed


class TestContainsEvaluator:
    """Tests for ContainsEvaluator."""

    @pytest.mark.asyncio
    async def test_contains_passes(self):
        """Contains substring passes."""
        evaluator = ContainsEvaluator()

        result = await evaluator.evaluate("The quick brown fox", expected="quick")

        assert result.passed

    @pytest.mark.asyncio
    async def test_not_contains_fails(self):
        """Missing substring fails."""
        evaluator = ContainsEvaluator()

        result = await evaluator.evaluate("Hello world", expected="foo")

        assert not result.passed

    @pytest.mark.asyncio
    async def test_multiple_substrings_all(self):
        """All substrings required with require_all=True."""
        evaluator = ContainsEvaluator(require_all=True)

        result = await evaluator.evaluate("The quick brown fox", expected=["quick", "brown"])

        assert result.passed
        assert result.score == 1.0

    @pytest.mark.asyncio
    async def test_multiple_substrings_any(self):
        """Any substring with require_all=False."""
        evaluator = ContainsEvaluator(require_all=False)

        result = await evaluator.evaluate("The quick brown fox", expected=["missing", "quick"])

        assert result.passed

    @pytest.mark.asyncio
    async def test_case_insensitive(self):
        """Case insensitive contains."""
        evaluator = ContainsEvaluator(case_sensitive=False)

        result = await evaluator.evaluate("HELLO WORLD", expected="hello")

        assert result.passed


class TestRegexEvaluator:
    """Tests for RegexEvaluator."""

    @pytest.mark.asyncio
    async def test_regex_match(self):
        """Regex pattern matches."""
        evaluator = RegexEvaluator()

        result = await evaluator.evaluate("Email: test@example.com", expected=r"\w+@\w+\.\w+")

        assert result.passed

    @pytest.mark.asyncio
    async def test_regex_no_match(self):
        """Regex pattern doesn't match."""
        evaluator = RegexEvaluator()

        result = await evaluator.evaluate("No email here", expected=r"\w+@\w+\.\w+")

        assert not result.passed

    @pytest.mark.asyncio
    async def test_invalid_regex(self):
        """Invalid regex returns failure."""
        evaluator = RegexEvaluator()

        result = await evaluator.evaluate("test", expected="[invalid")

        assert not result.passed
        assert "Invalid regex" in result.reason


class TestLengthEvaluator:
    """Tests for LengthEvaluator."""

    @pytest.mark.asyncio
    async def test_within_range(self):
        """Length within range passes."""
        evaluator = LengthEvaluator(min_length=5, max_length=20)

        result = await evaluator.evaluate("Hello world")  # 11 chars

        assert result.passed
        assert result.score == 1.0

    @pytest.mark.asyncio
    async def test_too_short(self):
        """Too short fails."""
        evaluator = LengthEvaluator(min_length=10)

        result = await evaluator.evaluate("Hi")  # 2 chars

        assert not result.passed
        assert "too short" in result.reason

    @pytest.mark.asyncio
    async def test_too_long(self):
        """Too long fails."""
        evaluator = LengthEvaluator(max_length=5)

        result = await evaluator.evaluate("Hello world")  # 11 chars

        assert not result.passed
        assert "too long" in result.reason

    @pytest.mark.asyncio
    async def test_word_count(self):
        """Word count mode."""
        evaluator = LengthEvaluator(min_length=2, max_length=5, unit="words")

        result = await evaluator.evaluate("one two three")  # 3 words

        assert result.passed


class TestJSONSchemaEvaluator:
    """Tests for JSONSchemaEvaluator."""

    @pytest.mark.asyncio
    async def test_valid_json(self):
        """Valid JSON passes."""
        evaluator = JSONSchemaEvaluator()

        result = await evaluator.evaluate('{"key": "value"}')

        assert result.passed
        assert result.metric == EvalMetric.JSON_VALID

    @pytest.mark.asyncio
    async def test_invalid_json(self):
        """Invalid JSON fails."""
        evaluator = JSONSchemaEvaluator()

        result = await evaluator.evaluate("{invalid json}")

        assert not result.passed
        assert "Invalid JSON" in result.reason

    @pytest.mark.asyncio
    async def test_schema_type_check(self):
        """Schema type validation."""
        schema = {"type": "object"}
        evaluator = JSONSchemaEvaluator(schema=schema)

        result = await evaluator.evaluate('{"key": "value"}')
        assert result.passed

        result = await evaluator.evaluate("[1, 2, 3]")
        assert not result.passed

    @pytest.mark.asyncio
    async def test_required_properties(self):
        """Required properties check."""
        from cemaf.evals.protocols import EvalConfig

        schema = {
            "type": "object",
            "required": ["name", "age"],
        }
        # Set threshold to 1.0 so missing required properties fail
        evaluator = JSONSchemaEvaluator(
            schema=schema,
            config=EvalConfig(pass_threshold=1.0),
        )

        result = await evaluator.evaluate('{"name": "Alice", "age": 30}')
        assert result.passed

        result = await evaluator.evaluate('{"name": "Alice"}')
        assert not result.passed  # score=0.5, threshold=1.0 -> fail

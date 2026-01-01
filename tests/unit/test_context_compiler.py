"""
Tests for context compiler.

Uses fixtures from conftest.py:
- token_budget: Standard TokenBudget
- context_compiler: PriorityContextCompiler
"""

import pytest

from cemaf.context.budget import TokenBudget
from cemaf.context.compiler import (
    CompiledContext,
    ContextSource,
    PriorityContextCompiler,
    SimpleTokenEstimator,
)


class TestTokenBudget:
    """Tests for TokenBudget."""

    def test_available_tokens(self, token_budget: TokenBudget):
        """available_tokens subtracts reserved_for_output."""
        assert token_budget.available_tokens == token_budget.max_tokens - token_budget.reserved_for_output

    def test_default_budget(self):
        """Default budget uses constants."""
        budget = TokenBudget.default()
        assert budget.max_tokens > 0
        assert budget.reserved_for_output > 0

    def test_for_model(self):
        """for_model returns appropriate limits."""
        gpt4_budget = TokenBudget.for_model("gpt-4")
        claude_budget = TokenBudget.for_model("claude-3-opus")

        assert gpt4_budget.max_tokens == 8_192
        assert claude_budget.max_tokens == 200_000

    def test_with_allocation(self, token_budget: TokenBudget):
        """with_allocation adds allocation."""
        budget = token_budget.with_allocation("system", 1000, priority=10)

        assert budget.get_section_budget("system") == 1000


class TestSimpleTokenEstimator:
    """Tests for SimpleTokenEstimator."""

    def test_estimate_basic(self):
        """Estimate uses chars_per_token ratio."""
        estimator = SimpleTokenEstimator(chars_per_token=4.0)

        # 20 chars / 4 = 5 tokens
        assert estimator.estimate("12345678901234567890") == 5

    def test_estimate_minimum_one(self):
        """Estimate returns at least 1."""
        estimator = SimpleTokenEstimator(chars_per_token=100.0)

        assert estimator.estimate("hi") == 1


class TestContextSource:
    """Tests for ContextSource."""

    def test_creation(self):
        """ContextSource can be created."""
        source = ContextSource(
            type="artifact",
            key="brand_guide",
            content="Brand values...",
            token_count=50,
            priority=10,
        )

        assert source.type == "artifact"
        assert source.priority == 10


class TestCompiledContext:
    """Tests for CompiledContext."""

    def test_content_hash_deterministic(self, token_budget: TokenBudget):
        """Same content produces same hash."""
        sources = (
            ContextSource(type="artifact", key="a", content="content_a", token_count=10),
            ContextSource(type="memory", key="b", content="content_b", token_count=10),
        )

        ctx1 = CompiledContext(sources=sources, total_tokens=20, budget=token_budget)
        ctx2 = CompiledContext(sources=sources, total_tokens=20, budget=token_budget)

        assert ctx1.content_hash == ctx2.content_hash

    def test_within_budget_respects_available(self):
        """within_budget uses available_tokens, not max_tokens."""
        budget = TokenBudget(max_tokens=1000, reserved_for_output=200)
        sources = (ContextSource(type="artifact", key="a", content="x" * 900, token_count=900),)

        # 900 tokens > 800 available (1000 - 200)
        ctx = CompiledContext(sources=sources, total_tokens=900, budget=budget)

        assert not ctx.within_budget()  # Should fail because 900 > 800 available

    def test_within_budget_passes(self):
        """within_budget passes when under available."""
        budget = TokenBudget(max_tokens=1000, reserved_for_output=200)
        sources = (ContextSource(type="artifact", key="a", content="x", token_count=100),)

        ctx = CompiledContext(sources=sources, total_tokens=100, budget=budget)

        assert ctx.within_budget()  # 100 < 800 available

    def test_to_messages(self, token_budget: TokenBudget):
        """to_messages creates message format."""
        sources = (
            ContextSource(type="artifact", key="guide", content="Brand guide...", token_count=10),
            ContextSource(type="memory", key="user_pref", content="Prefers formal", token_count=5),
        )

        ctx = CompiledContext(sources=sources, total_tokens=15, budget=token_budget)
        messages = ctx.to_messages()

        assert len(messages) == 1
        assert messages[0]["role"] == "system"
        assert "guide" in messages[0]["content"]
        assert "user_pref" in messages[0]["content"]


class TestPriorityContextCompiler:
    """Tests for PriorityContextCompiler."""

    @pytest.mark.asyncio
    async def test_compile_respects_budget(self, context_compiler: PriorityContextCompiler):
        """Compiler respects available token budget."""
        compiler = context_compiler
        budget = TokenBudget(max_tokens=100, reserved_for_output=50)  # 50 available

        artifacts = (
            ("small", "x" * 40),  # ~10 tokens
            ("large", "y" * 400),  # ~100 tokens - won't fit
        )

        ctx = await compiler.compile(artifacts=artifacts, memories=(), budget=budget)

        # Only small should fit (50 available tokens)
        assert ctx.total_tokens <= budget.available_tokens
        assert any(s.key == "small" for s in ctx.sources)

    @pytest.mark.asyncio
    async def test_compile_respects_priority(self, context_compiler: PriorityContextCompiler):
        """Higher priority sources included first."""
        compiler = context_compiler
        budget = TokenBudget(max_tokens=50, reserved_for_output=0)  # 50 available

        artifacts = (
            ("low_priority", "x" * 100),  # ~25 tokens
            ("high_priority", "y" * 100),  # ~25 tokens
        )
        priorities = {"high_priority": 10, "low_priority": 1}

        ctx = await compiler.compile(
            artifacts=artifacts,
            memories=(),
            budget=budget,
            priorities=priorities,
        )

        # High priority should be included
        keys = [s.key for s in ctx.sources]
        if len(keys) > 0:
            assert keys[0] == "high_priority"

    @pytest.mark.asyncio
    async def test_compile_includes_memories(self, context_compiler: PriorityContextCompiler):
        """Memories are included with lower default priority."""
        compiler = context_compiler
        budget = TokenBudget(max_tokens=1000, reserved_for_output=0)

        memories = (("user_context", "User prefers concise responses"),)

        ctx = await compiler.compile(artifacts=(), memories=memories, budget=budget)

        assert any(s.type == "memory" for s in ctx.sources)

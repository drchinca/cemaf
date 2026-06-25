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
from cemaf.context.patch import SecurityLevel


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


class TestSecurityClearanceGate:
    """SPEC-11 §2.2/§3 — clearance-gated compilation."""

    @pytest.mark.asyncio
    async def test_compile_accepts_security_kwargs(self, context_compiler: PriorityContextCompiler):
        """L0 (§10a) — compile accepts source_levels + clearance and returns a CompiledContext."""
        budget = TokenBudget(max_tokens=1000, reserved_for_output=0)
        ctx = await context_compiler.compile(
            artifacts=(("a", "content"),),
            memories=(),
            budget=budget,
            source_levels={"a": SecurityLevel.PUBLIC},
            clearance=SecurityLevel.CONFIDENTIAL,
        )
        assert isinstance(ctx, CompiledContext)

    @pytest.mark.asyncio
    async def test_confidential_excluded_under_internal_clearance(
        self, context_compiler: PriorityContextCompiler
    ):
        """Inv 4 — a CONFIDENTIAL source is dropped and recorded when clearance=INTERNAL."""
        budget = TokenBudget(max_tokens=1000, reserved_for_output=0)
        artifacts = (("notes", "public notes"), ("secrets", "api key inside"))
        ctx = await context_compiler.compile(
            artifacts=artifacts,
            memories=(),
            budget=budget,
            source_levels={"secrets": SecurityLevel.CONFIDENTIAL, "notes": SecurityLevel.PUBLIC},
            clearance=SecurityLevel.INTERNAL,
        )
        keys = [s.key for s in ctx.sources]
        assert "notes" in keys
        assert "secrets" not in keys
        assert "secrets" in ctx.metadata.get("security_excluded", [])

    @pytest.mark.asyncio
    async def test_no_clearance_selects_identical_set(self, context_compiler: PriorityContextCompiler):
        """Inv 3 / Property 3 — clearance=None yields the IDENTICAL set as the ungated path.

        Strengthened: multi-source mixed-level input compiled (a) with classification but no
        clearance and (b) with no security kwargs at all → identical ordered keys + content_hash.
        """
        budget = TokenBudget(max_tokens=10000, reserved_for_output=0)
        artifacts = (("pub", "public notes"), ("conf", "api key"), ("int", "internal memo"))
        memories = (("mem", "a remembered fact"),)

        gated_off = await context_compiler.compile(
            artifacts=artifacts,
            memories=memories,
            budget=budget,
            source_levels={"conf": SecurityLevel.CONFIDENTIAL, "pub": SecurityLevel.PUBLIC},
            clearance=None,
        )
        pristine = await context_compiler.compile(
            artifacts=artifacts,
            memories=memories,
            budget=budget,
        )
        assert [s.key for s in gated_off.sources] == [s.key for s in pristine.sources]
        assert gated_off.content_hash == pristine.content_hash
        assert gated_off.metadata.get("security_excluded", []) == []

    @pytest.mark.asyncio
    async def test_content_hash_independent_of_security_level(
        self, context_compiler: PriorityContextCompiler
    ):
        """Inv 7 — classification SHALL NOT alter content_hash determinism."""
        budget = TokenBudget(max_tokens=10000, reserved_for_output=0)
        artifacts = (("a", "same content"),)
        as_conf = await context_compiler.compile(
            artifacts=artifacts,
            memories=(),
            budget=budget,
            source_levels={"a": SecurityLevel.CONFIDENTIAL},
            clearance=None,
        )
        as_public = await context_compiler.compile(
            artifacts=artifacts,
            memories=(),
            budget=budget,
            source_levels={"a": SecurityLevel.PUBLIC},
            clearance=None,
        )
        assert as_conf.content_hash == as_public.content_hash

    @pytest.mark.asyncio
    async def test_public_clearance_drops_unclassified_internal(
        self, context_compiler: PriorityContextCompiler
    ):
        """Default-level foot-gun — an unclassified source (INTERNAL) is dropped under PUBLIC clearance."""
        budget = TokenBudget(max_tokens=1000, reserved_for_output=0)
        ctx = await context_compiler.compile(
            artifacts=(("plain", "content"),),  # absent from source_levels ⇒ INTERNAL
            memories=(),
            budget=budget,
            clearance=SecurityLevel.PUBLIC,
        )
        assert all(s.key != "plain" for s in ctx.sources)
        assert "plain" in ctx.metadata.get("security_excluded", [])

    @pytest.mark.asyncio
    async def test_confidential_clearance_includes_all_levels(
        self, context_compiler: PriorityContextCompiler
    ):
        """Upper bound — clearance=CONFIDENTIAL excludes nothing."""
        budget = TokenBudget(max_tokens=10000, reserved_for_output=0)
        artifacts = (("p", "x"), ("i", "y"), ("c", "z"))
        ctx = await context_compiler.compile(
            artifacts=artifacts,
            memories=(),
            budget=budget,
            source_levels={
                "p": SecurityLevel.PUBLIC,
                "i": SecurityLevel.INTERNAL,
                "c": SecurityLevel.CONFIDENTIAL,
            },
            clearance=SecurityLevel.CONFIDENTIAL,
        )
        keys = {s.key for s in ctx.sources}
        assert keys == {"p", "i", "c"}
        assert ctx.metadata.get("security_excluded", []) == []

    @pytest.mark.asyncio
    async def test_confidential_memory_excluded_under_internal_clearance(
        self, context_compiler: PriorityContextCompiler
    ):
        """Memories are gated too — a CONFIDENTIAL memory is dropped under INTERNAL clearance."""
        budget = TokenBudget(max_tokens=1000, reserved_for_output=0)
        ctx = await context_compiler.compile(
            artifacts=(),
            memories=(("secret_mem", "leaked detail"),),
            budget=budget,
            source_levels={"secret_mem": SecurityLevel.CONFIDENTIAL},
            clearance=SecurityLevel.INTERNAL,
        )
        assert all(s.key != "secret_mem" for s in ctx.sources)
        assert "secret_mem" in ctx.metadata.get("security_excluded", [])

    @pytest.mark.asyncio
    async def test_unclassified_source_defaults_internal(self, context_compiler: PriorityContextCompiler):
        """A source absent from source_levels is treated as INTERNAL (passes INTERNAL clearance)."""
        budget = TokenBudget(max_tokens=1000, reserved_for_output=0)
        ctx = await context_compiler.compile(
            artifacts=(("plain", "content"),),
            memories=(),
            budget=budget,
            clearance=SecurityLevel.INTERNAL,
        )
        assert any(s.key == "plain" for s in ctx.sources)

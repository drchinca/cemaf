"""
Integration tests for Agent-Native features: Time-Travel, Auto-Heal, and Semantic Caching.
"""

import pytest

from cemaf.cache.semantic import SemanticStateCache
from cemaf.context.context import Context
from cemaf.context.patch import ContextPatch, PatchSource
from cemaf.core.recovery import AutoHealManager, RecoveryStrategy
from cemaf.core.result import Result
from cemaf.retrieval.memory_store import InMemoryVectorStore
from cemaf.retrieval.protocols import EmbeddingProvider


class SimpleEmbeddingProvider(EmbeddingProvider):
    """Simple embedding provider for semantic-cache integration tests."""

    _dimension = 384

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def model_name(self) -> str:
        return "simple-test"

    async def embed(self, text: str) -> tuple[float, ...]:
        # Use the existing MockEmbeddingProvider's logic for better differentiation
        import json
        import math

        # For semantic caching, we want functionally equivalent states to have same embedding.
        # We sort keys in JSON to ensure stability.
        try:
            data = json.loads(text)
            stable_text = json.dumps(data, sort_keys=True)
        except ValueError, TypeError:
            stable_text = text

        embedding = [0.0] * self._dimension
        for i, char in enumerate(stable_text.lower()):
            idx = (ord(char) + i) % self._dimension
            embedding[idx] += 0.1
        norm = math.sqrt(sum(x * x for x in embedding)) or 1.0
        return tuple(x / norm for x in embedding)

    async def embed_batch(self, texts: list[str]) -> list[tuple[float, ...]]:
        return [await self.embed(t) for t in texts]


class TokenLimitRecovery(RecoveryStrategy):
    """Real-world style recovery strategy for token limits."""

    def recover(self, error_result: Result, context: Context) -> Result[Context]:
        # Simulate 'healing' by removing large data and adding a summary
        if "large_data" in context.data:
            # Use apply() with a patch to ensure timeline tracking
            patch = ContextPatch.set(
                "summary",
                "Data was too large, summarized here.",
                source=PatchSource.SYSTEM,
                reason="auto_heal",
            )
            # delete() currently preserves history, apply() adds to it
            new_ctx = context.delete("large_data").apply(patch)
            return Result.ok(new_ctx)
        return Result.fail("Could not heal: large_data not found")


@pytest.mark.asyncio
async def test_integration_time_travel_and_auto_heal():
    """
    Scenario:
    1. Agent performs steps, creating a timeline.
    2. An error occurs (Token Limit).
    3. We use Time-Travel to look at history.
    4. We use Auto-Heal to fix the state and continue.
    """
    # 1. Setup timeline
    ctx = Context()
    p1 = ContextPatch.set("step1", "started", source=PatchSource.AGENT, reason="init")
    p2 = ContextPatch.set("large_data", "x" * 1000, source=PatchSource.TOOL, reason="fetch")

    ctx = ctx.apply(p1).apply(p2)

    # 2. Simulate failure
    error_result = Result.fail(
        "Token limit exceeded", metadata={"exception_type": "TokenLimitExceeded"}
    ).with_hint(action="summarize", reason="large_payload", suggestion="Remove large_data")

    # 3. Time-Travel check
    timeline = ctx.get_timeline()
    assert len(timeline) == 2
    # Verify we can see the state before the 'large_data' was added
    state_before_fetch = ctx.rollback_to(p1.id)
    assert state_before_fetch.get("large_data") is None
    assert state_before_fetch.get("step1") == "started"

    # 4. Auto-Heal
    manager = AutoHealManager()
    manager.register("TokenLimitExceeded", TokenLimitRecovery())

    heal_result = manager.heal(error_result, ctx)
    assert heal_result.success
    healed_ctx = heal_result.data

    assert healed_ctx.get("large_data") is None
    assert healed_ctx.get("summary") == "Data was too large, summarized here."
    assert healed_ctx.get("step1") == "started"
    # Timeline should persist through healing if implemented via patches
    assert len(healed_ctx.get_timeline()) > len(ctx.get_timeline())


@pytest.mark.asyncio
async def test_integration_semantic_caching_flow():
    """
    Scenario:
    1. Agent computes a complex state.
    2. State is stored in Semantic Cache.
    3. Agent encounters a 'functionally equivalent' state (slight variation).
    4. Semantic Cache returns the previously computed result.
    """
    embedding_provider = SimpleEmbeddingProvider()
    vector_store = InMemoryVectorStore(embedding_provider=embedding_provider)
    cache = SemanticStateCache(
        vector_store=vector_store,
        embedding_provider=embedding_provider,
        threshold=0.99,  # High threshold
    )

    # 1. Original state
    ctx1 = Context(data={"user_query": "What is the capital of France?", "context": "Geography"})
    await cache.set(ctx1)

    # 2. Functionally equivalent state (different key order or minor metadata)
    # Note: SimpleEmbeddingProvider uses key count and length.
    # We'll simulate a hit by using the same keys and similar length.
    ctx2 = Context(data={"context": "Geography", "user_query": "What is the capital of France?"})

    # 3. Cache lookup
    cached_ctx = await cache.get(ctx2)

    assert cached_ctx is not None
    assert cached_ctx.data["user_query"] == ctx1.data["user_query"]

    # 4. Different state (Miss)
    ctx3 = Context(data={"user_query": "Who won the world cup?", "context": "Sports"})
    miss_ctx = await cache.get(ctx3)
    assert miss_ctx is None

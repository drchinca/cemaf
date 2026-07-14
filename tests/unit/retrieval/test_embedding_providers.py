"""Tests for embedding provider implementations."""

import math

import pytest

from cemaf.retrieval.embedding_providers import HashEmbeddingProvider


class TestHashEmbeddingProvider:
    @pytest.fixture
    def provider(self) -> HashEmbeddingProvider:
        return HashEmbeddingProvider(dimension=128)

    @pytest.mark.asyncio
    async def test_deterministic_same_text(self, provider: HashEmbeddingProvider) -> None:
        """Same text always produces identical embeddings."""
        embedding_a = await provider.embed(text="hello world")
        embedding_b = await provider.embed(text="hello world")
        assert embedding_a == embedding_b

    @pytest.mark.asyncio
    async def test_different_texts_differ(self, provider: HashEmbeddingProvider) -> None:
        """Different texts produce different embeddings."""
        embedding_a = await provider.embed(text="hello world")
        embedding_b = await provider.embed(text="goodbye world")
        assert embedding_a != embedding_b

    @pytest.mark.asyncio
    async def test_correct_dimension(self, provider: HashEmbeddingProvider) -> None:
        """Output dimension matches configured dimension."""
        embedding = await provider.embed(text="test")
        assert len(embedding) == 128

    @pytest.mark.asyncio
    async def test_default_dimension(self) -> None:
        """Default dimension is 384."""
        provider = HashEmbeddingProvider()
        embedding = await provider.embed(text="test")
        assert len(embedding) == 384

    @pytest.mark.asyncio
    async def test_unit_vector(self, provider: HashEmbeddingProvider) -> None:
        """Embedding magnitude is approximately 1.0."""
        embedding = await provider.embed(text="normalize this")
        magnitude = math.sqrt(sum(v * v for v in embedding))
        assert abs(magnitude - 1.0) < 1e-6

    @pytest.mark.asyncio
    async def test_embed_batch(self, provider: HashEmbeddingProvider) -> None:
        """Batch produces correct number of results matching individual calls."""
        texts = ["alpha", "beta", "gamma"]
        batch_results = await provider.embed_batch(texts=texts)
        assert len(batch_results) == 3

        # Each batch result should match individual embed
        for text, batch_emb in zip(texts, batch_results, strict=True):
            individual = await provider.embed(text=text)
            assert batch_emb == individual

    @pytest.mark.asyncio
    async def test_values_in_range(self, provider: HashEmbeddingProvider) -> None:
        """All embedding values fall within [-1, 1]."""
        embedding = await provider.embed(text="range check")
        for val in embedding:
            assert -1.0 <= val <= 1.0

    def test_dimension_property(self, provider: HashEmbeddingProvider) -> None:
        """Dimension property returns configured value."""
        assert provider.dimension == 128

    def test_model_name_property(self, provider: HashEmbeddingProvider) -> None:
        """Model name identifies the provider."""
        assert provider.model_name == "hash-embedding"

    def test_rejects_non_positive_dimension(self) -> None:
        """Embedding providers must not create empty or negative-length vectors."""
        with pytest.raises(ValueError, match="dimension must be positive, got 0"):
            HashEmbeddingProvider(dimension=0)
        with pytest.raises(ValueError, match="dimension must be positive, got -1"):
            HashEmbeddingProvider(dimension=-1)

    @pytest.mark.asyncio
    async def test_empty_string(self, provider: HashEmbeddingProvider) -> None:
        """Empty string produces valid unit vector."""
        embedding = await provider.embed(text="")
        assert len(embedding) == 128
        magnitude = math.sqrt(sum(v * v for v in embedding))
        assert abs(magnitude - 1.0) < 1e-6

    @pytest.mark.asyncio
    async def test_conforms_to_protocol(self) -> None:
        """HashEmbeddingProvider satisfies EmbeddingProvider protocol."""
        from cemaf.retrieval.protocols import EmbeddingProvider

        provider = HashEmbeddingProvider()
        assert isinstance(provider, EmbeddingProvider)

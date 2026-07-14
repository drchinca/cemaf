"""Tests for OpenAI embedding provider."""

from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cemaf.retrieval.protocols import EmbeddingProvider


@pytest.fixture()
def mock_openai_module() -> MagicMock:
    """Create a mock openai module with AsyncOpenAI."""
    mock_module = MagicMock(spec=ModuleType)
    mock_client_cls = MagicMock()
    mock_module.AsyncOpenAI = mock_client_cls
    return mock_module


@pytest.fixture()
def mock_client() -> AsyncMock:
    """Create a mock AsyncOpenAI client with embeddings endpoint."""
    client = AsyncMock()
    return client


def _make_embedding_response(embeddings: list[list[float]]) -> MagicMock:
    """Build a mock OpenAI embeddings response."""
    data = []
    for emb in embeddings:
        obj = MagicMock()
        obj.embedding = emb
        data.append(obj)
    response = MagicMock()
    response.data = data
    return response


class TestConstructor:
    def test_rejects_non_positive_dimension_before_optional_import(self) -> None:
        """Constructor validation must not depend on the optional OpenAI package."""
        from cemaf.retrieval.openai_embeddings import OpenAIEmbeddingProvider

        with pytest.raises(ValueError, match="dimension must be positive, got 0"):
            OpenAIEmbeddingProvider(api_key="test-key", dimension=0)
        with pytest.raises(ValueError, match="dimension must be positive, got -1"):
            OpenAIEmbeddingProvider(api_key="test-key", dimension=-1)


class TestSatisfiesProtocol:
    def test_satisfies_protocol(self) -> None:
        """OpenAIEmbeddingProvider structurally satisfies EmbeddingProvider."""
        from cemaf.retrieval.openai_embeddings import OpenAIEmbeddingProvider

        provider = OpenAIEmbeddingProvider(api_key="test-key")
        assert isinstance(provider, EmbeddingProvider)


class TestEmbed:
    @pytest.mark.asyncio()
    async def test_embed_returns_correct_dimension(self, mock_client: AsyncMock) -> None:
        """embed() returns a tuple with the configured dimension."""
        from cemaf.retrieval.openai_embeddings import OpenAIEmbeddingProvider

        dimension = 256
        fake_vector = [0.1] * dimension
        mock_client.embeddings.create = AsyncMock(
            return_value=_make_embedding_response(embeddings=[fake_vector]),
        )

        with patch.object(OpenAIEmbeddingProvider, "__init__", lambda self, **kw: None):
            provider = OpenAIEmbeddingProvider(api_key="x")
            provider._client = mock_client
            provider._model = "text-embedding-3-small"
            provider._dimension = dimension

        result = await provider.embed(text="hello world")

        assert isinstance(result, tuple)
        assert len(result) == dimension
        mock_client.embeddings.create.assert_awaited_once_with(
            input=["hello world"],
            model="text-embedding-3-small",
            dimensions=dimension,
        )

    @pytest.mark.asyncio()
    async def test_embed_empty_text_returns_zero_vector(self) -> None:
        """embed() returns zero vector for empty/whitespace text."""
        from cemaf.retrieval.openai_embeddings import OpenAIEmbeddingProvider

        with patch.object(OpenAIEmbeddingProvider, "__init__", lambda self, **kw: None):
            provider = OpenAIEmbeddingProvider(api_key="x")
            provider._client = AsyncMock()
            provider._model = "text-embedding-3-small"
            provider._dimension = 8

        result = await provider.embed(text="   ")

        assert result == tuple(0.0 for _ in range(8))
        provider._client.embeddings.create.assert_not_awaited()

    @pytest.mark.asyncio()
    async def test_embed_raises_on_missing_embedding_response(self, mock_client: AsyncMock) -> None:
        """embed() fails loud when the provider omits the requested vector."""
        from cemaf.retrieval.openai_embeddings import OpenAIEmbeddingProvider

        mock_client.embeddings.create = AsyncMock(
            return_value=_make_embedding_response(embeddings=[]),
        )

        with patch.object(OpenAIEmbeddingProvider, "__init__", lambda self, **kw: None):
            provider = OpenAIEmbeddingProvider(api_key="x")
            provider._client = mock_client
            provider._model = "text-embedding-3-small"
            provider._dimension = 4

        with pytest.raises(ValueError, match="returned 0 vectors for 1 inputs"):
            await provider.embed(text="hello world")

    @pytest.mark.asyncio()
    async def test_embed_raises_on_dimension_mismatch(self, mock_client: AsyncMock) -> None:
        """embed() fails loud when provider vector dimension differs from configuration."""
        from cemaf.retrieval.openai_embeddings import OpenAIEmbeddingProvider

        mock_client.embeddings.create = AsyncMock(
            return_value=_make_embedding_response(embeddings=[[0.1, 0.2, 0.3]]),
        )

        with patch.object(OpenAIEmbeddingProvider, "__init__", lambda self, **kw: None):
            provider = OpenAIEmbeddingProvider(api_key="x")
            provider._client = mock_client
            provider._model = "text-embedding-3-small"
            provider._dimension = 4

        with pytest.raises(ValueError, match="has dimension 3; expected 4"):
            await provider.embed(text="hello world")


class TestEmbedBatch:
    @pytest.mark.asyncio()
    async def test_embed_batch_single_api_call(self, mock_client: AsyncMock) -> None:
        """embed_batch() sends all texts in one API call."""
        from cemaf.retrieval.openai_embeddings import OpenAIEmbeddingProvider

        dimension = 4
        texts = ["alpha", "beta", "gamma"]
        fake_vectors = [[float(i)] * dimension for i in range(len(texts))]
        mock_client.embeddings.create = AsyncMock(
            return_value=_make_embedding_response(embeddings=fake_vectors),
        )

        with patch.object(OpenAIEmbeddingProvider, "__init__", lambda self, **kw: None):
            provider = OpenAIEmbeddingProvider(api_key="x")
            provider._client = mock_client
            provider._model = "text-embedding-3-small"
            provider._dimension = dimension

        results = await provider.embed_batch(texts=texts)

        assert len(results) == 3
        assert all(len(v) == dimension for v in results)
        mock_client.embeddings.create.assert_awaited_once()

    @pytest.mark.asyncio()
    async def test_embed_batch_handles_empty_texts(self, mock_client: AsyncMock) -> None:
        """embed_batch() returns zero vectors for empty strings, real vectors for others."""
        from cemaf.retrieval.openai_embeddings import OpenAIEmbeddingProvider

        dimension = 4
        mock_client.embeddings.create = AsyncMock(
            return_value=_make_embedding_response(embeddings=[[1.0] * dimension]),
        )

        with patch.object(OpenAIEmbeddingProvider, "__init__", lambda self, **kw: None):
            provider = OpenAIEmbeddingProvider(api_key="x")
            provider._client = mock_client
            provider._model = "text-embedding-3-small"
            provider._dimension = dimension

        results = await provider.embed_batch(texts=["", "real text", "  "])

        assert len(results) == 3
        assert results[0] == tuple(0.0 for _ in range(dimension))
        assert results[1] == tuple(1.0 for _ in range(dimension))
        assert results[2] == tuple(0.0 for _ in range(dimension))
        # Only the non-empty text sent to API
        mock_client.embeddings.create.assert_awaited_once_with(
            input=["real text"],
            model="text-embedding-3-small",
            dimensions=dimension,
        )

    @pytest.mark.asyncio()
    async def test_embed_batch_empty_list(self) -> None:
        """embed_batch() with empty list returns empty list without API call."""
        from cemaf.retrieval.openai_embeddings import OpenAIEmbeddingProvider

        with patch.object(OpenAIEmbeddingProvider, "__init__", lambda self, **kw: None):
            provider = OpenAIEmbeddingProvider(api_key="x")
            provider._client = AsyncMock()
            provider._model = "text-embedding-3-small"
            provider._dimension = 4

        results = await provider.embed_batch(texts=[])

        assert results == []
        provider._client.embeddings.create.assert_not_awaited()

    @pytest.mark.asyncio()
    async def test_embed_batch_raises_on_response_count_mismatch(self, mock_client: AsyncMock) -> None:
        """embed_batch() fails loud instead of zero-filling missing provider vectors."""
        from cemaf.retrieval.openai_embeddings import OpenAIEmbeddingProvider

        dimension = 4
        mock_client.embeddings.create = AsyncMock(
            return_value=_make_embedding_response(embeddings=[[1.0] * dimension]),
        )

        with patch.object(OpenAIEmbeddingProvider, "__init__", lambda self, **kw: None):
            provider = OpenAIEmbeddingProvider(api_key="x")
            provider._client = mock_client
            provider._model = "text-embedding-3-small"
            provider._dimension = dimension

        with pytest.raises(ValueError, match="returned 1 vectors for 2 inputs"):
            await provider.embed_batch(texts=["alpha", "beta"])

    @pytest.mark.asyncio()
    async def test_embed_batch_raises_on_dimension_mismatch(self, mock_client: AsyncMock) -> None:
        """embed_batch() validates every returned vector dimension."""
        from cemaf.retrieval.openai_embeddings import OpenAIEmbeddingProvider

        mock_client.embeddings.create = AsyncMock(
            return_value=_make_embedding_response(embeddings=[[1.0] * 4, [2.0] * 3]),
        )

        with patch.object(OpenAIEmbeddingProvider, "__init__", lambda self, **kw: None):
            provider = OpenAIEmbeddingProvider(api_key="x")
            provider._client = mock_client
            provider._model = "text-embedding-3-small"
            provider._dimension = 4

        with pytest.raises(ValueError, match="item 1 has dimension 3; expected 4"):
            await provider.embed_batch(texts=["alpha", "beta"])


class TestMissingPackage:
    def test_missing_package_raises(self) -> None:
        """ImportError raised with install instructions when openai not available."""
        # Temporarily hide the openai module
        hidden = sys.modules.pop("openai", None)
        # Also clear cached import of the provider module
        sys.modules.pop("cemaf.retrieval.openai_embeddings", None)

        try:
            with patch.dict(sys.modules, {"openai": None}):
                # Force re-import
                sys.modules.pop("cemaf.retrieval.openai_embeddings", None)
                from cemaf.retrieval.openai_embeddings import OpenAIEmbeddingProvider

                with pytest.raises(ImportError, match="uv add openai"):
                    OpenAIEmbeddingProvider(api_key="test-key")
        finally:
            if hidden is not None:
                sys.modules["openai"] = hidden
            # Re-import to restore normal state
            sys.modules.pop("cemaf.retrieval.openai_embeddings", None)

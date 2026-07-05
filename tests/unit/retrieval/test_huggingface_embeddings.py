"""Tests for Hugging Face embedding provider."""

from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cemaf.config.protocols import RetrievalSettings, Settings
from cemaf.retrieval.protocols import EmbeddingProvider


@pytest.fixture
def fake_hf_module() -> ModuleType:
    module = ModuleType("huggingface_hub")
    module.AsyncInferenceClient = MagicMock(name="AsyncInferenceClient")
    return module


class TestImportError:
    def test_missing_package_raises(self) -> None:
        sys.modules.pop("cemaf.retrieval.huggingface_embeddings", None)
        with (
            patch.dict("sys.modules", {"huggingface_hub": None}),
            pytest.raises(ImportError, match="huggingface_hub"),
        ):
            from cemaf.retrieval.huggingface_embeddings import HuggingFaceEmbeddingProvider

            HuggingFaceEmbeddingProvider()


class TestProvider:
    def test_rejects_non_positive_dimension_before_optional_import(self) -> None:
        sys.modules.pop("cemaf.retrieval.huggingface_embeddings", None)

        with patch.dict("sys.modules", {"huggingface_hub": None}):
            from cemaf.retrieval.huggingface_embeddings import HuggingFaceEmbeddingProvider

            with pytest.raises(ValueError, match="dimension must be positive, got 0"):
                HuggingFaceEmbeddingProvider(api_key="hf-test", dimension=0)
            with pytest.raises(ValueError, match="dimension must be positive, got -1"):
                HuggingFaceEmbeddingProvider(api_key="hf-test", dimension=-1)

    def test_satisfies_protocol(self, fake_hf_module: ModuleType) -> None:
        sys.modules.pop("cemaf.retrieval.huggingface_embeddings", None)

        with patch.dict("sys.modules", {"huggingface_hub": fake_hf_module}):
            from cemaf.retrieval.huggingface_embeddings import HuggingFaceEmbeddingProvider

            fake_hf_module.AsyncInferenceClient.return_value = AsyncMock()
            provider = HuggingFaceEmbeddingProvider(api_key="hf-test", dimension=3)

        assert isinstance(provider, EmbeddingProvider)

    @pytest.mark.asyncio()
    async def test_embed_returns_vector(self, fake_hf_module: ModuleType) -> None:
        sys.modules.pop("cemaf.retrieval.huggingface_embeddings", None)

        with patch.dict("sys.modules", {"huggingface_hub": fake_hf_module}):
            from cemaf.retrieval.huggingface_embeddings import HuggingFaceEmbeddingProvider

            client = AsyncMock()
            client.feature_extraction = AsyncMock(return_value=[0.1, 0.2, 0.3])
            fake_hf_module.AsyncInferenceClient.return_value = client

            provider = HuggingFaceEmbeddingProvider(api_key="hf-test", dimension=3)
            result = await provider.embed("hello world")

        assert result == (0.1, 0.2, 0.3)
        client.feature_extraction.assert_awaited_once_with(
            "hello world",
            model=provider.model_name,
        )

    @pytest.mark.asyncio()
    async def test_embed_rejects_response_dimension_mismatch(self, fake_hf_module: ModuleType) -> None:
        sys.modules.pop("cemaf.retrieval.huggingface_embeddings", None)

        with patch.dict("sys.modules", {"huggingface_hub": fake_hf_module}):
            from cemaf.retrieval.huggingface_embeddings import HuggingFaceEmbeddingProvider

            client = AsyncMock()
            client.feature_extraction = AsyncMock(return_value=[0.1, 0.2, 0.3])
            fake_hf_module.AsyncInferenceClient.return_value = client

            provider = HuggingFaceEmbeddingProvider(api_key="hf-test", dimension=4)
            with pytest.raises(
                ValueError,
                match="Hugging Face embedding response has dimension 3; expected 4",
            ):
                await provider.embed("hello world")

        assert provider.dimension == 4

    @pytest.mark.asyncio()
    async def test_embed_pools_token_level_matrix(self, fake_hf_module: ModuleType) -> None:
        sys.modules.pop("cemaf.retrieval.huggingface_embeddings", None)

        with patch.dict("sys.modules", {"huggingface_hub": fake_hf_module}):
            from cemaf.retrieval.huggingface_embeddings import HuggingFaceEmbeddingProvider

            client = AsyncMock()
            client.feature_extraction = AsyncMock(return_value=[[1.0, 3.0], [5.0, 7.0]])
            fake_hf_module.AsyncInferenceClient.return_value = client

            provider = HuggingFaceEmbeddingProvider(api_key="hf-test", dimension=2)
            result = await provider.embed("pool me")

        assert result == (3.0, 5.0)

    @pytest.mark.asyncio()
    async def test_embed_empty_text_returns_zero_vector(self, fake_hf_module: ModuleType) -> None:
        sys.modules.pop("cemaf.retrieval.huggingface_embeddings", None)

        with patch.dict("sys.modules", {"huggingface_hub": fake_hf_module}):
            from cemaf.retrieval.huggingface_embeddings import HuggingFaceEmbeddingProvider

            client = AsyncMock()
            fake_hf_module.AsyncInferenceClient.return_value = client

            provider = HuggingFaceEmbeddingProvider(api_key="hf-test", dimension=4)
            result = await provider.embed("   ")

        assert result == (0.0, 0.0, 0.0, 0.0)
        client.feature_extraction.assert_not_awaited()

    @pytest.mark.asyncio()
    async def test_embed_batch_reuses_single_embed_path(self, fake_hf_module: ModuleType) -> None:
        sys.modules.pop("cemaf.retrieval.huggingface_embeddings", None)

        with patch.dict("sys.modules", {"huggingface_hub": fake_hf_module}):
            from cemaf.retrieval.huggingface_embeddings import HuggingFaceEmbeddingProvider

            client = AsyncMock()
            client.feature_extraction = AsyncMock(
                side_effect=[
                    [1.0, 0.0, 0.0],
                    [0.0, 1.0, 0.0],
                ]
            )
            fake_hf_module.AsyncInferenceClient.return_value = client

            provider = HuggingFaceEmbeddingProvider(api_key="hf-test", dimension=3)
            results = await provider.embed_batch(["alpha", "", "beta"])

        assert results == [
            (1.0, 0.0, 0.0),
            (0.0, 0.0, 0.0),
            (0.0, 1.0, 0.0),
        ]
        assert client.feature_extraction.await_count == 2


class TestFactories:
    def test_create_embedding_provider_from_config_maps_hf_defaults(
        self,
        fake_hf_module: ModuleType,
    ) -> None:
        sys.modules.pop("cemaf.retrieval.huggingface_embeddings", None)

        with patch.dict("sys.modules", {"huggingface_hub": fake_hf_module}):
            from cemaf.retrieval.factories import create_embedding_provider_from_config
            from cemaf.retrieval.huggingface_embeddings import (
                DEFAULT_HF_EMBEDDING_DIMENSION,
                DEFAULT_HF_EMBEDDING_MODEL,
            )

            fake_hf_module.AsyncInferenceClient.return_value = AsyncMock()
            settings = Settings(
                retrieval=RetrievalSettings(
                    embedding_provider="huggingface",
                    embedding_model="text-embedding-3-small",
                    embedding_dimension=1536,
                )
            )

            provider = create_embedding_provider_from_config(settings=settings)

        assert provider.model_name == DEFAULT_HF_EMBEDDING_MODEL
        assert provider.dimension == DEFAULT_HF_EMBEDDING_DIMENSION

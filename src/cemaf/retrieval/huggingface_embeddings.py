"""Hugging Face embedding provider for Hub-hosted embedding models."""

from __future__ import annotations

import os
from typing import Any

DEFAULT_HF_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_HF_EMBEDDING_DIMENSION = 384


class HuggingFaceEmbeddingProvider:
    """Embedding provider backed by Hugging Face Inference Providers."""

    def __init__(
        self,
        *,
        api_key: str = "",
        model: str = DEFAULT_HF_EMBEDDING_MODEL,
        dimension: int = DEFAULT_HF_EMBEDDING_DIMENSION,
        provider: str = "hf-inference",
        timeout_seconds: float = 60.0,
    ) -> None:
        try:
            from huggingface_hub import AsyncInferenceClient
        except ImportError as exc:
            raise ImportError(
                "huggingface_hub package is required for HuggingFaceEmbeddingProvider. "
                "Install it with: uv add huggingface_hub"
            ) from exc

        token = (
            api_key
            or os.getenv("HF_TOKEN")
            or os.getenv("HUGGINGFACE_API_KEY")
            or os.getenv("HUGGINGFACEHUB_API_TOKEN", "")
        )
        client_kwargs: dict[str, Any] = {
            "model": model,
            "timeout": timeout_seconds,
        }
        if provider:
            client_kwargs["provider"] = provider
        if token:
            client_kwargs["api_key"] = token

        self._client = AsyncInferenceClient(**client_kwargs)
        self._model = model
        self._dimension = dimension
        self._provider = provider

    @property
    def dimension(self) -> int:
        """Embedding vector dimension."""

        return self._dimension

    @property
    def model_name(self) -> str:
        """Embedding model identifier."""

        return self._model

    async def embed(self, text: str) -> tuple[float, ...]:
        """Generate an embedding for one input string."""

        if not text.strip():
            return tuple(0.0 for _ in range(self._dimension))

        response = await self._client.feature_extraction(text, model=self._model)
        vector = _coerce_embedding_vector(response)
        if len(vector) != self._dimension:
            self._dimension = len(vector)
        return vector

    async def embed_batch(self, texts: list[str]) -> list[tuple[float, ...]]:
        """Generate embeddings for multiple texts."""

        return [await self.embed(text=text) for text in texts]


def _coerce_embedding_vector(value: object) -> tuple[float, ...]:
    """Normalize HF feature-extraction payloads into one vector."""

    if hasattr(value, "tolist"):
        value = value.tolist()

    if isinstance(value, (list, tuple)):
        if not value:
            return ()

        first = value[0]
        if isinstance(first, (int, float)):
            return tuple(float(item) for item in value)

        if isinstance(first, (list, tuple)):
            rows = [_coerce_numeric_row(row) for row in value]
            if len(rows) == 1:
                return rows[0]

            width = len(rows[0])
            if any(len(row) != width for row in rows):
                raise ValueError("Hugging Face embedding response has inconsistent row widths")

            return tuple(sum(row[index] for row in rows) / len(rows) for index in range(width))

    raise ValueError(
        "Unsupported Hugging Face embedding payload shape. Expected a vector or matrix of numeric values."
    )


def _coerce_numeric_row(value: object) -> tuple[float, ...]:
    if not isinstance(value, (list, tuple)):
        raise ValueError("Embedding row must be a sequence of numeric values")
    return tuple(float(item) for item in value)

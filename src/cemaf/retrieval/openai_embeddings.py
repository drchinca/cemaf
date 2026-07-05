"""OpenAI embedding provider for production vector search."""

from __future__ import annotations

from typing import Any

from cemaf.retrieval.embedding_validation import require_positive_dimension


class OpenAIEmbeddingProvider:
    """Embedding provider backed by OpenAI text-embedding API."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "text-embedding-3-small",
        dimension: int = 1536,
    ) -> None:
        self._dimension = require_positive_dimension(dimension)

        try:
            from openai import AsyncOpenAI
        except ImportError as exc:
            raise ImportError(
                "openai package is required for OpenAIEmbeddingProvider. Install it with: uv add openai"
            ) from exc

        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model

    @property
    def dimension(self) -> int:
        """Embedding vector dimension."""
        return self._dimension

    @property
    def model_name(self) -> str:
        """OpenAI model identifier."""
        return self._model

    async def embed(self, text: str) -> tuple[float, ...]:
        """Generate embedding for a single text."""
        if not text.strip():
            return tuple(0.0 for _ in range(self._dimension))

        response = await self._client.embeddings.create(
            input=[text],
            model=self._model,
            dimensions=self._dimension,
        )
        return _extract_embedding_vectors(
            response=response,
            expected_count=1,
            dimension=self._dimension,
        )[0]

    async def embed_batch(self, texts: list[str]) -> list[tuple[float, ...]]:
        """Generate embeddings for multiple texts in a single API call."""
        if not texts:
            return []

        zero_vector = tuple(0.0 for _ in range(self._dimension))
        non_empty_indices: list[int] = []
        non_empty_texts: list[str] = []

        for i, text in enumerate(texts):
            if text.strip():
                non_empty_indices.append(i)
                non_empty_texts.append(text)

        if not non_empty_texts:
            return [zero_vector for _ in texts]

        response = await self._client.embeddings.create(
            input=non_empty_texts,
            model=self._model,
            dimensions=self._dimension,
        )
        embeddings = _extract_embedding_vectors(
            response=response,
            expected_count=len(non_empty_texts),
            dimension=self._dimension,
        )

        results: list[tuple[float, ...]] = [zero_vector] * len(texts)
        for idx, embedding in zip(non_empty_indices, embeddings, strict=True):
            results[idx] = embedding

        return results


def _extract_embedding_vectors(
    *,
    response: Any,
    expected_count: int,
    dimension: int,
) -> list[tuple[float, ...]]:
    """Extract and validate OpenAI embedding vectors."""
    data = list(getattr(response, "data", []) or [])
    if len(data) != expected_count:
        raise ValueError(
            f"OpenAI embedding response returned {len(data)} vectors for {expected_count} inputs"
        )

    vectors: list[tuple[float, ...]] = []
    for index, item in enumerate(data):
        raw_embedding = getattr(item, "embedding", None)
        if raw_embedding is None:
            raise ValueError(f"OpenAI embedding response item {index} is missing 'embedding'")
        try:
            vector = tuple(float(value) for value in raw_embedding)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"OpenAI embedding response item {index} is not a numeric vector") from exc
        if len(vector) != dimension:
            raise ValueError(
                f"OpenAI embedding response item {index} has dimension {len(vector)}; expected {dimension}"
            )
        vectors.append(vector)
    return vectors

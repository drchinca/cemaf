"""OpenAI embedding provider for production vector search."""

from __future__ import annotations


class OpenAIEmbeddingProvider:
    """Embedding provider backed by OpenAI text-embedding API."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "text-embedding-3-small",
        dimension: int = 1536,
    ) -> None:
        try:
            from openai import AsyncOpenAI
        except ImportError as exc:
            raise ImportError(
                "openai package is required for OpenAIEmbeddingProvider. Install it with: uv add openai"
            ) from exc

        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model
        self._dimension = dimension

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
        return tuple(response.data[0].embedding)

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

        results: list[tuple[float, ...]] = [zero_vector] * len(texts)
        for idx, embedding_obj in zip(non_empty_indices, response.data, strict=False):
            results[idx] = tuple(embedding_obj.embedding)

        return results

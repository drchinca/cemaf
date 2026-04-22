"""Embedding provider implementations."""

import hashlib
import math
import struct


class HashEmbeddingProvider:
    """Deterministic embedding provider using content hashing for testing and development."""

    def __init__(self, *, dimension: int = 384) -> None:
        self._dimension = dimension
        self._model_name = "hash-embedding"

    @property
    def dimension(self) -> int:
        """Embedding vector dimension."""
        return self._dimension

    @property
    def model_name(self) -> str:
        """Model identifier."""
        return self._model_name

    async def embed(self, text: str) -> tuple[float, ...]:
        """Generate deterministic embedding from text content hash."""
        hash_bytes = hashlib.sha256(text.encode()).digest()
        needed_bytes = self._dimension * 4
        expanded = (hash_bytes * (needed_bytes // len(hash_bytes) + 1))[:needed_bytes]

        floats: list[float] = []
        for i in range(self._dimension):
            raw = struct.unpack_from(">I", expanded, offset=i * 4)[0]
            # Map unsigned 32-bit int to [-1, 1]
            floats.append((raw / 2_147_483_647.5) - 1.0)

        # Normalize to unit vector
        magnitude = math.sqrt(sum(f * f for f in floats))
        if magnitude > 0:
            floats = [f / magnitude for f in floats]

        return tuple(floats)

    async def embed_batch(self, texts: list[str]) -> list[tuple[float, ...]]:
        """Generate embeddings for multiple texts."""
        return [await self.embed(text=t) for t in texts]

"""
Semantic State Caching - Intelligence over exact-match hashing.
"""

import json
import uuid
from datetime import datetime, timedelta

from cemaf.context.context import Context
from cemaf.core.utils import utc_now
from cemaf.retrieval.protocols import Document, EmbeddingProvider, VectorStore


class SemanticStateCache:
    """
    Caches context states based on semantic similarity of their content.
    Uses vector embeddings to identify functionally equivalent states.

    Includes lifecycle management: TTL expiration and LRU eviction.
    """

    def __init__(
        self,
        vector_store: VectorStore,
        embedding_provider: EmbeddingProvider,
        threshold: float = 0.98,
        cache_ttl: int | None = 3600,
        max_cache_size: int | None = 100_000,
    ) -> None:
        """
        Initialize the semantic cache with lifecycle management.

        Args:
            vector_store: Store for state embeddings
            embedding_provider: Provider to generate embeddings
            threshold: Similarity threshold (0.0 to 1.0) for a cache hit
            cache_ttl: Time-to-live in seconds (None = no expiration)
            max_cache_size: Maximum cache entries (None = unlimited)
        """
        self.vector_store = vector_store
        self.embedding_provider = embedding_provider
        self.threshold = threshold
        self.cache_ttl = cache_ttl
        self.max_cache_size = max_cache_size
        # Local cache: key -> (context, created_at)
        self._cache_entries: dict[str, tuple[Context, datetime]] = {}

    async def get(self, context: Context) -> Context | None:
        """
        Try to find a semantically similar context state in the cache.

        Checks local cache first, then vector store.
        Enforces TTL expiration.

        Args:
            context: The context to look up

        Returns:
            Context | None: The cached context if found and not expired
        """
        # Convert context data to a stable string representation
        state_str = json.dumps(context.data, sort_keys=True)
        cache_key = self._make_cache_key(state_str)

        # Check local cache first (with TTL expiration)
        if cache_key in self._cache_entries:
            cached_context, created_at = self._cache_entries[cache_key]

            # Check if expired
            if self.cache_ttl is not None:
                age = utc_now() - created_at
                if age > timedelta(seconds=self.cache_ttl):
                    # Expired - remove and return None
                    del self._cache_entries[cache_key]
                    return None

            # Not expired - return cached context (preserves patch history)
            return cached_context

        # If not in local cache, try vector store (for distributed scenarios)
        embedding = await self.embedding_provider.embed(state_str)
        results = await self.vector_store.search(embedding, k=1)

        if results and results[0].score >= self.threshold:
            # Cache hit! Reconstruct context from the stored content
            # NOTE: Vector store hits don't have patch history
            # (semantic caching implies functional equivalence, not identity)
            cached_data = json.loads(results[0].content)
            return Context(data=cached_data)

        return None

    async def set(self, context: Context) -> None:
        """
        Store a context state in the semantic cache.

        Enforces size limits with LRU eviction.

        Args:
            context: The context to cache
        """
        state_str = json.dumps(context.data, sort_keys=True)
        cache_key = self._make_cache_key(state_str)

        # Store in local cache (preserves full Context with patch history)
        self._cache_entries[cache_key] = (context, utc_now())

        # Enforce size limit (LRU eviction)
        if self.max_cache_size is not None and len(self._cache_entries) > self.max_cache_size:
            # Find oldest entry
            oldest_key = min(
                self._cache_entries.keys(),
                key=lambda k: self._cache_entries[k][1],
            )
            del self._cache_entries[oldest_key]

        # Also store in vector store for semantic search
        embedding = await self.embedding_provider.embed(state_str)

        doc = Document(
            id=str(uuid.uuid4()),
            content=state_str,
            embedding=embedding,
            metadata={
                "type": "context_state",
                "state_hash": context.state_hash(),
            },
        )

        await self.vector_store.add(doc)

    @staticmethod
    def _make_cache_key(state_str: str) -> str:
        """Create a deterministic cache key from state string."""
        import hashlib

        return hashlib.sha256(state_str.encode()).hexdigest()

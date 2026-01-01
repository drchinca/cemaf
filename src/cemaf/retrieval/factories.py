"""
Factory functions for retrieval components.

Provides convenient ways to create retrieval components
with sensible defaults while maintaining dependency injection principles.

Extension Point:
    This module is designed for extension. The create_vector_store_from_config()
    function includes a clear "EXTEND HERE" section where you can add your own
    vector store implementations. CEMAF provides the protocol; you bring your
    own implementation (BYOI - Bring Your Own Implementation).

    See create_vector_store_from_config() for detailed extension instructions.
"""

from cemaf.config.factories import load_settings_from_env_sync
from cemaf.config.protocols import Settings
from cemaf.retrieval.memory_store import InMemoryVectorStore, MockEmbeddingProvider
from cemaf.retrieval.protocols import EmbeddingProvider, VectorStore


def create_in_memory_vector_store(
    embedding_provider: EmbeddingProvider | None = None,
    dimension: int = 384,
) -> InMemoryVectorStore:
    """
    Factory for InMemoryVectorStore with sensible defaults.

    Args:
        embedding_provider: Custom embedding provider (optional)
        dimension: Embedding dimension for default mock provider

    Returns:
        Configured InMemoryVectorStore instance

    Example:
        # With defaults (mock embeddings for testing)
        store = create_in_memory_vector_store()

        # With custom embedding provider
        from cemaf.retrieval.openai_embeddings import OpenAIEmbeddingProvider

        provider = OpenAIEmbeddingProvider(api_key="...")
        store = create_in_memory_vector_store(embedding_provider=provider)
    """
    provider = embedding_provider or MockEmbeddingProvider(dimension=dimension)
    return InMemoryVectorStore(provider)


def create_vector_store_from_config(
    backend: str | None = None,
    embedding_provider: EmbeddingProvider | None = None,
    settings: Settings | None = None,
) -> VectorStore:
    """
    Create a vector store from configuration.

    Reads from Settings (which loads from environment variables):
    - CEMAF_RETRIEVAL_VECTOR_STORE_BACKEND: Backend type (default: "memory")
    - CEMAF_RETRIEVAL_EMBEDDING_PROVIDER: Embedding provider (default: "openai")
    - CEMAF_RETRIEVAL_EMBEDDING_MODEL: Embedding model name
    - CEMAF_RETRIEVAL_EMBEDDING_DIMENSION: Embedding dimension

    Args:
        backend: Vector store backend type (overrides settings)
        embedding_provider: Custom embedding provider (optional)
        settings: Settings instance (loads from env if None)

    Returns:
        Configured VectorStore instance

    Example:
        # From environment variables (via Settings)
        store = create_vector_store_from_config()

        # Explicit backend
        store = create_vector_store_from_config(backend="memory")

        # With custom embedding provider
        from cemaf.retrieval.openai_embeddings import OpenAIEmbeddingProvider
        provider = OpenAIEmbeddingProvider(api_key="...")
        store = create_vector_store_from_config(embedding_provider=provider)

        # With explicit settings
        settings = Settings(...)
        store = create_vector_store_from_config(settings=settings)

    Extension Point:
        This is where you can extend CEMAF with your own vector store implementations.
        See the "EXTEND HERE" section below for instructions.
    """
    # Get settings from parameter or environment
    cfg = settings or load_settings_from_env_sync()  # noqa: F841

    # Get backend from parameter or settings
    backend = backend or cfg.retrieval.vector_store_backend

    # ============================================================================
    # BUILT-IN IMPLEMENTATIONS
    # ============================================================================
    if backend == "memory":
        return create_in_memory_vector_store(
            embedding_provider=embedding_provider,
            dimension=cfg.retrieval.embedding_dimension,
        )

    # ============================================================================
    # EXTEND HERE: Bring Your Own Vector Store Implementation
    # ============================================================================
    # This is the extension point for custom vector store backends.
    #
    # To add your own implementation:
    # 1. Implement the VectorStore protocol (see cemaf.retrieval.protocols.VectorStore)
    # 2. Add your backend case below
    # 3. Read configuration from environment variables or pass as parameters
    #
    # Example:
    #   elif backend == "pinecone":
    #       from your_package import PineconeVectorStore
    #       api_key = os.getenv("PINECONE_API_KEY")
    #       index_name = os.getenv("PINECONE_INDEX_NAME", "cemaf-index")
    #       return PineconeVectorStore(api_key=api_key, index_name=index_name)
    #
    #   elif backend == "my_custom_store":
    #       from my_package.vector_stores import MyCustomVectorStore
    #       config = {
    #           "url": os.getenv("MY_STORE_URL"),
    #           "api_key": os.getenv("MY_STORE_API_KEY"),
    #       }
    #       return MyCustomVectorStore(**config)
    #
    # Your implementation must conform to the VectorStore protocol:
    #   - async def add(document: Document) -> None
    #   - async def search(query_embedding: tuple[float, ...], k: int = 10) -> list[SearchResult]
    #   - async def get(document_id: str) -> Document | None
    #   - async def delete(document_id: str) -> bool
    #   - async def count() -> int
    #   - async def clear() -> None
    #   - async def search_by_text(query_text: str, k: int = 10) -> list[SearchResult]
    #
    # See: cemaf/src/cemaf/retrieval/protocols.py for the full protocol definition
    # ============================================================================

    # ============================================================================
    # PLACEHOLDER: Common Vector Store Backends
    # ============================================================================
    # Uncomment and implement these as needed, or add your own:
    #
    # elif backend == "pinecone":
    #     # TODO: Implement PineconeVectorStore
    #     # from cemaf.retrieval.pinecone_store import PineconeVectorStore
    #     # api_key = os.getenv("PINECONE_API_KEY")
    #     # environment = os.getenv("PINECONE_ENVIRONMENT", "us-east-1")
    #     # index_name = os.getenv("PINECONE_INDEX_NAME", "cemaf-index")
    #     # return PineconeVectorStore(api_key=api_key, environment=environment, index_name=index_name)
    #     pass
    #
    # elif backend == "qdrant":
    #     # TODO: Implement QdrantVectorStore
    #     # from cemaf.retrieval.qdrant_store import QdrantVectorStore
    #     # url = os.getenv("QDRANT_URL", "http://localhost:6333")
    #     # api_key = os.getenv("QDRANT_API_KEY")
    #     # collection_name = os.getenv("QDRANT_COLLECTION_NAME", "cemaf")
    #     # return QdrantVectorStore(url=url, api_key=api_key, collection_name=collection_name)
    #     pass
    #
    # elif backend == "weaviate":
    #     # TODO: Implement WeaviateVectorStore
    #     # from cemaf.retrieval.weaviate_store import WeaviateVectorStore
    #     # url = os.getenv("WEAVIATE_URL", "http://localhost:8080")
    #     # api_key = os.getenv("WEAVIATE_API_KEY")
    #     # class_name = os.getenv("WEAVIATE_CLASS_NAME", "Document")
    #     # return WeaviateVectorStore(url=url, api_key=api_key, class_name=class_name)
    #     pass
    #
    # elif backend == "chroma":
    #     # TODO: Implement ChromaVectorStore
    #     # from cemaf.retrieval.chroma_store import ChromaVectorStore
    #     # persist_directory = os.getenv("CHROMA_PERSIST_DIRECTORY", "./data/chroma")
    #     # collection_name = os.getenv("CHROMA_COLLECTION_NAME", "cemaf")
    #     # return ChromaVectorStore(persist_directory=persist_directory, collection_name=collection_name)
    #     pass
    #
    # elif backend == "pgvector":
    #     # TODO: Implement PGVectorStore
    #     # from cemaf.retrieval.pgvector_store import PGVectorStore
    #     # connection_string = os.getenv("PGVECTOR_CONNECTION_STRING")
    #     # table_name = os.getenv("PGVECTOR_TABLE_NAME", "embeddings")
    #     # return PGVectorStore(connection_string=connection_string, table_name=table_name)
    #     pass
    #
    # elif backend == "faiss":
    #     # TODO: Implement FAISSVectorStore
    #     # from cemaf.retrieval.faiss_store import FAISSVectorStore
    #     # index_path = os.getenv("FAISS_INDEX_PATH", "./data/faiss.index")
    #     # return FAISSVectorStore(index_path=index_path, embedding_provider=embedding_provider)
    #     pass
    # ============================================================================

    raise ValueError(
        f"Unsupported vector store backend: {backend}. "
        f"Supported backends: memory, pinecone, qdrant, weaviate, chroma, pgvector, faiss. "
        f"To add your own implementation, extend create_vector_store_from_config() "
        f"in cemaf/retrieval/factories.py (see 'EXTEND HERE' section)"
    )

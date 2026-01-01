"""
Factory functions for memory store components.

Provides convenient ways to create memory stores with sensible defaults
while maintaining dependency injection principles.

Extension Point:
    This module is designed for extension. The create_memory_store_from_config()
    function includes a clear "EXTEND HERE" section where you can add
    your own memory backend implementations (Redis, PostgreSQL, DynamoDB, etc.).
"""

import os

from cemaf.config.protocols import Settings
from cemaf.memory.base import InMemoryStore
from cemaf.memory.protocols import MemoryStore


def create_memory_store(
    backend: str = "memory",
    max_items: int = 10000,
    default_ttl_seconds: float = 3600.0,
) -> MemoryStore:
    """
    Factory for MemoryStore with sensible defaults.

    Args:
        backend: Memory store backend (memory, redis, postgres, etc.)
        max_items: Maximum memory items to store
        default_ttl_seconds: Default TTL for memory items

    Returns:
        Configured MemoryStore instance

    Example:
        # In-memory store
        store = create_memory_store()

        # With custom limits
        store = create_memory_store(max_items=5000, default_ttl_seconds=7200.0)
    """
    if backend == "memory":
        return InMemoryStore(
            max_items=max_items,
            default_ttl_seconds=default_ttl_seconds,
        )
    else:
        raise ValueError(f"Unsupported memory backend: {backend}")


def create_memory_store_from_config(settings: Settings | None = None) -> MemoryStore:
    """
    Create MemoryStore from environment configuration.

    Reads from environment variables:
    - CEMAF_MEMORY_BACKEND: Backend type (default: "memory")
    - CEMAF_MEMORY_MAX_ITEMS: Max items in store (default: 10000)
    - CEMAF_MEMORY_DEFAULT_TTL_SECONDS: Default TTL (default: 3600.0)
    - CEMAF_MEMORY_CLEANUP_INTERVAL_SECONDS: Cleanup interval (default: 300.0)

    Returns:
        Configured MemoryStore instance

    Example:
        # From environment
        store = create_memory_store_from_config()
    """
    backend = os.getenv("CEMAF_MEMORY_BACKEND", "memory")
    max_items = int(os.getenv("CEMAF_MEMORY_MAX_ITEMS", "10000"))
    default_ttl = float(os.getenv("CEMAF_MEMORY_DEFAULT_TTL_SECONDS", "3600.0"))

    # BUILT-IN IMPLEMENTATIONS
    if backend == "memory":
        return create_memory_store(
            backend=backend,
            max_items=max_items,
            default_ttl_seconds=default_ttl,
        )

    # ============================================================================
    # EXTEND HERE: Bring Your Own Memory Backend
    # ============================================================================
    # This is the extension point for custom memory backends.
    #
    # To add your own implementation:
    # 1. Implement the MemoryStore protocol (see cemaf.memory.protocols)
    # 2. Add your backend case below
    # 3. Read configuration from environment variables
    #
    # Example (Redis):
    #   elif backend == "redis":
    #       from your_package import RedisMemoryStore
    #
    #       redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    #       return RedisMemoryStore(
    #           url=redis_url,
    #           max_items=max_items,
    #           default_ttl_seconds=default_ttl,
    #       )
    #
    # Example (PostgreSQL):
    #   elif backend == "postgres":
    #       from your_package import PostgresMemoryStore
    #
    #       db_url = os.getenv("DATABASE_URL")
    #       return PostgresMemoryStore(
    #           connection_string=db_url,
    #           table_name="cemaf_memory",
    #       )
    #
    # Example (DynamoDB):
    #   elif backend == "dynamodb":
    #       from your_package import DynamoDBMemoryStore
    #
    #       table_name = os.getenv("DYNAMODB_MEMORY_TABLE", "cemaf_memory")
    #       region = os.getenv("AWS_REGION", "us-east-1")
    #
    #       return DynamoDBMemoryStore(
    #           table_name=table_name,
    #           region=region,
    #       )
    # ============================================================================

    raise ValueError(
        f"Unsupported memory backend: {backend}. "
        f"Supported: memory. "
        f"To add your own, extend create_memory_store_from_config() "
        f"in cemaf/memory/factories.py"
    )

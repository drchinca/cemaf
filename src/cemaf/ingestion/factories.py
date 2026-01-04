"""
Factory functions for context ingestion.

DI-friendly factories that accept explicit dependencies for testing
while providing sensible defaults for production.
"""

import os
from dataclasses import dataclass, field
from typing import Any

from cemaf.ingestion.adapters import (
    ChunkAdapter,
    JSONAdapter,
    TableAdapter,
    TextAdapter,
)
from cemaf.ingestion.protocols import ContextAdapter


@dataclass
class AdapterConfig:
    """Configuration for context adapters."""

    adapter_type: str = "text"
    max_tokens: int = 2000
    chars_per_token: float = 4.0
    truncation_strategy: str = "tail"
    chunk_size: int = 500
    chunk_overlap: int = 50
    extract_fields: list[str] | None = None
    flatten_depth: int = 2
    array_limit: int = 10
    max_rows: int = 50
    table_format: str = "markdown"


@dataclass
class AdapterOverrides:
    """Override specific adapter dependencies for testing."""

    token_estimator: Any | None = None
    compression_strategy: Any | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def create_adapter(
    adapter_type: str = "text",
    config: AdapterConfig | None = None,
    overrides: AdapterOverrides | None = None,
    **kwargs: Any,
) -> ContextAdapter:
    """
    Create a context adapter.

    Supports three usage patterns:
    1. Simple: create_adapter("text")
    2. Config-based: create_adapter(config=AdapterConfig(...))
    3. Override-based: create_adapter(overrides=AdapterOverrides(...))

    Args:
        adapter_type: Type of adapter (text, json, table, chunk)
        config: Structured configuration
        overrides: Dependency overrides for testing
        **kwargs: Additional arguments passed to adapter

    Returns:
        Configured ContextAdapter instance

    Example:
        # Simple
        adapter = create_adapter("text")

        # With config
        adapter = create_adapter(config=AdapterConfig(
            adapter_type="json",
            extract_fields=["id", "name"],
        ))

        # For testing
        adapter = create_adapter(overrides=AdapterOverrides(
            token_estimator=MockEstimator(),
        ))
    """
    # Apply config
    if config:
        adapter_type = config.adapter_type
        kwargs.setdefault("chars_per_token", config.chars_per_token)

        if adapter_type == "text":
            kwargs.setdefault("max_tokens", config.max_tokens)
            kwargs.setdefault("truncation_strategy", config.truncation_strategy)
        elif adapter_type == "json":
            kwargs.setdefault("extract_fields", config.extract_fields)
            kwargs.setdefault("flatten_depth", config.flatten_depth)
            kwargs.setdefault("array_limit", config.array_limit)
        elif adapter_type == "table":
            kwargs.setdefault("max_rows", config.max_rows)
            kwargs.setdefault("format", config.table_format)
        elif adapter_type == "chunk":
            kwargs.setdefault("chunk_size", config.chunk_size)
            kwargs.setdefault("overlap", config.chunk_overlap)

    # Build adapter
    adapters = {
        "text": TextAdapter,
        "json": JSONAdapter,
        "table": TableAdapter,
        "chunk": ChunkAdapter,
    }

    if adapter_type not in adapters:
        raise ValueError(f"Unknown adapter type: {adapter_type}. Available: {list(adapters.keys())}")

    return adapters[adapter_type](**kwargs)


def create_adapter_from_config() -> ContextAdapter:
    """
    Create adapter from environment configuration.

    Environment variables:
    - CEMAF_ADAPTER_TYPE: text, json, table, chunk
    - CEMAF_ADAPTER_MAX_TOKENS: Maximum tokens
    - CEMAF_ADAPTER_CHARS_PER_TOKEN: Characters per token ratio
    - CEMAF_ADAPTER_TRUNCATION: head, tail, middle

    Returns:
        Configured ContextAdapter
    """
    adapter_type = os.getenv("CEMAF_ADAPTER_TYPE", "text")
    max_tokens = int(os.getenv("CEMAF_ADAPTER_MAX_TOKENS", "2000"))
    chars_per_token = float(os.getenv("CEMAF_ADAPTER_CHARS_PER_TOKEN", "4.0"))
    truncation = os.getenv("CEMAF_ADAPTER_TRUNCATION", "tail")

    config = AdapterConfig(
        adapter_type=adapter_type,
        max_tokens=max_tokens,
        chars_per_token=chars_per_token,
        truncation_strategy=truncation,
    )

    return create_adapter(config=config)


def create_text_adapter(
    max_tokens: int = 2000,
    truncation_strategy: str = "tail",
    chars_per_token: float = 4.0,
) -> TextAdapter:
    """Convenience factory for TextAdapter."""
    return TextAdapter(
        max_tokens=max_tokens,
        truncation_strategy=truncation_strategy,
        chars_per_token=chars_per_token,
    )


def create_json_adapter(
    extract_fields: list[str] | None = None,
    flatten_depth: int = 2,
    array_limit: int = 10,
) -> JSONAdapter:
    """Convenience factory for JSONAdapter."""
    return JSONAdapter(
        extract_fields=extract_fields,
        flatten_depth=flatten_depth,
        array_limit=array_limit,
    )


def create_table_adapter(
    max_rows: int = 50,
    format: str = "markdown",
    priority_columns: list[str] | None = None,
) -> TableAdapter:
    """Convenience factory for TableAdapter."""
    return TableAdapter(
        max_rows=max_rows,
        format=format,
        priority_columns=priority_columns,
    )


def create_chunk_adapter(
    chunk_size: int = 500,
    overlap: int = 50,
    strategy: str = "fixed",
) -> ChunkAdapter:
    """Convenience factory for ChunkAdapter."""
    return ChunkAdapter(
        chunk_size=chunk_size,
        overlap=overlap,
        strategy=strategy,
    )

"""
Context Ingestion module - Transform raw data into token-budgeted context.

CEMAF doesn't care how you fetch data. CEMAF cares how that data
fits into the Context Window.

This module provides Context Adapters that:
- Transform raw data into ContextSource objects
- Manage token budget constraints
- Apply compression strategies
- Assign priorities for selection algorithms
"""

from cemaf.ingestion.adapters import (
    ChunkAdapter,
    JSONAdapter,
    TableAdapter,
    TextAdapter,
)
from cemaf.ingestion.factories import (
    AdapterConfig,
    create_adapter,
    create_adapter_from_config,
)
from cemaf.ingestion.protocols import (
    CompressionStrategy,
    ContextAdapter,
    FormatOptimizer,
    PriorityAssigner,
)

__all__ = [
    # Protocols
    "ContextAdapter",
    "CompressionStrategy",
    "FormatOptimizer",
    "PriorityAssigner",
    # Adapters
    "TextAdapter",
    "JSONAdapter",
    "TableAdapter",
    "ChunkAdapter",
    # Factories
    "create_adapter",
    "create_adapter_from_config",
    "AdapterConfig",
]

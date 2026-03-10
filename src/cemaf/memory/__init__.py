"""
Memory module - Short-term and long-term memory management.

Memory types:
- SESSION: In-memory, single run (short-term)
- PERSISTENT: Stored in DB, survives runs (long-term)

Memory scopes:
- BRAND: Brand-level knowledge (shared across all projects)
- PROJECT: Project-specific knowledge
- AUDIENCE_SEGMENT: Segment-specific knowledge
- PLATFORM: Platform-specific knowledge
- PERSONAE: Persona-specific knowledge
- CONVERSATION: Conversation-scoped (cleared after each conversation)
- TURN: Turn-scoped (cleared after each turn)

## Configuration

Settings for this module are defined in MemorySettings.

Environment Variables:
    CEMAF_MEMORY_DEFAULT_TTL_SECONDS: Default TTL for memory items (default: 3600)
    CEMAF_MEMORY_MAX_ITEMS: Max items in memory store (default: 10000)
    CEMAF_MEMORY_CLEANUP_INTERVAL_SECONDS: Cleanup interval (default: 300)

## Usage

Protocol-based:
    >>> from cemaf.memory import MemoryStore, MemoryItem
    >>> from cemaf.core.enums import MemoryScope
    >>> from cemaf.core.types import Confidence
    >>>
    >>> class MyMemoryStore:
    ...     async def get(self, scope: MemoryScope, key: str) -> MemoryItem | None:
    ...         # Your implementation
    ...         ...
    ...
    ...     async def set(self, item: MemoryItem) -> None:
    ...         # Your implementation
    ...         ...

Built-in Implementation:
    >>> from cemaf.memory import InMemoryStore
    >>> store = InMemoryStore()
    >>> item = MemoryItem(
    ...     scope=MemoryScope.BRAND,
    ...     key="company",
    ...     value={"name": "Acme"}
    ... )
    >>> await store.set(item)

## Extension

Memory store implementations are discovered via protocols. No registration needed.
Simply implement the MemoryStore protocol and your store is compatible with all
CEMAF orchestration systems.

See cemaf.memory.protocols.MemoryStore for the protocol definition.
"""

# Built-in implementation
from cemaf.memory.base import InMemoryStore
from cemaf.memory.compaction import (
    CompactedMemory,
    CompactionLevel,
    MemoryCompactor,
    SimpleMemoryCompactor,
)
from cemaf.memory.factories import create_memory_store, create_memory_store_from_config
from cemaf.memory.protocols import MemoryItem, MemoryStore
from cemaf.memory.scoring import (
    DecayFunction,
    MemoryScorer,
    ScoredMemoryItem,
    ScoringWeights,
    TemporalDecayScorer,
)

__all__ = [
    # Core
    "MemoryItem",
    "MemoryStore",
    "InMemoryStore",
    # Scoring
    "DecayFunction",
    "MemoryScorer",
    "ScoredMemoryItem",
    "ScoringWeights",
    "TemporalDecayScorer",
    # Compaction
    "CompactedMemory",
    "CompactionLevel",
    "MemoryCompactor",
    "SimpleMemoryCompactor",
    # Factories
    "create_memory_store",
    "create_memory_store_from_config",
]

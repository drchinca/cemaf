"""
Memory module - Short-term and long-term memory management.

Memory types:
- SESSION: In-memory, single run (short-term)
- PERSISTENT: Stored in DB, survives runs (long-term)

Memory scopes (from start.ini):
- brand, project, audience_segment, platform, personae
"""

from cemaf.memory.base import MemoryItem, MemoryStore, InMemoryStore

__all__ = [
    "MemoryItem",
    "MemoryStore",
    "InMemoryStore",
]


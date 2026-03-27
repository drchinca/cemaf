"""Knowledge graph factory — create graph instances with sensible defaults."""

from __future__ import annotations

from cemaf.knowledge.graph import MemoryBackedKnowledgeGraph
from cemaf.memory.manager import MemoryManager


def create_knowledge_graph(
    memory_manager: MemoryManager,
) -> MemoryBackedKnowledgeGraph:
    """Create a knowledge graph backed by the given MemoryManager."""
    return MemoryBackedKnowledgeGraph(memory_manager=memory_manager)

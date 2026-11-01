"""Knowledge graph factory — create graph instances with sensible defaults."""

from __future__ import annotations

from typing import Any

from cemaf.context.patch import SecurityLevel
from cemaf.core.provider_registry import ProviderRegistry
from cemaf.knowledge.graph import MemoryBackedKnowledgeGraph
from cemaf.knowledge.protocols import KnowledgeGraph
from cemaf.memory.manager import MemoryManager

knowledge_graph_registry: ProviderRegistry[KnowledgeGraph] = ProviderRegistry(name="knowledge_graph")


def _create_memory_backed_knowledge_graph(**kwargs: Any) -> KnowledgeGraph:
    memory_manager = kwargs.get("memory_manager")
    if memory_manager is None:
        raise ValueError("memory knowledge graph backend requires memory_manager.")
    clearance = kwargs.get("clearance")
    if not isinstance(clearance, SecurityLevel):
        raise ValueError("memory knowledge graph backend requires a SecurityLevel clearance.")
    return MemoryBackedKnowledgeGraph(memory_manager=memory_manager, clearance=clearance)


knowledge_graph_registry.register(backend="memory", factory=_create_memory_backed_knowledge_graph)
knowledge_graph_registry.register(backend="memory_backed", factory=_create_memory_backed_knowledge_graph)


def create_knowledge_graph(
    memory_manager: MemoryManager,
    *,
    clearance: SecurityLevel,
    backend: str = "memory",
    **backend_options: Any,
) -> KnowledgeGraph:
    """Create a `KnowledgeGraph` via the registry; readers never see items above clearance."""
    return knowledge_graph_registry.create(
        backend=backend,
        memory_manager=memory_manager,
        clearance=clearance,
        **backend_options,
    )

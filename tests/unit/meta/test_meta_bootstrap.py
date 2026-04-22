"""Unit tests for create_meta_executor — the self-hosting composition root."""

from __future__ import annotations

from cemaf.agents.registry import AgentRegistry
from cemaf.audit.factories import create_audit_system
from cemaf.core.enums import MemoryScope
from cemaf.core.types import JSON, Confidence
from cemaf.events.bus import InMemoryEventBus
from cemaf.knowledge.factories import create_knowledge_graph
from cemaf.memory.base import MemoryItem
from cemaf.memory.episodic import Episode, EpisodicEvent
from cemaf.memory.semantic import MemoryQuery, MemorySearchResult
from cemaf.meta.bootstrap import MetaServices, create_meta_executor
from cemaf.orchestration.executor import DAGExecutor
from cemaf.orchestration.services import RuntimeServices
from cemaf.tools.registry import ToolRegistry

# ---------------------------------------------------------------------------
# Fake MemoryManager (same pattern as test_graph.py)
# ---------------------------------------------------------------------------


class FakeMemoryManager:
    """In-memory MemoryManager for testing."""

    def __init__(self) -> None:
        self._store: dict[str, MemoryItem] = {}

    async def remember(
        self,
        scope: MemoryScope,
        key: str,
        value: JSON,
        *,
        confidence: float = 1.0,
        content_for_embedding: str | None = None,
    ) -> MemoryItem:
        """Store item keyed by scope:key."""
        item = MemoryItem(
            scope=scope,
            key=key,
            value=value,
            confidence=Confidence(confidence),
        )
        self._store[f"{scope.value}:{key}"] = item
        return item

    async def recall(self, query: MemoryQuery) -> tuple[MemorySearchResult, ...]:
        """Simple text search across stored items."""
        results: list[MemorySearchResult] = []
        search_text = (query.text or "").lower()
        for item in self._store.values():
            if query.scope is not None and item.scope != query.scope:
                continue
            text_repr = f"{item.key} {str(item.value)}".lower()
            if search_text and search_text not in text_repr:
                continue
            results.append(
                MemorySearchResult(
                    item=item,
                    similarity=0.9,
                    combined_score=0.9,
                    rank=len(results),
                )
            )
            if len(results) >= query.limit:
                break
        return tuple(results)

    async def recall_by_key(self, scope: MemoryScope, key: str) -> MemoryItem | None:
        """Direct key lookup."""
        return self._store.get(f"{scope.value}:{key}")

    async def forget(self, scope: MemoryScope, key: str) -> bool:
        """Remove an item."""
        full_key = f"{scope.value}:{key}"
        if full_key in self._store:
            del self._store[full_key]
            return True
        return False

    async def start_episode(self, session_id: str) -> Episode:
        raise NotImplementedError

    async def record_event(self, episode_id: str, event: EpisodicEvent) -> None:
        raise NotImplementedError

    async def end_episode(self, episode_id: str) -> Episode:
        raise NotImplementedError

    async def get_recent_history(
        self,
        session_id: str,
        *,
        limit: int = 20,
    ) -> tuple[EpisodicEvent, ...]:
        raise NotImplementedError

    async def cleanup(self) -> int:
        return 0


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCreateMetaExecutor:
    """Verify create_meta_executor returns a working executor."""

    def test_returns_dag_executor(self) -> None:
        """Returns a DAGExecutor instance."""
        agent_registry = AgentRegistry()
        executor = create_meta_executor(agent_registry=agent_registry)
        assert isinstance(executor, DAGExecutor)

    def test_graceful_degradation_without_services(self) -> None:
        """Without event_bus or memory_manager, no meta-agents are registered."""
        agent_registry = AgentRegistry()
        executor = create_meta_executor(agent_registry=agent_registry)
        assert executor is not None
        assert agent_registry.get("MetaAuditor") is None
        assert agent_registry.get("MetaArchitect") is None

    def test_meta_agents_registered_with_services(self) -> None:
        """With event_bus + memory_manager, all meta-agents are registered."""
        agent_registry = AgentRegistry()
        tool_registry = ToolRegistry()
        event_bus = InMemoryEventBus()
        memory_manager = FakeMemoryManager()

        services = RuntimeServices(
            event_bus=event_bus,
            memory_manager=memory_manager,  # type: ignore[arg-type]
        )
        executor = create_meta_executor(
            agent_registry=agent_registry,
            tool_registry=tool_registry,
            services=services,
        )

        assert isinstance(executor, DAGExecutor)
        assert agent_registry.get("MetaAuditor") is not None
        assert agent_registry.get("MetaArchitect") is not None
        assert agent_registry.get("MetaSynthesizer") is not None
        assert agent_registry.get("MetaKnowledgeGraph") is not None

    def test_explicit_meta_services_used(self) -> None:
        """When MetaServices are provided, those are used instead of auto-creating."""
        agent_registry = AgentRegistry()
        tool_registry = ToolRegistry()
        event_bus = InMemoryEventBus()
        memory_manager = FakeMemoryManager()

        audit_log, audit_trail = create_audit_system(event_bus=event_bus)
        kg = create_knowledge_graph(memory_manager=memory_manager)  # type: ignore[arg-type]

        meta_services = MetaServices(
            audit_log=audit_log,
            audit_trail=audit_trail,
            knowledge_graph=kg,
        )
        services = RuntimeServices(event_bus=event_bus)

        executor = create_meta_executor(
            agent_registry=agent_registry,
            tool_registry=tool_registry,
            services=services,
            meta_services=meta_services,
        )

        assert isinstance(executor, DAGExecutor)
        assert agent_registry.get("MetaAuditor") is not None

    def test_no_meta_agents_without_event_bus(self) -> None:
        """With memory_manager but no event_bus, still degrades gracefully."""
        agent_registry = AgentRegistry()
        memory_manager = FakeMemoryManager()
        services = RuntimeServices(memory_manager=memory_manager)  # type: ignore[arg-type]

        executor = create_meta_executor(
            agent_registry=agent_registry,
            services=services,
        )
        assert isinstance(executor, DAGExecutor)
        # No audit_trail (needs event_bus), so meta-agents not registered
        assert agent_registry.get("MetaAuditor") is None

"""Unit tests for register_meta_agents helper."""

from __future__ import annotations

from cemaf.agents.registry import AgentRegistry
from cemaf.audit.models import AuditEntry
from cemaf.knowledge.models import EntityType, KGEntity, KGQueryResult, KGRelation, RelationType
from cemaf.meta.goals import ArchitectGoal, AuditGoal, KnowledgeGraphGoal, SynthesizerGoal
from cemaf.meta.registry import register_meta_agents
from cemaf.tools.registry import ToolRegistry

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeAuditTrail:
    """Minimal AuditTrail for testing registration."""

    async def get_run_timeline(self, run_id: str) -> tuple[AuditEntry, ...]:
        return ()

    async def get_quality_trend(self, *, window: int = 20) -> tuple[float, ...]:
        return ()

    async def get_anomalies(self, *, threshold: float = 2.0) -> tuple[AuditEntry, ...]:
        return ()


class FakeKnowledgeGraph:
    """Minimal KnowledgeGraph for testing registration."""

    async def add_entity(self, entity: KGEntity) -> None:
        pass

    async def add_relation(self, relation: KGRelation) -> None:
        pass

    async def get_entity(self, entity_id: str) -> KGEntity | None:
        return None

    async def query_neighbors(
        self,
        entity_id: str,
        relation_type: RelationType | None = None,
        depth: int = 1,
    ) -> KGQueryResult:
        return KGQueryResult(entities=(), relations=())

    async def search(
        self,
        query: str,
        entity_type: EntityType | None = None,
        limit: int = 10,
    ) -> tuple[KGEntity, ...]:
        return ()

    async def remove_entity(self, entity_id: str) -> bool:
        return False


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRegisterMetaAgents:
    """Verify register_meta_agents wires all tools and agents."""

    def setup_method(self) -> None:
        """Create fresh registries and fakes for each test."""
        self.agent_registry = AgentRegistry()
        self.tool_registry = ToolRegistry()
        self.audit_trail = FakeAuditTrail()
        self.knowledge_graph = FakeKnowledgeGraph()

    def _register(self) -> None:
        """Invoke register_meta_agents with test dependencies."""
        register_meta_agents(
            self.agent_registry,
            tool_registry=self.tool_registry,
            audit_trail=self.audit_trail,
            knowledge_graph=self.knowledge_graph,
        )

    def test_all_four_agents_registered(self) -> None:
        """All meta-agents are discoverable by ID after registration."""
        self._register()
        assert self.agent_registry.get("MetaArchitect") is not None
        assert self.agent_registry.get("MetaSynthesizer") is not None
        assert self.agent_registry.get("MetaAuditor") is not None
        assert self.agent_registry.get("MetaKnowledgeGraph") is not None

    def test_all_four_tools_registered(self) -> None:
        """All meta-tools are discoverable by ID after registration."""
        self._register()
        assert self.tool_registry.get("meta_introspect_registry") is not None
        assert self.tool_registry.get("meta_generate_dag") is not None
        assert self.tool_registry.get("meta_trace_analyzer") is not None
        assert self.tool_registry.get("meta_knowledge_graph") is not None

    def test_goal_types_registered(self) -> None:
        """Each agent has its correct goal type registered."""
        self._register()
        assert self.agent_registry.get_goal_type("MetaArchitect") is ArchitectGoal
        assert self.agent_registry.get_goal_type("MetaSynthesizer") is SynthesizerGoal
        assert self.agent_registry.get_goal_type("MetaAuditor") is AuditGoal
        assert self.agent_registry.get_goal_type("MetaKnowledgeGraph") is KnowledgeGraphGoal

    def test_agent_count(self) -> None:
        """Exactly 4 agents registered (no extras)."""
        self._register()
        assert len(self.agent_registry.list_agents()) == 4

    def test_tool_count(self) -> None:
        """Exactly 4 tools registered (no extras)."""
        self._register()
        assert len(self.tool_registry.list_tools()) == 4

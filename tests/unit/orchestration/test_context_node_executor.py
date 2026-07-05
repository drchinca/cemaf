"""Tests for ContextNodeExecutor."""

import pytest
from pydantic import BaseModel

from cemaf.agents.base import Agent, AgentContext, AgentResult, AgentState
from cemaf.agents.registry import AgentRegistry
from cemaf.context.context import Context
from cemaf.core.enums import NodeType
from cemaf.core.types import AgentID, NodeID
from cemaf.knowledge import EntityType, KGEntity, create_knowledge_graph
from cemaf.llm.mock import MockLLMClient
from cemaf.memory.factories import create_memory_manager
from cemaf.observability.run_logger import InMemoryRunLogger
from cemaf.orchestration.context_node_executor import ContextNodeExecutor
from cemaf.orchestration.dag import Node
from cemaf.retrieval.factories import create_in_memory_vector_store


@pytest.fixture
def registry() -> AgentRegistry:
    """Create a registry with built-in agents available."""
    return AgentRegistry()


@pytest.fixture
def executor(registry: AgentRegistry) -> ContextNodeExecutor:
    """Create executor with registry."""
    return ContextNodeExecutor(agent_registry=registry)


@pytest.fixture
def executor_with_logger(registry: AgentRegistry) -> tuple[ContextNodeExecutor, InMemoryRunLogger]:
    """Create executor with run logger."""
    run_logger = InMemoryRunLogger()
    run_logger.start_run(run_id="test-run", dag_name="test-dag", initial_context=Context())
    executor = ContextNodeExecutor(agent_registry=registry, run_logger=run_logger)
    return executor, run_logger


class KGProbeGoal(BaseModel):
    entity_id: str


class KGProbeResult(BaseModel):
    stored_entity_id: str


class KGProbeAgent(Agent[KGProbeGoal, KGProbeResult]):
    @property
    def id(self) -> AgentID:
        return AgentID("KGProbe")

    @property
    def description(self) -> str:
        return "Uses AgentContext.knowledge_graph"

    @property
    def skills(self) -> tuple[()]:
        return ()

    async def run(self, goal: KGProbeGoal, context: AgentContext) -> AgentResult[KGProbeResult]:
        if context.knowledge_graph is None:
            return AgentResult.fail("knowledge graph missing", AgentState())
        entity = KGEntity(
            id=goal.entity_id,
            type=EntityType.AGENT,
            name="KG Probe",
        )
        await context.knowledge_graph.add_entity(entity)
        return AgentResult.ok(
            output=KGProbeResult(stored_entity_id=entity.id),
            state=AgentState(),
        )


class TestContextNodeExecutor:
    """Tests for ContextNodeExecutor."""

    @pytest.mark.asyncio
    async def test_execute_unknown_agent(self, executor: ContextNodeExecutor) -> None:
        node = Node(
            id=NodeID("step_1"),
            type=NodeType.AGENT,
            name="Unknown",
            ref_id="NonexistentAgent",
        )
        result = await executor.execute_node(node=node, context=Context())
        assert not result.success
        assert "not found" in (result.error or "")

    @pytest.mark.asyncio
    async def test_execute_missing_ref_id(self, executor: ContextNodeExecutor) -> None:
        node = Node(
            id=NodeID("step_1"),
            type=NodeType.AGENT,
            name="NoRef",
            ref_id="",
        )
        result = await executor.execute_node(node=node, context=Context())
        assert not result.success
        assert "no ref_id" in (result.error or "")

    @pytest.mark.asyncio
    async def test_execute_librarian_agent(self, registry: AgentRegistry) -> None:
        vector_store = create_in_memory_vector_store()
        agent = registry.create_agent("Librarian", vector_store=vector_store)
        assert agent is not None
        registry.register_agent(agent_instance=agent)
        executor = ContextNodeExecutor(agent_registry=registry)

        node = Node(
            id=NodeID("step_1"),
            type=NodeType.AGENT,
            name="Librarian",
            ref_id="Librarian",
            input_mapping={"intent_query": "professional audit style"},
        )
        context = Context(data={"_resolved_inputs": {"intent_query": "professional audit style"}})
        result = await executor.execute_node(node=node, context=context)
        assert result.success
        assert result.output is not None

    @pytest.mark.asyncio
    async def test_execute_summarizer_agent(self, registry: AgentRegistry) -> None:
        llm_client = MockLLMClient()
        agent = registry.create_agent("Summarizer", llm_client=llm_client)
        assert agent is not None
        registry.register_agent(agent_instance=agent)
        executor = ContextNodeExecutor(agent_registry=registry)

        node = Node(
            id=NodeID("step_1"),
            type=NodeType.AGENT,
            name="Summarizer",
            ref_id="Summarizer",
        )
        context = Context(
            data={
                "_resolved_inputs": {
                    "text_to_summarize": "Long text about AI research findings.",
                    "summary_objective": "Key takeaways",
                }
            }
        )
        result = await executor.execute_node(node=node, context=context)
        assert result.success
        assert result.metadata.get("agent_id") == "Summarizer"

    @pytest.mark.asyncio
    async def test_execute_with_provenance_logging(self, registry: AgentRegistry) -> None:
        vector_store = create_in_memory_vector_store()
        agent = registry.create_agent("Librarian", vector_store=vector_store)
        assert agent is not None
        registry.register_agent(agent_instance=agent)

        run_logger = InMemoryRunLogger()
        run_logger.start_run(run_id="prov-test", dag_name="test", initial_context=Context())
        executor = ContextNodeExecutor(
            agent_registry=registry,
            run_logger=run_logger,
        )

        node = Node(
            id=NodeID("step_1"),
            type=NodeType.AGENT,
            name="Librarian",
            ref_id="Librarian",
        )
        context = Context(data={"_resolved_inputs": {"intent_query": "test"}})
        result = await executor.execute_node(node=node, context=context)
        assert result.success

        # Check provenance was recorded
        record = run_logger.get_current_record()
        assert record is not None
        assert record.provenance_chain is not None
        assert len(record.provenance_chain.links) == 1
        link = record.provenance_chain.links[0]
        assert link.agent_id == "Librarian"
        assert link.node_id == "step_1"

    @pytest.mark.asyncio
    async def test_execute_invalid_goal_inputs(self, registry: AgentRegistry) -> None:
        llm_client = MockLLMClient()
        agent = registry.create_agent("Writer", llm_client=llm_client)
        assert agent is not None
        registry.register_agent(agent_instance=agent)
        executor = ContextNodeExecutor(agent_registry=registry)

        node = Node(
            id=NodeID("step_1"),
            type=NodeType.AGENT,
            name="Writer",
            ref_id="Writer",
        )
        # Missing required 'blueprint' field
        context = Context(data={"_resolved_inputs": {"wrong_field": "value"}})
        result = await executor.execute_node(node=node, context=context)
        assert not result.success
        assert "Failed to build goal" in (result.error or "")

    @pytest.mark.asyncio
    async def test_execute_with_domain_context(self, registry: AgentRegistry) -> None:
        from cemaf.core.domain import DomainContext
        from cemaf.core.types import DomainID, TenantID

        vector_store = create_in_memory_vector_store()
        agent = registry.create_agent("Librarian", vector_store=vector_store)
        assert agent is not None
        registry.register_agent(agent_instance=agent)

        domain = DomainContext(
            domain_id=DomainID("marketing"),
            tenant_id=TenantID("acme"),
            business_rules=("formal tone", "include citations"),
        )
        executor = ContextNodeExecutor(
            agent_registry=registry,
            domain_context=domain,
        )

        node = Node(
            id=NodeID("step_1"),
            type=NodeType.AGENT,
            name="Librarian",
            ref_id="Librarian",
        )
        context = Context(data={"_resolved_inputs": {"intent_query": "formal report"}})
        result = await executor.execute_node(node=node, context=context)
        assert result.success

    @pytest.mark.asyncio
    async def test_execute_passes_knowledge_graph_to_agent_context(
        self,
        registry: AgentRegistry,
    ) -> None:
        kg = create_knowledge_graph(memory_manager=create_memory_manager())
        registry.register_agent(agent_instance=KGProbeAgent(), goal_type=KGProbeGoal)
        executor = ContextNodeExecutor(agent_registry=registry, knowledge_graph=kg)

        node = Node(
            id=NodeID("step_kg"),
            type=NodeType.AGENT,
            name="KG Probe",
            ref_id="KGProbe",
        )
        context = Context(data={"_resolved_inputs": {"entity_id": "entity:kg-probe"}})

        result = await executor.execute_node(node=node, context=context)

        assert result.success
        assert await kg.get_entity("entity:kg-probe") is not None

    @pytest.mark.asyncio
    async def test_context_hash_deterministic(self, executor: ContextNodeExecutor) -> None:
        inputs = {"key1": "value1", "key2": "value2"}
        hash1 = executor._compute_context_hash(inputs=inputs)
        hash2 = executor._compute_context_hash(inputs=inputs)
        assert hash1 == hash2
        assert len(hash1) == 16

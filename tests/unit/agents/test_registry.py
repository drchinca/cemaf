"""Tests for Agent Registry v2."""

from pydantic import BaseModel

from cemaf.agents import AgentContext, AgentResult, AgentState
from cemaf.agents.registry import AgentRegistry, agent_factory_registry, create_default_registry
from cemaf.core.types import AgentID
from cemaf.llm.mock import MockLLMClient
from cemaf.retrieval.factories import create_in_memory_vector_store


class CustomFactoryGoal(BaseModel):
    task: str = "test"


class CustomFactoryAgent:
    def __init__(self, *, agent_id: str = "CustomFactory", marker: str = "") -> None:
        self._agent_id = AgentID(agent_id)
        self.marker = marker

    @property
    def id(self) -> AgentID:
        return self._agent_id

    @property
    def description(self) -> str:
        return "Custom factory agent"

    @property
    def skills(self) -> tuple[()]:
        return ()

    async def run(self, goal: CustomFactoryGoal, context: AgentContext) -> AgentResult[str]:
        return AgentResult.ok(output=self.marker or goal.task, state=AgentState())


class TestAgentRegistry:
    """Tests for AgentRegistry."""

    def test_registry_initialization(self) -> None:
        registry = AgentRegistry()
        assert registry is not None
        assert registry.count() == 0

    def test_get_agent_class(self) -> None:
        registry = AgentRegistry()
        agent_class = registry.get_agent_class("Librarian")
        assert agent_class is not None

    def test_get_unknown_agent_class(self) -> None:
        registry = AgentRegistry()
        assert registry.get_agent_class("UnknownAgent") is None

    def test_get_goal_type(self) -> None:
        registry = AgentRegistry()
        goal_type = registry.get_goal_type("Librarian")
        assert goal_type is not None

    def test_create_librarian_agent(self) -> None:
        vector_store = create_in_memory_vector_store()
        registry = AgentRegistry()

        agent = registry.create_agent(
            "Librarian",
            vector_store=vector_store,
            namespace_context="test_blueprints",
            librarian_top_k=3,
        )

        assert agent is not None
        assert agent.id == "Librarian"

    def test_create_researcher_agent(self) -> None:
        vector_store = create_in_memory_vector_store()
        llm_client = MockLLMClient()
        registry = AgentRegistry()

        agent = registry.create_agent(
            "Researcher",
            vector_store=vector_store,
            llm_client=llm_client,
            namespace_knowledge="test_knowledge",
            researcher_top_k=20,
        )

        assert agent is not None
        assert agent.id == "Researcher"

    def test_create_summarizer_agent(self) -> None:
        llm_client = MockLLMClient()
        registry = AgentRegistry()
        agent = registry.create_agent("Summarizer", llm_client=llm_client)
        assert agent is not None
        assert agent.id == "Summarizer"

    def test_create_writer_agent(self) -> None:
        llm_client = MockLLMClient()
        registry = AgentRegistry()
        agent = registry.create_agent("Writer", llm_client=llm_client)
        assert agent is not None
        assert agent.id == "Writer"

    def test_create_agent_missing_dependencies(self) -> None:
        registry = AgentRegistry()
        agent = registry.create_agent("Librarian")
        assert agent is None

        llm_client = MockLLMClient()
        agent = registry.create_agent("Researcher", llm_client=llm_client)
        assert agent is None

    def test_create_unknown_agent_returns_none(self) -> None:
        registry = AgentRegistry()

        assert registry.create_agent("UnknownAgent") is None

    def test_register_custom_agent_factory(self) -> None:
        captured: dict[str, object] = {}

        def factory(**kwargs: object) -> CustomFactoryAgent:
            captured.update(kwargs)
            return CustomFactoryAgent(marker=str(kwargs["marker"]))

        agent_factory_registry.register(backend="UnitCustomAgent", factory=factory)
        registry = AgentRegistry()

        agent = registry.create_agent("UnitCustomAgent", marker="created")

        assert isinstance(agent, CustomFactoryAgent)
        assert agent.id == "CustomFactory"
        assert agent.marker == "created"
        assert captured["marker"] == "created"

    def test_registered_instance_takes_precedence_over_factory(self) -> None:
        factory_calls = 0

        def factory(**kwargs: object) -> CustomFactoryAgent:
            nonlocal factory_calls
            factory_calls += 1
            return CustomFactoryAgent(agent_id="FactoryAgent")

        agent_factory_registry.register(backend="UnitExistingAgent", factory=factory)
        registry = AgentRegistry()
        existing = CustomFactoryAgent(agent_id="UnitExistingAgent", marker="existing")
        registry.register_agent(agent_instance=existing, goal_type=CustomFactoryGoal)

        agent = registry.create_agent("UnitExistingAgent")

        assert agent is existing
        assert factory_calls == 0

    def test_register_agent_dynamic(self) -> None:
        registry = AgentRegistry()
        llm_client = MockLLMClient()
        agent = registry.create_agent("Writer", llm_client=llm_client)
        assert agent is not None
        registry.register_agent(agent_instance=agent)
        assert registry.count() == 1
        assert "Writer" in registry.list_agents()

    def test_register_agent_with_domain(self) -> None:
        registry = AgentRegistry()
        llm_client = MockLLMClient()
        agent = registry.create_agent("Summarizer", llm_client=llm_client)
        assert agent is not None
        registry.register_agent(
            agent_instance=agent,
            domain_id="marketing",
        )
        domain_agents = registry.get_for_domain(domain_id="marketing")
        assert len(domain_agents) == 1
        assert domain_agents[0].id == "Summarizer"

    def test_get_for_domain_empty(self) -> None:
        registry = AgentRegistry()
        assert registry.get_for_domain(domain_id="nonexistent") == []

    def test_capabilities_description_empty(self) -> None:
        registry = AgentRegistry()
        assert registry.get_capabilities_description() == "No agents registered."

    def test_capabilities_description_with_agents(self) -> None:
        registry = AgentRegistry()
        llm_client = MockLLMClient()
        writer = registry.create_agent("Writer", llm_client=llm_client)
        assert writer is not None
        registry.register_agent(agent_instance=writer)

        desc = registry.get_capabilities_description()
        assert "Writer" in desc
        assert "AGENT:" in desc

    def test_create_default_registry(self) -> None:
        registry = create_default_registry()
        assert isinstance(registry, AgentRegistry)
        assert registry.count() == 0

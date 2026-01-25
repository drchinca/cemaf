"""
Tests for Agent Registry.

Ensures registry is extensible and configurable.
"""

from cemaf.agents.registry import AGENT_TOOLKIT, AgentRegistry
from cemaf.llm.mock import MockLLMClient
from cemaf.retrieval.factories import create_in_memory_vector_store


class TestAgentRegistry:
    """Tests for AgentRegistry."""

    def test_registry_initialization(self):
        """Test that registry initializes correctly."""
        registry = AgentRegistry()
        assert registry is not None
        assert len(registry.list_agents()) > 0

    def test_list_agents(self):
        """Test listing all registered agents."""
        registry = AgentRegistry()
        agents = registry.list_agents()
        assert "Librarian" in agents
        assert "Researcher" in agents
        assert "Summarizer" in agents
        assert "Writer" in agents

    def test_get_agent_class(self):
        """Test getting agent class by name."""
        registry = AgentRegistry()
        agent_class = registry.get_agent_class("Librarian")
        assert agent_class is not None

    def test_get_unknown_agent(self):
        """Test getting unknown agent returns None."""
        registry = AgentRegistry()
        agent_class = registry.get_agent_class("UnknownAgent")
        assert agent_class is None

    def test_get_goal_type(self):
        """Test getting goal type for agent."""
        registry = AgentRegistry()
        goal_type = registry.get_goal_type("Librarian")
        assert goal_type is not None

    def test_create_librarian_agent(self):
        """Test creating Librarian agent."""
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
        assert agent._namespace_context == "test_blueprints"
        assert agent._top_k == 3

    def test_create_researcher_agent(self):
        """Test creating Researcher agent."""
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
        assert agent._namespace_knowledge == "test_knowledge"
        assert agent._top_k == 20

    def test_create_summarizer_agent(self):
        """Test creating Summarizer agent."""
        llm_client = MockLLMClient()
        registry = AgentRegistry()

        agent = registry.create_agent("Summarizer", llm_client=llm_client)

        assert agent is not None
        assert agent.id == "Summarizer"

    def test_create_writer_agent(self):
        """Test creating Writer agent."""
        llm_client = MockLLMClient()
        registry = AgentRegistry()

        agent = registry.create_agent("Writer", llm_client=llm_client)

        assert agent is not None
        assert agent.id == "Writer"

    def test_create_agent_missing_dependencies(self):
        """Test creating agent without required dependencies."""
        registry = AgentRegistry()

        # Librarian without vector_store
        agent = registry.create_agent("Librarian")
        assert agent is None

        # Researcher without vector_store
        llm_client = MockLLMClient()
        agent = registry.create_agent("Researcher", llm_client=llm_client)
        assert agent is None

        # Researcher without llm_client
        vector_store = create_in_memory_vector_store()
        agent = registry.create_agent("Researcher", vector_store=vector_store)
        assert agent is None

    def test_get_capabilities_description(self):
        """Test getting capabilities description."""
        registry = AgentRegistry()
        description = registry.get_capabilities_description()

        assert isinstance(description, str)
        assert "Librarian" in description
        assert "Researcher" in description
        assert "Summarizer" in description
        assert "Writer" in description
        assert "INPUTS" in description
        assert "OUTPUT" in description

    def test_global_toolkit(self):
        """Test that global AGENT_TOOLKIT is available."""
        assert AGENT_TOOLKIT is not None
        assert isinstance(AGENT_TOOLKIT, AgentRegistry)

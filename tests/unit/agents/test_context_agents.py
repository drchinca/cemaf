"""
Tests for Context Engineering Agents.

Tests follow TDD principles and ensure all agents are:
- Configurable (no hardcoded values)
- Extensible (protocol-based)
- Well-tested (edge cases, error handling)
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from cemaf.agents.base import AgentContext
from cemaf.agents.context_agents import (
    LibrarianAgent,
    LibrarianGoal,
    LibrarianResult,
    ResearcherAgent,
    ResearcherGoal,
    ResearcherResult,
    SummarizerAgent,
    SummarizerGoal,
    SummarizerResult,
    WriterAgent,
    WriterGoal,
    WriterResult,
)
from cemaf.core.types import AgentID
from cemaf.llm.protocols import CompletionResult, Message, MessageRole


@pytest.fixture
def mock_vector_store():
    """Mock vector store for testing."""
    store = AsyncMock()
    store.search_by_text = AsyncMock()
    return store


@pytest.fixture
def mock_llm_client():
    """Mock LLM client for testing."""
    client = AsyncMock()
    client.complete = AsyncMock()
    return client


@pytest.fixture
def agent_context():
    """Standard agent context for testing."""
    return AgentContext(
        run_id="test_run",
        agent_id="test_agent",
    )


class TestLibrarianAgent:
    """Tests for LibrarianAgent."""

    def test_agent_properties(self, mock_vector_store):
        """Test agent ID and description."""
        agent = LibrarianAgent(mock_vector_store)
        assert agent.id == AgentID("Librarian")
        assert "Retrieves Semantic Blueprints" in agent.description
        assert agent.skills == ()

    def test_configurable_namespace(self, mock_vector_store):
        """Test that namespace is configurable."""
        agent = LibrarianAgent(mock_vector_store, namespace_context="custom_namespace")
        assert agent._namespace_context == "custom_namespace"

    def test_configurable_top_k(self, mock_vector_store):
        """Test that top_k is configurable."""
        agent = LibrarianAgent(mock_vector_store, top_k=5)
        assert agent._top_k == 5

    def test_default_values(self, mock_vector_store):
        """Test default configuration values."""
        agent = LibrarianAgent(mock_vector_store)
        assert agent._namespace_context == "blueprints"
        assert agent._top_k == 1

    @pytest.mark.asyncio
    async def test_successful_retrieval(self, mock_vector_store, agent_context):
        """Test successful blueprint retrieval."""
        # Setup mock
        blueprint_data = {"instruction": "Generate professional content"}
        mock_doc = MagicMock()
        mock_doc.id = "blueprint_1"
        mock_doc.content = json.dumps(blueprint_data)
        mock_doc.metadata = {"blueprint_json": json.dumps(blueprint_data)}

        mock_result = MagicMock()
        mock_result.document = mock_doc
        mock_result.score = 0.95

        mock_vector_store.search_by_text.return_value = [mock_result]

        # Execute
        agent = LibrarianAgent(mock_vector_store)
        goal = LibrarianGoal(intent_query="professional style")
        result = await agent.run(goal, agent_context)

        # Assertions
        assert result.success
        assert result.output is not None
        assert isinstance(result.output, LibrarianResult)
        # Should return valid JSON blueprint
        blueprint_parsed = json.loads(result.output.blueprint_json)
        assert isinstance(blueprint_parsed, dict)
        mock_vector_store.search_by_text.assert_called_once_with(
            query_text="professional style",
            k=1,
            filter={"namespace": "blueprints"},
        )

    @pytest.mark.asyncio
    async def test_no_results_returns_default(self, mock_vector_store, agent_context):
        """Test that no results returns default blueprint."""
        mock_vector_store.search_by_text.return_value = []

        agent = LibrarianAgent(mock_vector_store)
        goal = LibrarianGoal(intent_query="unknown style")
        result = await agent.run(goal, agent_context)

        assert result.success
        assert result.output is not None
        blueprint_data = json.loads(result.output.blueprint_json)
        assert "instruction" in blueprint_data

    @pytest.mark.asyncio
    async def test_error_handling(self, mock_vector_store, agent_context):
        """Test error handling."""
        mock_vector_store.search_by_text.side_effect = Exception("Vector store error")

        agent = LibrarianAgent(mock_vector_store)
        goal = LibrarianGoal(intent_query="test")
        result = await agent.run(goal, agent_context)

        assert not result.success
        assert "error" in result.error.lower()


class TestResearcherAgent:
    """Tests for ResearcherAgent."""

    def test_agent_properties(self, mock_vector_store, mock_llm_client):
        """Test agent ID and description."""
        agent = ResearcherAgent(mock_vector_store, mock_llm_client)
        assert agent.id == AgentID("Researcher")
        assert "Synthesizes" in agent.description
        assert agent.skills == ()

    def test_configurable_namespace(self, mock_vector_store, mock_llm_client):
        """Test that namespace is configurable."""
        agent = ResearcherAgent(mock_vector_store, mock_llm_client, namespace_knowledge="custom_knowledge")
        assert agent._namespace_knowledge == "custom_knowledge"

    def test_configurable_top_k(self, mock_vector_store, mock_llm_client):
        """Test that top_k is configurable."""
        agent = ResearcherAgent(mock_vector_store, mock_llm_client, top_k=20)
        assert agent._top_k == 20

    def test_default_values(self, mock_vector_store, mock_llm_client):
        """Test default configuration values."""
        agent = ResearcherAgent(mock_vector_store, mock_llm_client)
        assert agent._namespace_knowledge == "knowledge"
        assert agent._top_k == 15

    @pytest.mark.asyncio
    async def test_successful_research(self, mock_vector_store, mock_llm_client, agent_context):
        """Test successful research with synthesis."""
        # Setup vector store mock
        mock_doc1 = MagicMock()
        mock_doc1.content = "Fact 1 about topic"
        mock_doc1.metadata = {"source": "source1", "text": "Fact 1 about topic"}

        mock_doc2 = MagicMock()
        mock_doc2.content = "Fact 2 about topic"
        mock_doc2.metadata = {"source": "source2", "text": "Fact 2 about topic"}

        mock_result1 = MagicMock()
        mock_result1.document = mock_doc1
        mock_result2 = MagicMock()
        mock_result2.document = mock_doc2

        mock_vector_store.search_by_text.return_value = [mock_result1, mock_result2]

        # Setup LLM mock
        mock_llm_client.complete.return_value = CompletionResult.ok(
            Message(role=MessageRole.ASSISTANT, content="Synthesized facts: Fact 1 and Fact 2"),
            prompt_tokens=100,
            completion_tokens=50,
        )

        # Execute
        agent = ResearcherAgent(mock_vector_store, mock_llm_client)
        goal = ResearcherGoal(topic_query="test topic")
        result = await agent.run(goal, agent_context)

        # Assertions
        assert result.success
        assert result.output is not None
        assert isinstance(result.output, ResearcherResult)
        assert "facts" in result.output.facts.lower()
        mock_vector_store.search_by_text.assert_called_once_with(
            query_text="test topic",
            k=15,
            filter={"namespace": "knowledge"},
        )
        mock_llm_client.complete.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_evidence_found(self, mock_vector_store, mock_llm_client, agent_context):
        """Test handling when no evidence is found."""
        mock_vector_store.search_by_text.return_value = []

        agent = ResearcherAgent(mock_vector_store, mock_llm_client)
        goal = ResearcherGoal(topic_query="unknown topic")
        result = await agent.run(goal, agent_context)

        assert result.success
        assert result.output.facts == "No evidence found."

    @pytest.mark.asyncio
    async def test_llm_failure(self, mock_vector_store, mock_llm_client, agent_context):
        """Test handling LLM synthesis failure."""
        mock_doc = MagicMock()
        mock_doc.content = "Some content"
        mock_doc.metadata = {"source": "source1", "text": "Some content"}
        mock_result = MagicMock()
        mock_result.document = mock_doc

        mock_vector_store.search_by_text.return_value = [mock_result]
        mock_llm_client.complete.return_value = CompletionResult.fail("LLM error")

        agent = ResearcherAgent(mock_vector_store, mock_llm_client)
        goal = ResearcherGoal(topic_query="test")
        result = await agent.run(goal, agent_context)

        assert not result.success
        assert "llm" in result.error.lower() or "synthesis" in result.error.lower()


class TestSummarizerAgent:
    """Tests for SummarizerAgent."""

    def test_agent_properties(self, mock_llm_client):
        """Test agent ID and description."""
        agent = SummarizerAgent(mock_llm_client)
        assert agent.id == AgentID("Summarizer")
        assert "Reduces text" in agent.description
        assert agent.skills == ()

    @pytest.mark.asyncio
    async def test_successful_summarization(self, mock_llm_client, agent_context):
        """Test successful summarization."""
        long_text = "This is a very long text that needs to be summarized. " * 10
        mock_llm_client.complete.return_value = CompletionResult.ok(
            Message(role=MessageRole.ASSISTANT, content="Summary of the text"),
            prompt_tokens=200,
            completion_tokens=20,
        )

        agent = SummarizerAgent(mock_llm_client)
        goal = SummarizerGoal(
            text_to_summarize=long_text,
            summary_objective="Extract key points",
        )
        result = await agent.run(goal, agent_context)

        assert result.success
        assert result.output is not None
        assert isinstance(result.output, SummarizerResult)
        assert len(result.output.summary) < len(long_text)
        mock_llm_client.complete.assert_called_once()

    @pytest.mark.asyncio
    async def test_dict_input_handling(self, mock_llm_client, agent_context):
        """Test handling dict input (from other agents)."""
        # Dict is converted to string before passing to goal
        text_to_summarize = "Some facts to summarize and also some report content"
        mock_llm_client.complete.return_value = CompletionResult.ok(
            Message(role=MessageRole.ASSISTANT, content="Summarized facts"),
            prompt_tokens=50,
            completion_tokens=10,
        )

        agent = SummarizerAgent(mock_llm_client)
        goal = SummarizerGoal(
            text_to_summarize=text_to_summarize,
            summary_objective="Summarize",
        )
        result = await agent.run(goal, agent_context)

        assert result.success
        assert result.output is not None

    @pytest.mark.asyncio
    async def test_token_telemetry_included(self, mock_llm_client, agent_context):
        """Test that token telemetry is included in metadata."""
        mock_llm_client.complete.return_value = CompletionResult.ok(
            Message(role=MessageRole.ASSISTANT, content="Summary"),
            prompt_tokens=100,
            completion_tokens=20,
        )

        agent = SummarizerAgent(mock_llm_client)
        goal = SummarizerGoal(text_to_summarize="Long text", summary_objective="Summarize")
        result = await agent.run(goal, agent_context)

        assert result.success
        assert "tokens_in" in result.metadata
        assert "tokens_out" in result.metadata
        assert "tokens_saved" in result.metadata  # Special for Summarizer
        assert result.metadata["tokens_saved"] >= 0


class TestWriterAgent:
    """Tests for WriterAgent."""

    def test_agent_properties(self, mock_llm_client):
        """Test agent ID and description."""
        agent = WriterAgent(mock_llm_client)
        assert agent.id == AgentID("Writer")
        assert "Generates or rewrites content" in agent.description
        assert agent.skills == ()

    @pytest.mark.asyncio
    async def test_successful_generation(self, mock_llm_client, agent_context):
        """Test successful content generation."""
        blueprint_json = json.dumps({"instruction": "Write professionally"})
        facts = "Fact 1: Important information"

        mock_llm_client.complete.return_value = CompletionResult.ok(
            Message(role=MessageRole.ASSISTANT, content="Generated report content"),
            prompt_tokens=150,
            completion_tokens=100,
        )

        agent = WriterAgent(mock_llm_client)
        goal = WriterGoal(blueprint=blueprint_json, facts=facts)
        result = await agent.run(goal, agent_context)

        assert result.success
        assert result.output is not None
        assert isinstance(result.output, WriterResult)
        assert len(result.output.report) > 0
        mock_llm_client.complete.assert_called_once()

    @pytest.mark.asyncio
    async def test_blueprint_json_string_input(self, mock_llm_client, agent_context):
        """Test handling Blueprint JSON string input."""
        blueprint_json = json.dumps({"objective": "Generate professional content", "style": "formal"})
        facts = "Some facts"

        mock_llm_client.complete.return_value = CompletionResult.ok(
            Message(role=MessageRole.ASSISTANT, content="Generated content"),
            prompt_tokens=100,
            completion_tokens=50,
        )

        agent = WriterAgent(mock_llm_client)
        goal = WriterGoal(blueprint=blueprint_json, facts=facts)
        result = await agent.run(goal, agent_context)

        assert result.success
        assert result.output is not None
        assert len(result.output.report) > 0

    @pytest.mark.asyncio
    async def test_missing_blueprint_error(self, mock_llm_client, agent_context):
        """Test error when blueprint is missing."""
        agent = WriterAgent(mock_llm_client)
        goal = WriterGoal(blueprint="", facts="Some facts")
        result = await agent.run(goal, agent_context)

        assert not result.success
        assert "blueprint" in result.error.lower()

    @pytest.mark.asyncio
    async def test_missing_facts_error(self, mock_llm_client, agent_context):
        """Test error when facts are missing."""
        agent = WriterAgent(mock_llm_client)
        goal = WriterGoal(blueprint="Some blueprint", facts=None, previous_content=None)
        result = await agent.run(goal, agent_context)

        assert not result.success
        assert "facts" in result.error.lower() or "previous_content" in result.error.lower()

    @pytest.mark.asyncio
    async def test_dict_input_handling(self, mock_llm_client, agent_context):
        """Test handling dict inputs from other agents."""
        blueprint_dict = {"blueprint_json": json.dumps({"instruction": "Write"})}
        facts_dict = {"summary": "Summarized facts"}

        mock_llm_client.complete.return_value = CompletionResult.ok(
            Message(role=MessageRole.ASSISTANT, content="Generated"),
            prompt_tokens=50,
            completion_tokens=25,
        )

        agent = WriterAgent(mock_llm_client)
        goal = WriterGoal(blueprint=blueprint_dict, facts=facts_dict)
        result = await agent.run(goal, agent_context)

        assert result.success

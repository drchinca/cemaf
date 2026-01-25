"""
Tests for Autonomous Planner.

Ensures planner generates valid DAGs and handles errors gracefully.
"""

import json
from unittest.mock import AsyncMock

import pytest

from cemaf.agents.registry import AgentRegistry
from cemaf.llm.protocols import CompletionResult, Message, MessageRole
from cemaf.orchestration.planner import Planner


@pytest.fixture
def mock_llm_client():
    """Mock LLM client for planning."""
    client = AsyncMock()
    return client


@pytest.fixture
def agent_registry():
    """Agent registry for testing."""
    return AgentRegistry()


@pytest.fixture
def planner(mock_llm_client, agent_registry):
    """Planner instance for testing."""
    return Planner(llm_client=mock_llm_client, agent_registry=agent_registry)


class TestPlanner:
    """Tests for Planner."""

    @pytest.mark.asyncio
    async def test_generate_simple_plan(self, planner, mock_llm_client):
        """Test generating a simple execution plan."""
        plan_json = {
            "plan": [
                {"step": 1, "agent": "Librarian", "input": {"intent_query": "professional style"}},
                {"step": 2, "agent": "Researcher", "input": {"topic_query": "AI safety"}},
                {
                    "step": 3,
                    "agent": "Writer",
                    "input": {"blueprint": "$$STEP_1_OUTPUT$$", "facts": "$$STEP_2_OUTPUT$$"},
                },
            ]
        }

        mock_llm_client.complete.return_value = CompletionResult.ok(
            Message(role=MessageRole.ASSISTANT, content=json.dumps(plan_json)),
            prompt_tokens=200,
            completion_tokens=150,
        )

        dag = await planner.plan("Generate an audit report on AI safety")

        assert dag is not None
        assert len(dag.nodes) == 3
        assert dag.entry_node is not None
        dag.validate_structure()  # Should not raise

    @pytest.mark.asyncio
    async def test_plan_with_context_chaining(self, planner, mock_llm_client):
        """Test plan with context chaining placeholders."""
        plan_json = {
            "plan": [
                {"step": 1, "agent": "Librarian", "input": {"intent_query": "style"}},
                {"step": 2, "agent": "Writer", "input": {"blueprint": "$$STEP_1_OUTPUT$$"}},
            ]
        }

        mock_llm_client.complete.return_value = CompletionResult.ok(
            Message(role=MessageRole.ASSISTANT, content=json.dumps(plan_json)),
            prompt_tokens=100,
            completion_tokens=50,
        )

        dag = await planner.plan("Generate content")
        assert dag is not None
        assert len(dag.nodes) == 2

        # Check that input_mapping contains placeholders
        step2_node = dag.get_node(dag.nodes[1].id)
        assert step2_node is not None
        assert "$$STEP_1_OUTPUT$$" in str(step2_node.input_mapping)

    @pytest.mark.asyncio
    async def test_plan_validation(self, planner, mock_llm_client):
        """Test that generated plan validates agent names."""
        plan_json = {
            "plan": [
                {"step": 1, "agent": "UnknownAgent", "input": {}},
            ]
        }

        mock_llm_client.complete.return_value = CompletionResult.ok(
            Message(role=MessageRole.ASSISTANT, content=json.dumps(plan_json)),
            prompt_tokens=50,
            completion_tokens=25,
        )

        with pytest.raises(ValueError, match="Unknown agent"):
            await planner.plan("Test goal")

    @pytest.mark.asyncio
    async def test_plan_handles_markdown_code_blocks(self, planner, mock_llm_client):
        """Test that planner extracts JSON from markdown code blocks."""
        plan_json = {
            "plan": [
                {"step": 1, "agent": "Librarian", "input": {"intent_query": "test"}},
            ]
        }

        # LLM sometimes wraps JSON in markdown
        markdown_response = f"```json\n{json.dumps(plan_json)}\n```"

        mock_llm_client.complete.return_value = CompletionResult.ok(
            Message(role=MessageRole.ASSISTANT, content=markdown_response),
            prompt_tokens=50,
            completion_tokens=30,
        )

        dag = await planner.plan("Test goal")
        assert dag is not None
        assert len(dag.nodes) == 1

    @pytest.mark.asyncio
    async def test_plan_handles_llm_failure(self, planner, mock_llm_client):
        """Test handling LLM planning failure."""
        mock_llm_client.complete.return_value = CompletionResult.fail("LLM error")

        with pytest.raises(ValueError, match="planning failed"):
            await planner.plan("Test goal")

    @pytest.mark.asyncio
    async def test_plan_handles_invalid_json(self, planner, mock_llm_client):
        """Test handling invalid JSON from LLM."""
        mock_llm_client.complete.return_value = CompletionResult.ok(
            Message(role=MessageRole.ASSISTANT, content="Not valid JSON {invalid}"),
            prompt_tokens=50,
            completion_tokens=10,
        )

        with pytest.raises(ValueError, match="Invalid JSON"):
            await planner.plan("Test goal")

    @pytest.mark.asyncio
    async def test_plan_missing_plan_key(self, planner, mock_llm_client):
        """Test handling response missing 'plan' key."""
        invalid_json = {"steps": []}

        mock_llm_client.complete.return_value = CompletionResult.ok(
            Message(role=MessageRole.ASSISTANT, content=json.dumps(invalid_json)),
            prompt_tokens=50,
            completion_tokens=10,
        )

        with pytest.raises(ValueError, match="missing 'plan' key"):
            await planner.plan("Test goal")

    @pytest.mark.asyncio
    async def test_plan_output_keys(self, planner, mock_llm_client):
        """Test that plan sets correct output keys for context chaining."""
        plan_json = {
            "plan": [
                {"step": 1, "agent": "Librarian", "input": {"intent_query": "test"}},
                {"step": 2, "agent": "Writer", "input": {"blueprint": "$$STEP_1_OUTPUT$$"}},
            ]
        }

        mock_llm_client.complete.return_value = CompletionResult.ok(
            Message(role=MessageRole.ASSISTANT, content=json.dumps(plan_json)),
            prompt_tokens=100,
            completion_tokens=50,
        )

        dag = await planner.plan("Test goal")

        # Check output keys are set correctly
        step1_node = dag.get_node(dag.nodes[0].id)
        assert step1_node.output_key == "STEP_1_OUTPUT"

        step2_node = dag.get_node(dag.nodes[1].id)
        assert step2_node.output_key == "STEP_2_OUTPUT"

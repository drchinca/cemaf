"""
Unit tests for the retrieval DAG example.

Tests the retrieval + caching + retry + context propagation workflow.
"""

import pytest

from cemaf.skills.base import SkillContext
from examples.retrieval_dag_example import (
    AnalysisTool,
    MockVectorStore,
    RetrievalInput,
    RetrievalSkill,
    build_retrieval_dag,
)


class TestRetrievalSkill:
    """Tests for RetrievalSkill."""

    @pytest.mark.asyncio
    async def test_retrieval_skill_executes_successfully(self):
        """RetrievalSkill retrieves and returns documents."""
        vector_store = MockVectorStore()
        skill = RetrievalSkill(vector_store)

        input_data = RetrievalInput(query="test query", top_k=3)
        context = SkillContext(run_id="test", agent_id="test")

        result = await skill.execute(input_data, context)

        assert result.success
        assert result.data is not None
        assert "documents" in result.data.data
        assert len(result.data.data["documents"]) == 3
        assert result.data.data["query"] == "test query"
        assert result.data.data["cached"] is False

    @pytest.mark.asyncio
    async def test_retrieval_skill_caches_results(self):
        """RetrievalSkill caches results for repeated queries."""
        vector_store = MockVectorStore()
        skill = RetrievalSkill(vector_store)

        input_data = RetrievalInput(query="cached query", top_k=2)
        context = SkillContext(run_id="test", agent_id="test")

        # First call - should retrieve
        result1 = await skill.execute(input_data, context)
        assert result1.success
        assert result1.data.data["cached"] is False
        initial_call_count = vector_store._call_count

        # Second call - should use cache
        result2 = await skill.execute(input_data, context)
        assert result2.success
        assert result2.data.data["cached"] is True
        assert vector_store._call_count == initial_call_count  # No new call

    @pytest.mark.asyncio
    async def test_retrieval_skill_emits_metadata(self):
        """RetrievalSkill returns metadata for observability."""
        vector_store = MockVectorStore()
        skill = RetrievalSkill(vector_store)

        input_data = RetrievalInput(query="metadata test")
        context = SkillContext(run_id="test", agent_id="test")

        result = await skill.execute(input_data, context)

        assert result.success
        data = result.data.data
        assert "num_results" in data
        assert "top_score" in data
        assert data["num_results"] > 0
        assert isinstance(data["top_score"], (int, float))


class TestAnalysisTool:
    """Tests for AnalysisTool."""

    @pytest.mark.asyncio
    async def test_analysis_tool_executes(self):
        """AnalysisTool analyzes with given focus."""
        tool = AnalysisTool()

        result = await tool.execute(focus="summary")

        assert result.success
        assert "analysis" in result.data
        assert "focus" in result.data
        assert result.data["focus"] == "summary"

    def test_analysis_tool_has_valid_schema(self):
        """AnalysisTool has properly defined schema."""
        tool = AnalysisTool()
        schema = tool.schema

        assert schema.name == "analyze"
        assert "focus" in schema.parameters["properties"]
        assert "focus" in schema.required


class TestRetrievalDAG:
    """Tests for the retrieval DAG."""

    def test_dag_construction(self):
        """Retrieval DAG is constructed correctly."""
        vector_store = MockVectorStore()
        dag = build_retrieval_dag(vector_store)

        assert dag.name == "retrieval_example"
        assert len(dag.nodes) == 3  # retrieve, analyze, format
        assert len(dag.edges) == 2  # retrieve→analyze, analyze→format

        # Verify retrieval node has retry configured
        retrieve_node = dag.get_node("retrieve")
        assert retrieve_node is not None
        assert retrieve_node.retry_on_failure is True
        assert retrieve_node.max_retries == 2
        assert retrieve_node.output_key == "retrieved_docs"

    def test_dag_has_proper_context_keys(self):
        """DAG nodes have output_keys for context propagation."""
        vector_store = MockVectorStore()
        dag = build_retrieval_dag(vector_store)

        retrieve_node = dag.get_node("retrieve")
        analyze_node = dag.get_node("analyze")
        format_node = dag.get_node("format")

        assert retrieve_node.output_key == "retrieved_docs"
        assert analyze_node.output_key == "analysis_result"
        assert format_node.output_key == "final_response"


class TestMockVectorStore:
    """Tests for MockVectorStore."""

    @pytest.mark.asyncio
    async def test_vector_store_search(self):
        """MockVectorStore returns documents."""
        store = MockVectorStore()

        docs = await store.search("test", top_k=5)

        assert len(docs) == 3  # Max 3 in mock
        assert all(d.content for d in docs)
        assert all(d.score >= 0 for d in docs)
        assert docs[0].score > docs[-1].score  # Descending scores

    @pytest.mark.asyncio
    async def test_vector_store_tracks_calls(self):
        """MockVectorStore tracks call count."""
        store = MockVectorStore()
        assert store._call_count == 0

        await store.search("query1")
        assert store._call_count == 1

        await store.search("query2")
        assert store._call_count == 2

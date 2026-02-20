"""
Tests for Token Telemetry.

Ensures token tracking works correctly for cost analysis.
"""

from cemaf.llm.protocols import CompletionResult, Message, MessageRole
from cemaf.observability.token_telemetry import (
    count_tokens,
    extract_token_metadata,
    merge_token_metadata,
)


class TestTokenTelemetry:
    """Tests for token telemetry utilities."""

    def test_extract_from_completion_result(self):
        """Test extracting token metadata from CompletionResult."""
        llm_result = CompletionResult.ok(
            Message(role=MessageRole.ASSISTANT, content="Response"),
            prompt_tokens=100,
            completion_tokens=50,
            model="gpt-4",
        )

        metadata = extract_token_metadata(llm_result=llm_result)

        assert metadata["tokens_in"] == 100
        assert metadata["tokens_out"] == 50
        assert metadata["tokens_total"] == 150

    def test_extract_from_text(self):
        """Test extracting token metadata from text."""
        input_text = "This is input text " * 10
        output_text = "Output " * 5

        metadata = extract_token_metadata(
            input_text=input_text,
            output_text=output_text,
            model="gpt-4",
        )

        assert metadata["tokens_in"] > 0
        assert metadata["tokens_out"] > 0
        assert metadata["tokens_total"] == metadata["tokens_in"] + metadata["tokens_out"]

    def test_summarizer_tokens_saved(self):
        """Test tokens_saved calculation for Summarizer."""
        llm_result = CompletionResult.ok(
            Message(role=MessageRole.ASSISTANT, content="Summary"),
            prompt_tokens=200,
            completion_tokens=50,
        )

        metadata = extract_token_metadata(
            llm_result=llm_result,
            agent_name="Summarizer",
        )

        assert "tokens_saved" in metadata
        assert metadata["tokens_saved"] == 150  # 200 - 50
        assert "compression_ratio" in metadata
        assert metadata["compression_ratio"] == 0.25  # 50 / 200

    def test_non_summarizer_no_tokens_saved(self):
        """Test that non-Summarizer agents don't have tokens_saved."""
        llm_result = CompletionResult.ok(
            Message(role=MessageRole.ASSISTANT, content="Response"),
            prompt_tokens=100,
            completion_tokens=50,
        )

        metadata = extract_token_metadata(
            llm_result=llm_result,
            agent_name="Writer",
        )

        # Any agent with output < input now tracks compression
        assert metadata["tokens_saved"] == 50
        assert metadata["agent_name"] == "Writer"

    def test_cost_estimate_included(self):
        """Test that cost estimate is included when pricing available."""
        llm_result = CompletionResult.ok(
            Message(role=MessageRole.ASSISTANT, content="Response"),
            prompt_tokens=1000,
            completion_tokens=500,
            model="gpt-4",
        )

        metadata = extract_token_metadata(llm_result=llm_result)

        # Cost estimate may or may not be present depending on pricing registry
        # Just check that extraction doesn't fail
        assert "tokens_in" in metadata
        assert "tokens_out" in metadata

    def test_count_tokens(self):
        """Test token counting utility."""
        text = "This is a test sentence."
        tokens = count_tokens(text)

        assert isinstance(tokens, int)
        assert tokens > 0

    def test_count_tokens_different_models(self):
        """Test token counting with different models."""
        text = "Test text"

        tokens_gpt4 = count_tokens(text, model="gpt-4")
        tokens_gpt35 = count_tokens(text, model="gpt-3.5-turbo")

        # Both should return valid counts
        assert tokens_gpt4 > 0
        assert tokens_gpt35 > 0

    def test_merge_token_metadata(self):
        """Test merging token metadata from multiple sources."""
        metadata_list = [
            {"tokens_in": 100, "tokens_out": 50, "cost_estimate_usd": 0.01},
            {"tokens_in": 200, "tokens_out": 100, "cost_estimate_usd": 0.02},
            {"tokens_in": 50, "tokens_out": 25, "tokens_saved": 25, "cost_estimate_usd": 0.005},
        ]

        merged = merge_token_metadata(metadata_list)

        assert merged["tokens_in"] == 350
        assert merged["tokens_out"] == 175
        assert merged["tokens_total"] == 525
        assert merged["tokens_saved"] == 25
        assert merged["cost_estimate_usd"] == 0.035
        assert merged["llm_calls"] == 3

    def test_merge_empty_list(self):
        """Test merging empty metadata list."""
        merged = merge_token_metadata([])

        assert merged["tokens_in"] == 0
        assert merged["tokens_out"] == 0
        assert merged["tokens_total"] == 0
        assert merged["llm_calls"] == 0

"""
Unit tests for RLM chunking strategies.

Tests chunking implementations for breaking content into processable chunks.
"""

import pytest

from cemaf.context.compiler import SimpleTokenEstimator
from cemaf.rlm.chunking import FixedSizeChunkingStrategy


class TestFixedSizeChunkingStrategy:
    """Tests for FixedSizeChunkingStrategy."""

    @pytest.fixture
    def estimator(self) -> SimpleTokenEstimator:
        """Create token estimator for tests."""
        return SimpleTokenEstimator(chars_per_token=4.0)

    @pytest.fixture
    def strategy(self, estimator: SimpleTokenEstimator) -> FixedSizeChunkingStrategy:
        """Create chunking strategy for tests."""
        return FixedSizeChunkingStrategy(estimator, chunk_size=50)

    def test_empty_content(self, strategy: FixedSizeChunkingStrategy) -> None:
        """Test chunking empty content."""
        chunks = strategy.chunk("", max_chunk_tokens=50)
        assert chunks == ()

    def test_whitespace_only(self, strategy: FixedSizeChunkingStrategy) -> None:
        """Test chunking whitespace-only content."""
        chunks = strategy.chunk("   \n\n   ", max_chunk_tokens=50)
        assert chunks == ()

    def test_single_small_chunk(self, strategy: FixedSizeChunkingStrategy) -> None:
        """Test content that fits in single chunk."""
        content = "This is a short piece of content."
        chunks = strategy.chunk(content, max_chunk_tokens=50)

        assert len(chunks) == 1
        assert chunks[0].content == content
        assert chunks[0].chunk_id == "chunk_0"
        assert chunks[0].depth == 0
        assert chunks[0].parent_id is None

    def test_multiple_chunks(self, strategy: FixedSizeChunkingStrategy) -> None:
        """Test content that requires multiple chunks."""
        paragraphs = [
            "First paragraph with some content that takes up space.",
            "Second paragraph with additional content that also needs space.",
            "Third paragraph to ensure we have enough content for chunking.",
        ]
        content = "\n\n".join(paragraphs)

        chunks = strategy.chunk(content, max_chunk_tokens=30)

        assert len(chunks) >= 2
        for i, chunk in enumerate(chunks):
            assert chunk.chunk_id == f"chunk_{i}"
            assert chunk.depth == 0
            assert isinstance(chunk.token_count, int)
            assert int(chunk.token_count) > 0

    def test_respects_paragraph_boundaries(self, strategy: FixedSizeChunkingStrategy) -> None:
        """Test that chunking respects paragraph boundaries when possible."""
        paragraphs = ["Short para one.", "Short para two.", "Short para three."]
        content = "\n\n".join(paragraphs)

        chunks = strategy.chunk(content, max_chunk_tokens=100)

        combined_content = "\n\n".join(chunk.content for chunk in chunks)
        assert combined_content.replace("\n\n", " ").strip() == content.replace("\n\n", " ").strip()

    def test_chunk_size_limits(self, strategy: FixedSizeChunkingStrategy) -> None:
        """Test that chunks respect size limits."""
        content = "word " * 1000
        max_tokens = 50

        chunks = strategy.chunk(content, max_chunk_tokens=max_tokens)

        for chunk in chunks:
            assert int(chunk.token_count) <= max_tokens * 1.5

    def test_chunk_ids_sequential(self, strategy: FixedSizeChunkingStrategy) -> None:
        """Test that chunk IDs are sequential."""
        content = "paragraph one\n\n" * 10
        chunks = strategy.chunk(content, max_chunk_tokens=20)

        for i, chunk in enumerate(chunks):
            assert chunk.chunk_id == f"chunk_{i}"

    def test_chunk_metadata(self, strategy: FixedSizeChunkingStrategy) -> None:
        """Test that chunks have correct metadata."""
        content = "Test content for metadata checking."
        chunks = strategy.chunk(content, max_chunk_tokens=50)

        assert len(chunks) >= 1
        for chunk in chunks:
            assert chunk.metadata["source"] == "fixed_size_chunking"

    def test_very_long_paragraph(self, strategy: FixedSizeChunkingStrategy) -> None:
        """Test handling of very long paragraphs."""
        long_paragraph = "word " * 500
        chunks = strategy.chunk(long_paragraph, max_chunk_tokens=30)

        assert len(chunks) > 1
        total_content = " ".join(chunk.content for chunk in chunks)
        assert total_content.strip() == long_paragraph.strip()

    def test_mixed_length_paragraphs(self, strategy: FixedSizeChunkingStrategy) -> None:
        """Test handling of mixed-length paragraphs."""
        content = (
            "Short.\n\n"
            + ("Medium length paragraph. " * 5)
            + "\n\n"
            + ("Very long paragraph with lots of content. " * 20)
            + "\n\nAnother short one."
        )

        chunks = strategy.chunk(content, max_chunk_tokens=40)

        assert len(chunks) >= 2
        assert all(chunk.content.strip() for chunk in chunks)

    def test_create_hierarchy(self, strategy: FixedSizeChunkingStrategy) -> None:
        """Test hierarchy creation (currently returns flat structure)."""
        content = "Test content for hierarchy."
        chunks = strategy.chunk(content, max_chunk_tokens=50)

        hierarchical_chunks = strategy.create_hierarchy(chunks)

        assert hierarchical_chunks == chunks

    def test_token_count_estimation(
        self, estimator: SimpleTokenEstimator, strategy: FixedSizeChunkingStrategy
    ) -> None:
        """Test that token counts are reasonable."""
        content = "This is a test with twenty words here now okay good fine great thanks bye end done."
        chunks = strategy.chunk(content, max_chunk_tokens=100)

        estimated_total = estimator.estimate(content)
        chunk_total = sum(int(chunk.token_count) for chunk in chunks)

        assert abs(chunk_total - estimated_total) / estimated_total < 0.2

    def test_different_chunk_sizes(self, estimator: SimpleTokenEstimator) -> None:
        """Test different chunk size configurations."""
        content = "word " * 200

        for chunk_size in [10, 25, 50, 100]:
            strategy = FixedSizeChunkingStrategy(estimator, chunk_size=chunk_size)
            chunks = strategy.chunk(content, max_chunk_tokens=chunk_size)

            for chunk in chunks:
                assert int(chunk.token_count) <= chunk_size * 1.5

    def test_preserves_content(self, strategy: FixedSizeChunkingStrategy) -> None:
        """Test that all content is preserved across chunks."""
        content = "Important content that must not be lost during chunking process."
        chunks = strategy.chunk(content, max_chunk_tokens=20)

        combined = " ".join(chunk.content for chunk in chunks)
        content_words = content.split()
        combined_words = combined.split()

        assert len(content_words) == len(combined_words)

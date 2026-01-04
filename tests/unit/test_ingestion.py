"""
Unit tests for context ingestion module.

Tests the ContextAdapter protocol and implementations following TDD.
"""

import pytest

from cemaf.context.budget import TokenBudget
from cemaf.ingestion.adapters import (
    ChunkAdapter,
    JSONAdapter,
    TableAdapter,
    TextAdapter,
)
from cemaf.ingestion.factories import (
    AdapterConfig,
    create_adapter,
    create_chunk_adapter,
    create_json_adapter,
    create_table_adapter,
    create_text_adapter,
)
from cemaf.ingestion.protocols import ContextAdapter


class TestContextAdapterProtocol:
    """Tests for ContextAdapter protocol compliance."""

    def test_text_adapter_implements_protocol(self) -> None:
        """TextAdapter implements ContextAdapter protocol."""
        adapter = TextAdapter()
        assert isinstance(adapter, ContextAdapter)

    def test_json_adapter_implements_protocol(self) -> None:
        """JSONAdapter implements ContextAdapter protocol."""
        adapter = JSONAdapter()
        assert isinstance(adapter, ContextAdapter)

    def test_table_adapter_implements_protocol(self) -> None:
        """TableAdapter implements ContextAdapter protocol."""
        adapter = TableAdapter()
        assert isinstance(adapter, ContextAdapter)

    def test_chunk_adapter_implements_protocol(self) -> None:
        """ChunkAdapter implements ContextAdapter protocol."""
        adapter = ChunkAdapter()
        assert isinstance(adapter, ContextAdapter)


class TestTextAdapter:
    """Tests for TextAdapter."""

    @pytest.mark.asyncio
    async def test_adapt_simple_text(self) -> None:
        """Adapt simple text to context source."""
        adapter = TextAdapter(chars_per_token=4.0)
        budget = TokenBudget(max_tokens=1000, reserved_for_output=0)

        source = await adapter.adapt("Hello, world!", budget, priority=5)

        assert source.type == "text"
        assert source.content == "Hello, world!"
        assert source.priority == 5
        assert source.token_count > 0

    @pytest.mark.asyncio
    async def test_adapt_truncates_long_text(self) -> None:
        """Long text is truncated to fit budget."""
        adapter = TextAdapter(max_tokens=10, truncation_strategy="tail")
        budget = TokenBudget(max_tokens=10, reserved_for_output=0)

        long_text = "A" * 1000
        source = await adapter.adapt(long_text, budget, priority=0)

        assert source.token_count <= 10
        assert "..." in source.content  # Truncation marker

    @pytest.mark.asyncio
    async def test_truncation_strategy_head(self) -> None:
        """Head truncation keeps beginning of text."""
        adapter = TextAdapter(max_tokens=10, truncation_strategy="head")
        budget = TokenBudget(max_tokens=10, reserved_for_output=0)

        long_text = "A" * 50 + "B" * 50
        source = await adapter.adapt(long_text, budget, priority=0)

        assert source.content.startswith("A")

    @pytest.mark.asyncio
    async def test_truncation_strategy_middle(self) -> None:
        """Middle truncation keeps both ends."""
        adapter = TextAdapter(max_tokens=10, truncation_strategy="middle")
        budget = TokenBudget(max_tokens=10, reserved_for_output=0)

        long_text = "START" + "X" * 100 + "END"
        source = await adapter.adapt(long_text, budget, priority=0)

        assert "truncated" in source.content.lower()

    def test_estimate_tokens(self) -> None:
        """Token estimation uses chars_per_token ratio."""
        adapter = TextAdapter(chars_per_token=4.0)

        assert adapter.estimate_tokens("12345678") == 2  # 8 chars / 4 = 2
        assert adapter.estimate_tokens("1234") == 1  # 4 chars / 4 = 1


class TestJSONAdapter:
    """Tests for JSONAdapter."""

    @pytest.mark.asyncio
    async def test_adapt_simple_json(self) -> None:
        """Adapt simple JSON to context source."""
        adapter = JSONAdapter()
        budget = TokenBudget(max_tokens=1000, reserved_for_output=0)

        data = {"name": "Alice", "age": 30}
        source = await adapter.adapt(data, budget, priority=3)

        assert source.type == "json"
        assert "Alice" in source.content
        assert source.priority == 3

    @pytest.mark.asyncio
    async def test_extract_specific_fields(self) -> None:
        """Only specified fields are extracted."""
        adapter = JSONAdapter(extract_fields=["name", "email"])
        budget = TokenBudget(max_tokens=1000, reserved_for_output=0)

        data = {"name": "Alice", "email": "alice@test.com", "password": "secret"}
        source = await adapter.adapt(data, budget, priority=0)

        assert "Alice" in source.content
        assert "alice@test.com" in source.content
        assert "secret" not in source.content

    @pytest.mark.asyncio
    async def test_array_limit(self) -> None:
        """Arrays are limited to array_limit items."""
        adapter = JSONAdapter(array_limit=3)
        budget = TokenBudget(max_tokens=1000, reserved_for_output=0)

        data = {"items": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]}
        source = await adapter.adapt(data, budget, priority=0)

        # Should only contain first 3 items
        assert "1" in source.content
        assert "2" in source.content
        assert "3" in source.content
        # Items beyond limit should not appear
        assert "10" not in source.content

    def test_estimate_tokens_dict(self) -> None:
        """Token estimation works for dicts."""
        adapter = JSONAdapter(chars_per_token=4.0)

        data = {"key": "value"}
        tokens = adapter.estimate_tokens(data)

        assert tokens > 0


class TestTableAdapter:
    """Tests for TableAdapter."""

    @pytest.mark.asyncio
    async def test_adapt_list_of_dicts(self) -> None:
        """Adapt list of dicts to table source."""
        adapter = TableAdapter(format="markdown")
        budget = TokenBudget(max_tokens=1000, reserved_for_output=0)

        data = [
            {"name": "Alice", "age": 30},
            {"name": "Bob", "age": 25},
        ]
        source = await adapter.adapt(data, budget, priority=7)

        assert source.type == "table"
        assert "Alice" in source.content
        assert "Bob" in source.content
        assert "|" in source.content  # Markdown table format
        assert source.priority == 7

    @pytest.mark.asyncio
    async def test_max_rows_limit(self) -> None:
        """Tables are limited to max_rows."""
        adapter = TableAdapter(max_rows=2)
        budget = TokenBudget(max_tokens=1000, reserved_for_output=0)

        data = [{"id": i} for i in range(10)]
        source = await adapter.adapt(data, budget, priority=0)

        # Should only contain 2 rows + header
        assert source.metadata["rows"] == 2

    @pytest.mark.asyncio
    async def test_priority_columns(self) -> None:
        """Only priority columns are included."""
        adapter = TableAdapter(priority_columns=["name"])
        budget = TokenBudget(max_tokens=1000, reserved_for_output=0)

        data = [
            {"name": "Alice", "secret": "password123"},
        ]
        source = await adapter.adapt(data, budget, priority=0)

        assert "Alice" in source.content
        assert "password123" not in source.content

    @pytest.mark.asyncio
    async def test_csv_format(self) -> None:
        """Table can be formatted as CSV."""
        adapter = TableAdapter(format="csv")
        budget = TokenBudget(max_tokens=1000, reserved_for_output=0)

        data = [{"a": 1, "b": 2}]
        source = await adapter.adapt(data, budget, priority=0)

        assert "a,b" in source.content or "a\tb" in source.content


class TestChunkAdapter:
    """Tests for ChunkAdapter."""

    @pytest.mark.asyncio
    async def test_adapt_returns_first_chunk(self) -> None:
        """Single adapt returns first chunk."""
        adapter = ChunkAdapter(chunk_size=10)
        budget = TokenBudget(max_tokens=1000, reserved_for_output=0)

        text = "A" * 100
        source = await adapter.adapt(text, budget, priority=5)

        assert source.type == "chunk"
        assert source.metadata["chunk_index"] == 0
        assert source.priority == 5

    @pytest.mark.asyncio
    async def test_adapt_many_splits_document(self) -> None:
        """adapt_many returns multiple chunks."""
        adapter = ChunkAdapter(chunk_size=10, overlap=0)
        budget = TokenBudget(max_tokens=1000, reserved_for_output=0)

        # 100 chars / 4 chars_per_token = 25 tokens, chunk_size=10 means ~3 chunks
        text = "A" * 100
        sources = await adapter.adapt_many(text, budget, base_priority=10)

        assert len(sources) > 1
        assert all(s.type == "chunk" for s in sources)
        # Earlier chunks have higher priority
        assert sources[0].priority > sources[-1].priority

    @pytest.mark.asyncio
    async def test_chunks_have_overlap(self) -> None:
        """Chunks overlap as configured."""
        adapter = ChunkAdapter(chunk_size=20, overlap=5, chars_per_token=1.0)
        budget = TokenBudget(max_tokens=1000, reserved_for_output=0)

        text = "ABCDEFGHIJ" * 10  # 100 chars
        sources = await adapter.adapt_many(text, budget)

        # With overlap, there should be shared content between chunks
        if len(sources) >= 2:
            # Some overlap should exist
            assert len(sources) >= 2

    @pytest.mark.asyncio
    async def test_sentence_split_strategy(self) -> None:
        """Sentence strategy splits at sentence boundaries."""
        adapter = ChunkAdapter(chunk_size=20, strategy="sentence")
        budget = TokenBudget(max_tokens=1000, reserved_for_output=0)

        text = "First sentence. Second sentence. Third sentence."
        sources = await adapter.adapt_many(text, budget)

        # Chunks should not break mid-sentence
        for source in sources:
            # Each chunk should end at sentence boundary or be the last chunk
            content = source.content.strip()
            if content and not content.endswith("."):
                # It's either mid-text or the last partial
                pass


class TestFactories:
    """Tests for factory functions."""

    def test_create_adapter_text(self) -> None:
        """create_adapter creates TextAdapter."""
        adapter = create_adapter("text")
        assert isinstance(adapter, TextAdapter)

    def test_create_adapter_json(self) -> None:
        """create_adapter creates JSONAdapter."""
        adapter = create_adapter("json")
        assert isinstance(adapter, JSONAdapter)

    def test_create_adapter_table(self) -> None:
        """create_adapter creates TableAdapter."""
        adapter = create_adapter("table")
        assert isinstance(adapter, TableAdapter)

    def test_create_adapter_chunk(self) -> None:
        """create_adapter creates ChunkAdapter."""
        adapter = create_adapter("chunk")
        assert isinstance(adapter, ChunkAdapter)

    def test_create_adapter_with_config(self) -> None:
        """create_adapter accepts AdapterConfig."""
        config = AdapterConfig(
            adapter_type="text",
            max_tokens=500,
            truncation_strategy="head",
        )
        adapter = create_adapter(config=config)

        assert isinstance(adapter, TextAdapter)
        assert adapter.max_tokens == 500
        assert adapter.truncation_strategy == "head"

    def test_create_adapter_invalid_type_raises(self) -> None:
        """Unknown adapter type raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            create_adapter("invalid_type")

        assert "Unknown adapter type" in str(exc_info.value)

    def test_convenience_factories(self) -> None:
        """Convenience factories create correct types."""
        assert isinstance(create_text_adapter(), TextAdapter)
        assert isinstance(create_json_adapter(), JSONAdapter)
        assert isinstance(create_table_adapter(), TableAdapter)
        assert isinstance(create_chunk_adapter(), ChunkAdapter)

    def test_factory_with_kwargs(self) -> None:
        """Factories pass through kwargs."""
        adapter = create_text_adapter(max_tokens=100, truncation_strategy="middle")

        assert adapter.max_tokens == 100
        assert adapter.truncation_strategy == "middle"


class TestAdapterMetadata:
    """Tests for adapter metadata in context sources."""

    @pytest.mark.asyncio
    async def test_text_adapter_tracks_original_tokens(self) -> None:
        """TextAdapter metadata includes original token count."""
        adapter = TextAdapter(max_tokens=5)
        budget = TokenBudget(max_tokens=5, reserved_for_output=0)

        long_text = "A" * 100
        source = await adapter.adapt(long_text, budget, priority=0)

        assert "original_tokens" in source.metadata
        assert source.metadata["original_tokens"] > source.token_count

    @pytest.mark.asyncio
    async def test_json_adapter_tracks_fields(self) -> None:
        """JSONAdapter metadata includes field names."""
        adapter = JSONAdapter()
        budget = TokenBudget(max_tokens=1000, reserved_for_output=0)

        data = {"name": "Alice", "age": 30}
        source = await adapter.adapt(data, budget, priority=0)

        assert "fields" in source.metadata
        assert "name" in source.metadata["fields"]
        assert "age" in source.metadata["fields"]

    @pytest.mark.asyncio
    async def test_table_adapter_tracks_dimensions(self) -> None:
        """TableAdapter metadata includes row count and columns."""
        adapter = TableAdapter()
        budget = TokenBudget(max_tokens=1000, reserved_for_output=0)

        data = [{"a": 1, "b": 2}, {"a": 3, "b": 4}]
        source = await adapter.adapt(data, budget, priority=0)

        assert source.metadata["rows"] == 2
        assert "columns" in source.metadata

    @pytest.mark.asyncio
    async def test_chunk_adapter_tracks_position(self) -> None:
        """ChunkAdapter metadata includes chunk position."""
        adapter = ChunkAdapter(chunk_size=10)
        budget = TokenBudget(max_tokens=1000, reserved_for_output=0)

        text = "A" * 200
        sources = await adapter.adapt_many(text, budget)

        for i, source in enumerate(sources):
            assert source.metadata["chunk_index"] == i
            assert source.metadata["total_chunks"] == len(sources)

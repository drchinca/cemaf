"""
Tests for context source abstraction.
"""

from datetime import UTC, datetime, timedelta

from cemaf.context.source import CompiledContext, ContextSource
from cemaf.core.types import TokenCount


class TestContextSource:
    """Tests for ContextSource."""

    def test_create_basic_source(self):
        """Create a basic context source."""
        source = ContextSource(
            content="Test content",
            priority=5,
            source_type="test",
        )

        assert source.content == "Test content"
        assert source.priority == 5
        assert source.source_type == "test"
        assert source.compressible is True  # Default

    def test_create_source_with_all_fields(self):
        """Create source with all fields."""
        timestamp = datetime.now(UTC)
        source = ContextSource(
            content="Full content",
            priority=10,
            timestamp=timestamp,
            source_type="document",
            source_id="doc123",
            token_count=TokenCount(100),
            compressible=False,
            min_tokens=50,
            metadata={"key": "value"},
        )

        assert source.content == "Full content"
        assert source.priority == 10
        assert source.timestamp == timestamp
        assert source.source_type == "document"
        assert source.source_id == "doc123"
        assert source.token_count == TokenCount(100)
        assert source.compressible is False
        assert source.min_tokens == 50
        assert source.metadata == {"key": "value"}

    def test_from_tool_output(self):
        """Create source from tool output."""
        source = ContextSource.from_tool_output(
            content="Tool result",
            tool_name="web_search",
            priority=8,
            compressible=True,
        )

        assert source.content == "Tool result"
        assert source.priority == 8
        assert source.source_type == "tool_output"
        assert source.source_id == "web_search"
        assert source.compressible is True
        assert source.metadata["tool"] == "web_search"

    def test_from_document(self):
        """Create source from document."""
        timestamp = datetime(2024, 1, 1, tzinfo=UTC)
        source = ContextSource.from_document(
            content="Document content",
            document_id="doc456",
            priority=3,
            timestamp=timestamp,
        )

        assert source.content == "Document content"
        assert source.priority == 3
        assert source.source_type == "document"
        assert source.source_id == "doc456"
        assert source.timestamp == timestamp
        assert source.metadata["document_id"] == "doc456"

    def test_from_memory(self):
        """Create source from memory."""
        source = ContextSource.from_memory(
            content="Memory content",
            memory_key="user_profile",
            priority=7,
        )

        assert source.content == "Memory content"
        assert source.priority == 7
        assert source.source_type == "memory"
        assert source.source_id == "user_profile"
        assert source.compressible is False  # Memories not compressible by default
        assert source.metadata["memory_key"] == "user_profile"

    def test_from_system_prompt(self):
        """Create source from system prompt."""
        source = ContextSource.from_system_prompt(
            content="System instructions",
            priority=100,
        )

        assert source.content == "System instructions"
        assert source.priority == 100
        assert source.source_type == "system"
        assert source.source_id == "system_prompt"
        assert source.compressible is False
        assert source.metadata["critical"] is True

    def test_with_priority(self):
        """Update source priority."""
        source = ContextSource(content="Test", priority=5)
        new_source = source.with_priority(10)

        assert source.priority == 5  # Original unchanged
        assert new_source.priority == 10
        assert new_source.content == "Test"

    def test_with_token_count(self):
        """Update source token count."""
        source = ContextSource(content="Test", token_count=None)
        new_source = source.with_token_count(TokenCount(50))

        assert source.token_count is None  # Original unchanged
        assert new_source.token_count == TokenCount(50)
        assert new_source.content == "Test"

    def test_age_seconds(self):
        """Calculate source age."""
        past_time = datetime.now(UTC) - timedelta(hours=2)
        source = ContextSource(content="Test", timestamp=past_time)

        age = source.age_seconds()

        # Should be approximately 2 hours = 7200 seconds
        assert age >= 7199  # Allow for small timing variations
        assert age <= 7201

    def test_age_seconds_with_reference(self):
        """Calculate age with custom reference time."""
        timestamp = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
        reference = datetime(2024, 1, 1, 14, 0, 0, tzinfo=UTC)

        source = ContextSource(content="Test", timestamp=timestamp)
        age = source.age_seconds(reference_time=reference)

        assert age == 7200  # Exactly 2 hours

    def test_source_sorting_by_priority(self):
        """Sort sources by priority (higher first)."""
        source1 = ContextSource(content="Low", priority=1)
        source2 = ContextSource(content="High", priority=10)
        source3 = ContextSource(content="Medium", priority=5)

        sources = sorted([source1, source2, source3])

        assert sources[0].priority == 10
        assert sources[1].priority == 5
        assert sources[2].priority == 1

    def test_source_sorting_by_timestamp(self):
        """Sort sources by timestamp when priority is same."""
        old_time = datetime(2024, 1, 1, tzinfo=UTC)
        new_time = datetime(2024, 1, 2, tzinfo=UTC)

        source1 = ContextSource(content="Old", priority=5, timestamp=old_time)
        source2 = ContextSource(content="New", priority=5, timestamp=new_time)

        sources = sorted([source1, source2])

        # Newer first
        assert sources[0].content == "New"
        assert sources[1].content == "Old"

    def test_source_repr(self):
        """Source representation."""
        source = ContextSource(
            content="Test",
            source_type="document",
            source_id="doc123",
            priority=5,
            token_count=TokenCount(100),
        )

        repr_str = repr(source)

        assert "ContextSource" in repr_str
        assert "document" in repr_str
        assert "doc123" in repr_str
        assert "priority=5" in repr_str
        assert "tokens=100" in repr_str


class TestCompiledContext:
    """Tests for CompiledContext."""

    def test_create_compiled_context(self):
        """Create a compiled context."""
        source1 = ContextSource(content="Content 1", priority=10)
        source2 = ContextSource(content="Content 2", priority=5)

        compiled = CompiledContext(
            sources=(source1, source2),
            total_tokens=TokenCount(150),
        )

        assert compiled.source_count == 2
        assert compiled.total_tokens == TokenCount(150)

    def test_compiled_context_content(self):
        """Get concatenated content."""
        source1 = ContextSource(content="First part", priority=10)
        source2 = ContextSource(content="Second part", priority=5)

        compiled = CompiledContext(
            sources=(source1, source2),
            total_tokens=TokenCount(100),
        )

        assert compiled.content == "First part\n\nSecond part"

    def test_compiled_context_with_excluded(self):
        """Compiled context with excluded sources."""
        included1 = ContextSource(content="Included 1", priority=10)
        included2 = ContextSource(content="Included 2", priority=8)
        excluded1 = ContextSource(content="Excluded", priority=1)

        compiled = CompiledContext(
            sources=(included1, included2),
            total_tokens=TokenCount(100),
            excluded_sources=(excluded1,),
        )

        assert compiled.source_count == 2
        assert len(compiled.excluded_sources) == 1
        assert "Excluded" not in compiled.content

    def test_compiled_context_with_compressed(self):
        """Compiled context with compressed sources."""
        normal = ContextSource(content="Normal", priority=10)
        compressed = ContextSource(content="Summary", priority=5)

        compiled = CompiledContext(
            sources=(normal, compressed),
            total_tokens=TokenCount(80),
            compressed_sources=(compressed,),
            metadata={"compression_ratio": 0.5},
        )

        assert compiled.source_count == 2
        assert len(compiled.compressed_sources) == 1
        assert compiled.metadata["compression_ratio"] == 0.5

    def test_utilization_ratio(self):
        """Calculate budget utilization ratio."""
        source = ContextSource(content="Test", priority=10)

        compiled = CompiledContext(
            sources=(source,),
            total_tokens=TokenCount(750),
            metadata={"budget": 1000},
        )

        assert compiled.utilization_ratio == 0.75

    def test_utilization_ratio_no_budget(self):
        """Utilization ratio without budget."""
        source = ContextSource(content="Test", priority=10)

        compiled = CompiledContext(
            sources=(source,),
            total_tokens=TokenCount(100),
        )

        assert compiled.utilization_ratio == 0.0

    def test_compiled_context_repr(self):
        """Compiled context representation."""
        source = ContextSource(content="Test", priority=10)
        excluded = ContextSource(content="Excluded", priority=1)

        compiled = CompiledContext(
            sources=(source,),
            total_tokens=TokenCount(100),
            excluded_sources=(excluded,),
        )

        repr_str = repr(compiled)

        assert "CompiledContext" in repr_str
        assert "sources=1" in repr_str
        assert "tokens=100" in repr_str
        assert "excluded=1" in repr_str


class TestSourcePriorities:
    """Tests for different source type priorities."""

    def test_system_prompt_highest_priority(self):
        """System prompts have highest default priority."""
        system = ContextSource.from_system_prompt("System")
        memory = ContextSource.from_memory("Memory", "key")
        tool = ContextSource.from_tool_output("Tool", "search")
        doc = ContextSource.from_document("Doc", "id")

        sources = sorted([doc, tool, memory, system])

        # System should be first (highest priority)
        assert sources[0].source_type == "system"
        assert sources[1].source_type == "memory"
        assert sources[2].source_type == "tool_output"
        assert sources[3].source_type == "document"

    def test_custom_priorities(self):
        """Override default priorities."""
        high_doc = ContextSource.from_document("Important doc", "id", priority=50)
        low_tool = ContextSource.from_tool_output("Tool", "search", priority=1)

        sources = sorted([low_tool, high_doc])

        # High priority doc should come first
        assert sources[0].source_type == "document"
        assert sources[1].source_type == "tool_output"


class TestCompressibility:
    """Tests for source compressibility."""

    def test_tool_output_compressible(self):
        """Tool outputs are compressible by default."""
        source = ContextSource.from_tool_output("Content", "tool")
        assert source.compressible is True

    def test_document_compressible(self):
        """Documents are compressible by default."""
        source = ContextSource.from_document("Content", "id")
        assert source.compressible is True

    def test_memory_not_compressible(self):
        """Memories are not compressible by default."""
        source = ContextSource.from_memory("Content", "key")
        assert source.compressible is False

    def test_system_not_compressible(self):
        """System prompts are not compressible."""
        source = ContextSource.from_system_prompt("Content")
        assert source.compressible is False

    def test_override_compressibility(self):
        """Override default compressibility."""
        # Make tool output non-compressible
        source = ContextSource.from_tool_output("Content", "tool", compressible=False)
        assert source.compressible is False


class TestRealWorldScenarios:
    """Tests for real-world usage scenarios."""

    def test_multi_source_compilation(self):
        """Compile context from multiple source types."""
        system = ContextSource.from_system_prompt(
            "You are a helpful assistant",
            priority=100,
        )

        memory = ContextSource.from_memory(
            "User prefers concise answers",
            "user_preferences",
            priority=80,
        )

        search_results = ContextSource.from_tool_output(
            "Search found: ...",
            "web_search",
            priority=60,
        )

        document = ContextSource.from_document(
            "Reference material: ...",
            "doc123",
            priority=40,
        )

        sources = sorted([document, search_results, memory, system])

        # Check priority order
        assert sources[0].source_type == "system"
        assert sources[1].source_type == "memory"
        assert sources[2].source_type == "tool_output"
        assert sources[3].source_type == "document"

    def test_token_budget_scenario(self):
        """Simulate token budget compilation."""
        sources = [
            ContextSource.from_system_prompt("System", priority=100).with_token_count(TokenCount(50)),
            ContextSource.from_memory("Memory", "key", priority=80).with_token_count(TokenCount(100)),
            ContextSource.from_tool_output("Tool1", "search", priority=60).with_token_count(TokenCount(200)),
            ContextSource.from_tool_output("Tool2", "scrape", priority=40).with_token_count(TokenCount(300)),
        ]

        # Simulate selection with budget of 400 tokens
        budget = 400
        selected = []
        total = 0

        for source in sorted(sources):
            if total + source.token_count <= budget:
                selected.append(source)
                total += source.token_count

        compiled = CompiledContext(
            sources=tuple(selected),
            total_tokens=TokenCount(total),
            excluded_sources=tuple(s for s in sources if s not in selected),
            metadata={"budget": budget},
        )

        # Should include system, memory, and tool1 (total 350 tokens)
        # Excludes tool2 (would exceed budget)
        assert compiled.source_count == 3
        assert compiled.total_tokens == 350
        assert len(compiled.excluded_sources) == 1

    def test_recency_based_selection(self):
        """Select sources based on recency."""
        now = datetime.now(UTC)
        hour_ago = now - timedelta(hours=1)
        day_ago = now - timedelta(days=1)

        recent = ContextSource(content="Recent", priority=5, timestamp=now)
        medium = ContextSource(content="Hour old", priority=5, timestamp=hour_ago)
        old = ContextSource(content="Day old", priority=5, timestamp=day_ago)

        sources = sorted([old, medium, recent])

        # Should be sorted newest first (when priority is same)
        assert sources[0].content == "Recent"
        assert sources[1].content == "Hour old"
        assert sources[2].content == "Day old"

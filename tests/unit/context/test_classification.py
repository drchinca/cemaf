"""Unit tests for context type classification."""

import pytest

from cemaf.context.classification import (
    CONTEXT_TYPE_BEHAVIORS,
    classify_source,
    get_behavior,
)
from cemaf.context.source import ContextSource, ContextType


class TestContextType:
    """ContextType enum tests."""

    def test_all_types_have_behaviors(self) -> None:
        for ct in ContextType:
            assert ct in CONTEXT_TYPE_BEHAVIORS


class TestClassifySource:
    """Contract: classify_source maps all existing source types correctly."""

    @pytest.mark.parametrize(
        ("source_type", "expected"),
        [
            ("document", ContextType.RESOURCE),
            ("tool_output", ContextType.RESOURCE),
            ("memory", ContextType.MEMORY),
            ("system", ContextType.SKILL),
        ],
    )
    def test_maps_all_existing_types(self, source_type: str, expected: ContextType) -> None:
        assert classify_source(source_type=source_type) == expected

    def test_unknown_defaults_to_resource(self) -> None:
        assert classify_source(source_type="unknown_type") == ContextType.RESOURCE


class TestGetBehavior:
    """Contract: behavioral rules for each context type."""

    def test_skill_is_not_compressible(self) -> None:
        behavior = get_behavior(context_type=ContextType.SKILL)
        assert behavior.compressible is False

    def test_resource_is_cacheable_and_compressible(self) -> None:
        behavior = get_behavior(context_type=ContextType.RESOURCE)
        assert behavior.cacheable is True
        assert behavior.compressible is True

    def test_memory_is_not_shareable(self) -> None:
        behavior = get_behavior(context_type=ContextType.MEMORY)
        assert behavior.shareable is False

    def test_memory_has_ttl(self) -> None:
        behavior = get_behavior(context_type=ContextType.MEMORY)
        assert behavior.default_ttl_seconds == 86400.0

    def test_skill_preferred_compaction_is_full(self) -> None:
        behavior = get_behavior(context_type=ContextType.SKILL)
        assert behavior.preferred_compaction == "full"


class TestContextSourceFactoryMethods:
    """Contract: factory methods auto-set context_type."""

    def test_from_memory_sets_type(self) -> None:
        source = ContextSource.from_memory(content="test", memory_key="k")
        assert source.context_type == ContextType.MEMORY

    def test_from_document_sets_type(self) -> None:
        source = ContextSource.from_document(content="test", document_id="d")
        assert source.context_type == ContextType.RESOURCE

    def test_from_tool_output_sets_type(self) -> None:
        source = ContextSource.from_tool_output(content="test", tool_name="t")
        assert source.context_type == ContextType.RESOURCE

    def test_from_system_prompt_sets_type(self) -> None:
        source = ContextSource.from_system_prompt(content="test")
        assert source.context_type == ContextType.SKILL

    def test_default_constructor_has_none(self) -> None:
        source = ContextSource(content="test")
        assert source.context_type is None

    def test_with_priority_preserves_context_type(self) -> None:
        source = ContextSource.from_memory(content="test", memory_key="k")
        updated = source.with_priority(priority=99)
        assert updated.context_type == ContextType.MEMORY

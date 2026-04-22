"""Tests for ContextType.SPEC and ContextSource.from_spec()."""

from __future__ import annotations

from cemaf.context.source import ContextSource, ContextType


def test_spec_context_type_exists() -> None:
    assert ContextType.SPEC.value == "spec"


def test_from_spec_is_incompressible() -> None:
    source = ContextSource.from_spec(
        content="## ADDED Requirements\n### Requirement: R\n",
        spec_id="specs/cemaf/core/spec.md",
    )
    assert source.compressible is False
    assert source.context_type is ContextType.SPEC


def test_from_spec_carries_metadata() -> None:
    source = ContextSource.from_spec(
        content="x",
        spec_id="specs/cemaf/meta/spec.md",
        change_id="add-meta-specifier",
        capability="meta",
    )
    assert source.metadata["change_id"] == "add-meta-specifier"
    assert source.metadata["capability"] == "meta"
    assert source.source_type == "spec"


def test_from_spec_priority_higher_than_memory() -> None:
    spec = ContextSource.from_spec(content="x", spec_id="s")
    memory = ContextSource.from_memory(content="x", memory_key="k")
    assert spec.priority > memory.priority

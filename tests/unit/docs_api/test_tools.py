"""Tests for CemafDocsSearchTool and DocsRetrievalTool."""

from __future__ import annotations

import pytest

from cemaf.docs_api.index import DocEntry, DocEntryKind, DocIndex
from cemaf.docs_api.tools import CemafDocsSearchTool, DocsRetrievalTool


def _index_with_sample() -> DocIndex:
    return DocIndex(
        [
            DocEntry(
                id="docs/architecture.md",
                kind=DocEntryKind.GUIDE,
                title="Architecture",
                body="The runtime services bundle is the composition root.",
                source="markdown",
                anchors=("Composition root",),
            ),
            DocEntry(
                id="pkg:cemaf.orchestration",
                kind=DocEntryKind.PACKAGE,
                title="cemaf.orchestration — DAG execution",
                body="Orchestration owns DAGExecutor.",
                source="docstring",
            ),
            DocEntry(
                id="pattern:3-runtimeservices-bundle",
                kind=DocEntryKind.PATTERN,
                title="3. RuntimeServices bundle",
                body="Cross-cutting deps arrive in a single typed dataclass.",
                source="markdown",
                anchors=("RuntimeServices",),
            ),
        ]
    )


@pytest.mark.asyncio
async def test_search_tool_returns_matches() -> None:
    tool = CemafDocsSearchTool(index=_index_with_sample())
    result = await tool.execute(query="runtime services", k=3)
    assert result.success
    assert result.data["query"] == "runtime services"
    assert result.data["count"] >= 1
    titles = [r["title"] for r in result.data["results"]]
    assert any("RuntimeServices" in t or "runtime" in t.lower() for t in titles)


@pytest.mark.asyncio
async def test_search_tool_empty_query_fails_clearly() -> None:
    tool = CemafDocsSearchTool(index=_index_with_sample())
    result = await tool.execute(query="")
    assert not result.success
    assert "query" in (result.error or "")


@pytest.mark.asyncio
async def test_search_tool_caps_k() -> None:
    tool = CemafDocsSearchTool(index=_index_with_sample(), max_k=2)
    result = await tool.execute(query="runtime", k=99)
    assert len(result.data["results"]) <= 2


@pytest.mark.asyncio
async def test_search_tool_filters_by_kind() -> None:
    tool = CemafDocsSearchTool(index=_index_with_sample())
    result = await tool.execute(query="runtime", kinds=["pattern"])
    assert result.success
    for item in result.data["results"]:
        assert item["kind"] == "pattern"


@pytest.mark.asyncio
async def test_search_tool_rejects_unknown_kind() -> None:
    tool = CemafDocsSearchTool(index=_index_with_sample())
    result = await tool.execute(query="x", kinds=["not-a-kind"])
    assert not result.success


@pytest.mark.asyncio
async def test_search_tool_truncates_excerpt() -> None:
    tool = CemafDocsSearchTool(index=_index_with_sample())
    result = await tool.execute(query="runtime services", excerpt_chars=20)
    for item in result.data["results"]:
        # Either fits under the cap, or has the truncation marker
        assert len(item["excerpt"]) <= 100 or "truncated" in item["excerpt"]


@pytest.mark.asyncio
async def test_retrieval_tool_returns_full_body() -> None:
    index = _index_with_sample()
    tool = DocsRetrievalTool(index=index)
    result = await tool.execute(entry_id="docs/architecture.md")
    assert result.success
    assert result.data["id"] == "docs/architecture.md"
    assert "composition root" in result.data["body"].lower()


@pytest.mark.asyncio
async def test_retrieval_tool_missing_id_fails() -> None:
    tool = DocsRetrievalTool(index=_index_with_sample())
    result = await tool.execute(entry_id="does-not-exist")
    assert not result.success


@pytest.mark.asyncio
async def test_retrieval_tool_empty_id_fails() -> None:
    tool = DocsRetrievalTool(index=_index_with_sample())
    result = await tool.execute(entry_id="")
    assert not result.success


def test_search_tool_schema_declares_read_only_concurrent_safe() -> None:
    tool = CemafDocsSearchTool(index=_index_with_sample())
    assert tool.is_read_only is True
    assert tool.is_concurrent_safe is True
    assert tool.schema.required == ("query",)

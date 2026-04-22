"""Tests for the CEMAF docs MCP server wrapper."""

from __future__ import annotations

import pytest

from cemaf.docs_api.index import DocEntry, DocEntryKind, DocIndex
from cemaf.docs_api.mcp_server import create_docs_mcp_server
from cemaf.mcp.mock import MockTransport
from cemaf.mcp.protocols import MCPRequest


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
                id="pattern:4-composition-root",
                kind=DocEntryKind.PATTERN,
                title="4. Composition root",
                body="Exactly one place wires the executor.",
                source="markdown",
            ),
        ]
    )


@pytest.mark.asyncio
async def test_server_exposes_both_tools() -> None:
    server = create_docs_mcp_server(index=_index_with_sample(), transport=MockTransport())
    response = await server.handle_request(request=MCPRequest(method="tools/list", id=1))
    assert response.is_success
    tool_names = {t["name"] for t in response.result["tools"]}
    assert "cemaf_docs_search" in tool_names
    assert "cemaf_docs_get" in tool_names


@pytest.mark.asyncio
async def test_server_calls_search_tool_end_to_end() -> None:
    server = create_docs_mcp_server(index=_index_with_sample(), transport=MockTransport())
    response = await server.handle_request(
        request=MCPRequest(
            method="tools/call",
            params={
                "name": "cemaf_docs_search",
                "arguments": {"query": "composition root runtime", "k": 2},
            },
            id=2,
        )
    )
    assert response.is_success
    # Tool result is wrapped in MCP format — content is a list of content items
    content = response.result["content"]
    assert isinstance(content, list)
    assert len(content) > 0


@pytest.mark.asyncio
async def test_server_calls_get_tool_end_to_end() -> None:
    server = create_docs_mcp_server(index=_index_with_sample(), transport=MockTransport())
    response = await server.handle_request(
        request=MCPRequest(
            method="tools/call",
            params={
                "name": "cemaf_docs_get",
                "arguments": {"entry_id": "docs/architecture.md"},
            },
            id=3,
        )
    )
    assert response.is_success
    content = response.result["content"]
    text = str(content)
    assert "Architecture" in text or "architecture" in text


@pytest.mark.asyncio
async def test_server_unknown_tool_returns_error() -> None:
    server = create_docs_mcp_server(index=_index_with_sample(), transport=MockTransport())
    response = await server.handle_request(
        request=MCPRequest(
            method="tools/call",
            params={"name": "nonexistent_tool", "arguments": {}},
            id=4,
        )
    )
    # Unknown tool: either error or an isError=True result — either shape
    # signals to the client that the call failed.
    is_error = response.error is not None or (
        response.result is not None and response.result.get("isError") is True
    )
    assert is_error

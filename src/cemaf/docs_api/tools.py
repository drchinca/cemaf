"""CEMAF Tools exposing the DocIndex to agents and MCP clients."""

from __future__ import annotations

from typing import Any

from cemaf.core.result import Result
from cemaf.core.types import ToolID
from cemaf.docs_api.index import DocEntry, DocEntryKind, DocIndex
from cemaf.tools.base import Tool, ToolResult, ToolSchema


def _entry_to_dict(*, entry: DocEntry, score: float | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": entry.id,
        "kind": entry.kind.value,
        "title": entry.title,
        "source": entry.source,
        "path": entry.path,
        "anchors": list(entry.anchors),
    }
    if score is not None:
        out["score"] = score
    return out


def _truncate(body: str, *, max_chars: int) -> str:
    if len(body) <= max_chars:
        return body
    return body[:max_chars].rstrip() + "\n\n… [truncated]"


class CemafDocsSearchTool(Tool):
    """Search CEMAF's own documentation. Returns top-k matches with excerpts."""

    def __init__(
        self,
        *,
        index: DocIndex,
        default_excerpt_chars: int = 600,
        max_k: int = 25,
    ) -> None:
        self._index = index
        self._default_excerpt_chars = default_excerpt_chars
        self._max_k = max_k

    @property
    def id(self) -> ToolID:
        return ToolID("cemaf_docs_search")

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="cemaf_docs_search",
            description=(
                "Search CEMAF's own documentation (guides under docs/, "
                "package/module docstrings, design-pattern sections). Returns "
                "top-k matches ranked by weighted keyword overlap. Use this "
                "when you need to understand how a CEMAF primitive, pattern, "
                "or module is meant to be used."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Natural-language or keyword query (required).",
                    },
                    "k": {
                        "type": "integer",
                        "description": "Max results to return (default 5, capped at max_k).",
                        "default": 5,
                    },
                    "kinds": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Optional filter: restrict to kinds "
                            "('guide', 'package', 'module', 'pattern', 'spec')."
                        ),
                    },
                    "excerpt_chars": {
                        "type": "integer",
                        "description": "Chars of body to include per result (default 600).",
                    },
                },
            },
            required=("query",),
            is_read_only=True,
            is_concurrent_safe=True,
        )

    @property
    def is_read_only(self) -> bool:
        return True

    @property
    def is_concurrent_safe(self) -> bool:
        return True

    async def execute(self, **kwargs: Any) -> ToolResult:
        query = kwargs.get("query", "")
        if not isinstance(query, str) or not query.strip():
            return Result.fail(error="query is required and must be a non-empty string")
        k = int(kwargs.get("k", 5))
        if k < 1:
            k = 1
        if k > self._max_k:
            k = self._max_k
        excerpt_chars = int(kwargs.get("excerpt_chars", self._default_excerpt_chars))
        if excerpt_chars < 0:
            excerpt_chars = self._default_excerpt_chars

        kinds_raw = kwargs.get("kinds")
        kinds: tuple[DocEntryKind, ...] | None = None
        if kinds_raw:
            try:
                kinds = tuple(DocEntryKind(k) for k in kinds_raw)
            except ValueError as exc:
                return Result.fail(error=f"unknown kind: {exc}")

        matches = self._index.search(query=query, k=k, kinds=kinds)
        results: list[dict[str, Any]] = []
        for entry, score in matches:
            record = _entry_to_dict(entry=entry, score=score)
            record["excerpt"] = _truncate(entry.body, max_chars=excerpt_chars)
            results.append(record)

        return Result.ok(
            data={"query": query, "count": len(results), "results": results},
            metadata={"index_size": len(self._index)},
        )


class DocsRetrievalTool(Tool):
    """Fetch a single DocEntry by id (for follow-up after a search hit)."""

    def __init__(self, *, index: DocIndex) -> None:
        self._index = index

    @property
    def id(self) -> ToolID:
        return ToolID("cemaf_docs_get")

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="cemaf_docs_get",
            description=(
                "Fetch the full body of a CEMAF doc entry by id (e.g. "
                "'docs/architecture.md', 'pkg:cemaf.orchestration', "
                "'mod:cemaf.llm.anthropic', 'pattern:3-runtimeservices-bundle')."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "entry_id": {
                        "type": "string",
                        "description": "The entry id returned by cemaf_docs_search.",
                    },
                },
            },
            required=("entry_id",),
            is_read_only=True,
            is_concurrent_safe=True,
        )

    @property
    def is_read_only(self) -> bool:
        return True

    @property
    def is_concurrent_safe(self) -> bool:
        return True

    async def execute(self, **kwargs: Any) -> ToolResult:
        entry_id = kwargs.get("entry_id", "")
        if not isinstance(entry_id, str) or not entry_id:
            return Result.fail(error="entry_id is required")
        entry = self._index.get(entry_id)
        if entry is None:
            return Result.fail(error=f"no entry with id: {entry_id}")
        record = _entry_to_dict(entry=entry)
        record["body"] = entry.body
        return Result.ok(data=record)


__all__ = ["CemafDocsSearchTool", "DocsRetrievalTool"]

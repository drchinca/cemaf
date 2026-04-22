"""Docs API — expose CEMAF's own docs + docstrings to LLMs.

The self-hosting loop closed: agents reasoning about how to use CEMAF can
look up CEMAF's documentation as a first-class resource. Works standalone
(Python API), as a CEMAF Tool (register via ToolRegistry), or as an MCP
server (drop into any MCP-speaking client).

Key types:
- `DocEntry` — one indexable unit: kind, id, title, body, anchors, metadata
- `DocEntryKind` — GUIDE (markdown doc), PACKAGE (package docstring),
  MODULE (module docstring), PATTERN (section in docs/patterns.md)
- `DocIndex` — the searchable corpus + lookup-by-id
- `DocSource` protocol — pluggable ingestion (markdown files, docstrings,
  BYO source for other doc systems)
- `MarkdownDocSource` — reads `docs/**/*.md`
- `PackageDocstringSource` — reflects over `cemaf.*.__doc__`
- `CemafDocsSearchTool` — keyword+substring search as a CEMAF Tool
- `DocsRetrievalTool` — fetch a single entry by id

Usage (standalone):
    from cemaf.docs_api import build_default_index

    index = build_default_index()
    results = index.search("how do I wire a runtime services bundle", k=5)
    for entry, score in results:
        print(f"{entry.title}  [{entry.id}]  (score={score:.2f})")

Usage (as a Tool):
    from cemaf.docs_api.tools import CemafDocsSearchTool

    tool_registry.register_instance(item=CemafDocsSearchTool(index=index))

Usage (via MCP):
    cemaf-docs serve        # stdio MCP server
"""

from cemaf.docs_api.index import (
    DocEntry,
    DocEntryKind,
    DocIndex,
    build_default_index,
)
from cemaf.docs_api.protocols import DocSource
from cemaf.docs_api.sources import (
    MarkdownDocSource,
    PackageDocstringSource,
)
from cemaf.docs_api.tools import CemafDocsSearchTool, DocsRetrievalTool

__all__ = [
    "CemafDocsSearchTool",
    "DocEntry",
    "DocEntryKind",
    "DocIndex",
    "DocSource",
    "DocsRetrievalTool",
    "MarkdownDocSource",
    "PackageDocstringSource",
    "build_default_index",
]

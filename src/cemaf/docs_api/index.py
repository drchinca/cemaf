"""DocIndex — searchable corpus of CEMAF documentation entries."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

from cemaf.core.types import JSON

if TYPE_CHECKING:
    from cemaf.docs_api.protocols import DocSource


class DocEntryKind(str, Enum):
    """What kind of documentation this entry represents."""

    GUIDE = "guide"  # A full markdown doc under docs/
    PACKAGE = "package"  # A package's __init__.py docstring
    MODULE = "module"  # A single module's docstring
    PATTERN = "pattern"  # A section within docs/patterns.md
    SPEC = "spec"  # An OpenSpec proposal or capability delta


@dataclass(frozen=True, slots=True)
class DocEntry:
    """One addressable documentation record.

    Entries are the unit of search and retrieval. Each has a stable `id`
    (used for direct fetches and cross-references in search results), a
    human-readable `title`, and a `body` of markdown content.
    """

    id: str
    kind: DocEntryKind
    title: str
    body: str
    source: str = ""  # Which DocSource produced this (e.g. "markdown", "docstring")
    path: str = ""  # Filesystem path (when applicable)
    anchors: tuple[str, ...] = field(default_factory=tuple)
    metadata: JSON = field(default_factory=dict)


_CAMEL_SPLIT_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_WORD_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> set[str]:
    """Tokenize into lowercase alphanumeric tokens.

    Splits camelCase and PascalCase so `RuntimeServices` matches both
    `runtime` and `services` — CEMAF docs use camelCase identifiers
    heavily, and queries are natural-language separate words.
    """
    # Insert spaces at camelCase boundaries first, then lowercase + tokenize.
    camel_split = _CAMEL_SPLIT_RE.sub(" ", text)
    return set(_WORD_RE.findall(camel_split.lower()))


class DocIndex:
    """In-memory corpus + keyword search over DocEntry records.

    Scoring is a simple weighted-overlap: each query token contributes
    its match count in title (×3) + anchors (×2) + body (×1). Deterministic
    and transparent — no embedding model required. For semantic search,
    wrap with a vector backend via the same DocSource protocol.

    The index is append-only after construction: build once, query many.
    """

    def __init__(self, entries: Iterable[DocEntry] = ()) -> None:
        self._entries: dict[str, DocEntry] = {}
        for entry in entries:
            self.add(entry=entry)

    def add(self, *, entry: DocEntry) -> None:
        """Append an entry. Duplicate ids overwrite — later add wins."""
        self._entries[entry.id] = entry

    def add_from(self, *, sources: Iterable[DocSource]) -> None:
        """Ingest every entry from each source."""
        for source in sources:
            for entry in source.load():
                self.add(entry=entry)

    def get(self, entry_id: str) -> DocEntry | None:
        return self._entries.get(entry_id)

    def all(self) -> tuple[DocEntry, ...]:
        return tuple(self._entries.values())

    def __len__(self) -> int:
        return len(self._entries)

    def search(
        self,
        *,
        query: str,
        k: int = 5,
        kinds: tuple[DocEntryKind, ...] | None = None,
    ) -> list[tuple[DocEntry, float]]:
        """Return top-k entries ranked by weighted token overlap.

        Empty query returns an empty list (no "return everything" footgun).
        `kinds` filter restricts to a subset (e.g. only PATTERN entries).
        Results are sorted by score descending, then by entry.id for stable
        tie-breaks.
        """
        query_tokens = _tokenize(query)
        if not query_tokens:
            return []

        scored: list[tuple[DocEntry, float]] = []
        for entry in self._entries.values():
            if kinds is not None and entry.kind not in kinds:
                continue
            title_tokens = _tokenize(entry.title)
            anchor_tokens: set[str] = set()
            for anchor in entry.anchors:
                anchor_tokens.update(_tokenize(anchor))
            body_tokens = _tokenize(entry.body)

            title_hits = len(query_tokens & title_tokens)
            anchor_hits = len(query_tokens & anchor_tokens)
            body_hits = len(query_tokens & body_tokens)
            score = float(3 * title_hits + 2 * anchor_hits + body_hits)
            if score > 0:
                scored.append((entry, score))

        scored.sort(key=lambda pair: (-pair[1], pair[0].id))
        return scored[:k]


def build_default_index(repo_root: Path | None = None) -> DocIndex:
    """Compose the canonical CEMAF docs index.

    Sources:
    - `docs/*.md` via MarkdownDocSource
    - `docs/patterns.md` sections via MarkdownDocSource (as PATTERN entries)
    - Every package `__doc__` under `cemaf.*` via PackageDocstringSource

    `repo_root` defaults to the repo containing the installed `cemaf` package;
    passing it explicitly is useful for tests or out-of-tree doc trees.
    """
    from cemaf.docs_api.sources import MarkdownDocSource, PackageDocstringSource

    if repo_root is None:
        # Resolve to the repo root based on this file's location:
        #   .../cemaf/src/cemaf/docs_api/index.py -> .../cemaf
        repo_root = Path(__file__).resolve().parents[3]

    index = DocIndex()
    index.add_from(
        sources=(
            MarkdownDocSource(root=repo_root / "docs"),
            PackageDocstringSource(root_package="cemaf"),
        ),
    )
    return index

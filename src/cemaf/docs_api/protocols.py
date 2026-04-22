"""DocSource protocol — pluggable ingestion for the docs index."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol, runtime_checkable

from cemaf.docs_api.index import DocEntry


@runtime_checkable
class DocSource(Protocol):
    """A source of documentation entries.

    Implementations enumerate `DocEntry` records from a specific substrate
    (markdown files on disk, Python docstrings via reflection, an external
    knowledge base). The `DocIndex` composes any number of sources.

    Keep sources lazy-loading — `load()` is a synchronous generator so
    indexes can be built at import time without heavy I/O upfront.
    """

    @property
    def name(self) -> str:
        """Short identifier for this source (used in DocEntry metadata)."""
        ...

    def load(self) -> Iterable[DocEntry]:
        """Yield every entry this source produces. Called by DocIndex.build."""
        ...

"""Concrete `BlueprintSource` implementations.

`BlueprintLibrary` is substrate-agnostic — it ingests whatever a
`BlueprintSource` yields. This module ships two sources that cover the
common cases:

    InMemoryBlueprintSource  — hand-authored entries, usually for tests
                               or programmatic bootstrapping.

    JSONFileBlueprintSource  — a single JSON file containing a list of
                               entry records. Good fit for a checked-in
                               `blueprints/catalog.json` that teams edit
                               by hand and version-control alongside code.

Both are sync iterators; implementations that need I/O-heavy or
network-backed ingestion should wrap the protocol themselves and return a
plain list (or a generator) from `load()`.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from cemaf.blueprint.library import BlueprintEntry, BlueprintEntryKind


class InMemoryBlueprintSource:
    """A source backed by an in-memory tuple of entries.

    Useful for tests, programmatic bootstrap, and composing other sources
    (filter + map before ingestion). `name` appears in
    `BlueprintEntry.source` for provenance, so give it something
    descriptive.
    """

    def __init__(self, *, entries: Iterable[BlueprintEntry], name: str = "in-memory") -> None:
        self._entries = tuple(entries)
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    def load(self) -> Iterable[BlueprintEntry]:
        # Stamp source on entries that don't carry one yet, preserving explicit values.
        for entry in self._entries:
            if entry.source:
                yield entry
            else:
                yield dataclasses.replace(entry, source=self._name)


class JSONFileBlueprintSource:
    """Load entries from a single JSON file.

    File format — a top-level list of entry records:

        [
          {
            "id": "content/announcement",
            "kind": "snapshot",
            "title": "Product Announcement",
            "tags": ["content", "marketing"],
            "snapshot": { ...Blueprint.to_dict() output... }
          },
          {
            "id": "content/faq-builder",
            "kind": "factory",
            "title": "FAQ Builder",
            "factory_ref": "acme.blueprints:faq_builder"
          },
          {
            "id": "content/release-notes",
            "kind": "recipe",
            "title": "Release Notes",
            "recipe": { "name": "Release Notes", "goal": "..." }
          }
        ]

    Unknown keys are ignored (forward-compat); missing required keys
    raise a clear error at load time rather than at resolve time.
    """

    def __init__(self, *, path: Path, name: str | None = None) -> None:
        self._path = Path(path)
        self._name = name or f"json:{self._path.name}"

    @property
    def name(self) -> str:
        return self._name

    def load(self) -> Iterable[BlueprintEntry]:
        if not self._path.is_file():
            return  # Missing file is a no-op, same convention as docs_api sources.

        raw = json.loads(self._path.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            raise ValueError(f"{self._path}: top-level JSON must be a list of entry objects.")

        for i, record in enumerate(raw):
            if not isinstance(record, dict):
                raise ValueError(f"{self._path}[{i}]: entry must be a dict; got {type(record).__name__}.")
            yield self._record_to_entry(record=record, index=i)

    def _record_to_entry(self, *, record: dict[str, Any], index: int) -> BlueprintEntry:
        try:
            kind = BlueprintEntryKind(record["kind"])
        except (KeyError, ValueError) as exc:
            raise ValueError(
                f"{self._path}[{index}]: 'kind' must be one of "
                f"{[k.value for k in BlueprintEntryKind]}; got {record.get('kind')!r}"
            ) from exc

        try:
            return BlueprintEntry(
                id=record["id"],
                kind=kind,
                title=record["title"],
                description=record.get("description", ""),
                tags=tuple(record.get("tags", ())),
                source=record.get("source") or self._name,
                path=record.get("path", str(self._path)),
                version=record.get("version", "1.0"),
                snapshot=record.get("snapshot"),
                factory_ref=record.get("factory_ref"),
                recipe=record.get("recipe"),
                metadata=dict(record.get("metadata", {})),
            )
        except KeyError as exc:
            raise ValueError(f"{self._path}[{index}]: missing required field {exc.args[0]!r}") from exc


__all__ = ["InMemoryBlueprintSource", "JSONFileBlueprintSource"]

"""BlueprintLibrary — curated, searchable index of reusable Blueprints.

A `Blueprint` (see `cemaf.blueprint.core`) is CEMAF's unit of structured
prompt engineering — it carries a scene goal, style guide, context
entities, and execution policies. As the set of reusable blueprints grows
across a codebase, teams need a single service that answers three
questions without ceremony:

    1. *What blueprints exist* for a given task?  (discovery via `search`)
    2. *Who owns this one*, and where did it come from? (provenance via
       `BlueprintEntry.source` + `path`)
    3. *Give me the Blueprint object now.* (resolution via `resolve`)

The library doesn't care **how** a blueprint is stored. It accepts three
kinds of entries, each of which resolves to the same `Blueprint` type:

    SNAPSHOT — the entry carries a serialized `Blueprint` dict inline.
               Faithful replay, self-contained, immune to registry drift,
               but frozen at capture time.

    FACTORY  — the entry carries a dotted path `pkg.module:function` to
               a zero-argument callable returning a `Blueprint`. Always
               current (resolves live), but contributors must ship Python.

    RECIPE   — the entry carries a declarative dict that the library
               parses into a `Blueprint` at resolution time. Contributor-
               friendly (YAML/JSON), language-agnostic, but the library
               owns a small parser and its error surface.

All three coexist in one library; consumers read blueprints without
knowing which representation was used. The tradeoff is paid once at
registration time (which kind do we use?), not at every call site.

Usage:
    >>> from cemaf.blueprint.library import BlueprintLibrary, BlueprintEntry
    >>> library = BlueprintLibrary()
    >>> library.register(entry=BlueprintEntry.snapshot_entry(
    ...     id="content/announcement",
    ...     title="Product Announcement",
    ...     blueprint=my_blueprint,
    ...     tags=("content", "marketing"),
    ... ))
    >>> blueprint = library.resolve(entry_id="content/announcement")
    >>> print(blueprint.to_prompt())
"""

from __future__ import annotations

import importlib
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from cemaf.blueprint.core import Blueprint
from cemaf.blueprint.recipe import parse_recipe


class BlueprintEntryKind(str, Enum):
    """Representation of a `Blueprint` inside a `BlueprintEntry`.

    The kind tells the resolver which field holds the payload and which
    strategy to use to materialize a `Blueprint`. See module docstring for
    the tradeoff matrix.
    """

    SNAPSHOT = "snapshot"
    FACTORY = "factory"
    RECIPE = "recipe"


class BlueprintLibraryError(Exception):
    """Raised when a library operation violates an invariant.

    Subclassed for specific failure modes so callers can discriminate.
    """


class BlueprintIdCollision(BlueprintLibraryError):
    """Raised when registering an id already present without `overwrite=True`."""


class BlueprintNotFound(BlueprintLibraryError):
    """Raised when `resolve` is called with an unknown id."""


class BlueprintResolutionError(BlueprintLibraryError):
    """Raised when a valid entry fails to produce a `Blueprint`.

    Examples: FACTORY import path that doesn't exist, RECIPE missing
    required fields, SNAPSHOT that fails Pydantic validation.
    """


@dataclass(frozen=True, slots=True)
class BlueprintEntry:
    """One addressable blueprint record in the library.

    Exactly one of `snapshot`, `factory_ref`, or `recipe` is non-None,
    matching `kind`. The `__post_init__` check enforces that invariant at
    construction time so resolution logic can trust the discriminator.

    Prefer the factory classmethods (`snapshot_entry`, `factory_entry`,
    `recipe_entry`) over constructing this directly — they keep the
    discriminator and the payload in sync.
    """

    id: str
    kind: BlueprintEntryKind
    title: str
    description: str = ""
    tags: tuple[str, ...] = ()
    source: str = ""  # Which BlueprintSource produced this (provenance)
    path: str = ""  # Filesystem path (when applicable)
    version: str = "1.0"

    # Exactly one of these is populated based on `kind`:
    snapshot: dict[str, Any] | None = None
    factory_ref: str | None = None
    recipe: dict[str, Any] | None = None

    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        payload_map: dict[BlueprintEntryKind, Any] = {
            BlueprintEntryKind.SNAPSHOT: self.snapshot,
            BlueprintEntryKind.FACTORY: self.factory_ref,
            BlueprintEntryKind.RECIPE: self.recipe,
        }
        populated = {k for k, v in payload_map.items() if v is not None}
        if self.kind not in populated:
            raise BlueprintLibraryError(
                f"Entry {self.id!r} declares kind={self.kind.value} but its matching payload field is empty."
            )
        if populated - {self.kind}:
            extra = sorted(k.value for k in populated - {self.kind})
            raise BlueprintLibraryError(
                f"Entry {self.id!r} has kind={self.kind.value} but also "
                f"populated foreign payload(s): {extra}. Exactly one payload "
                f"field must match kind."
            )
        if not self.id:
            raise BlueprintLibraryError("Entry id must be non-empty.")
        if not self.title:
            raise BlueprintLibraryError("Entry title must be non-empty.")

    @classmethod
    def snapshot_entry(
        cls,
        *,
        id: str,
        title: str,
        blueprint: Blueprint,
        description: str = "",
        tags: tuple[str, ...] = (),
        source: str = "",
        path: str = "",
    ) -> BlueprintEntry:
        """Capture `blueprint` as an inline serialized snapshot."""
        return cls(
            id=id,
            kind=BlueprintEntryKind.SNAPSHOT,
            title=title,
            description=description,
            tags=tags,
            source=source,
            path=path,
            version=blueprint.version,
            snapshot=blueprint.to_dict(),
        )

    @classmethod
    def factory_entry(
        cls,
        *,
        id: str,
        title: str,
        factory_ref: str,
        description: str = "",
        tags: tuple[str, ...] = (),
        source: str = "",
        path: str = "",
        version: str = "1.0",
    ) -> BlueprintEntry:
        """Point at an importable zero-arg callable returning a Blueprint.

        `factory_ref` format: `"package.module:callable"` (colon separator,
        mirroring entry-point and Uvicorn/Gunicorn conventions).
        """
        if ":" not in factory_ref:
            raise BlueprintLibraryError(f"factory_ref must use 'module:callable' format, got {factory_ref!r}")
        return cls(
            id=id,
            kind=BlueprintEntryKind.FACTORY,
            title=title,
            description=description,
            tags=tags,
            source=source,
            path=path,
            version=version,
            factory_ref=factory_ref,
        )

    @classmethod
    def recipe_entry(
        cls,
        *,
        id: str,
        title: str,
        recipe: dict[str, Any],
        description: str = "",
        tags: tuple[str, ...] = (),
        source: str = "",
        path: str = "",
        version: str = "1.0",
    ) -> BlueprintEntry:
        """Store a declarative dict spec parsed into a Blueprint at resolve time."""
        return cls(
            id=id,
            kind=BlueprintEntryKind.RECIPE,
            title=title,
            description=description,
            tags=tags,
            source=source,
            path=path,
            version=version,
            recipe=dict(recipe),
        )


# =============================================================================
# Resolution — materialize a BlueprintEntry into a Blueprint.
# =============================================================================


def _resolve_snapshot(entry: BlueprintEntry) -> Blueprint:
    if entry.snapshot is None:
        raise BlueprintResolutionError(f"SNAPSHOT entry {entry.id!r}: payload missing (invariant violation).")
    try:
        return Blueprint.from_dict(data=entry.snapshot)
    except Exception as exc:
        raise BlueprintResolutionError(
            f"SNAPSHOT entry {entry.id!r} failed Blueprint validation: {exc}"
        ) from exc


def _resolve_factory(entry: BlueprintEntry) -> Blueprint:
    # SECURITY: `factory_ref` is evaluated via importlib.import_module — loading a
    # catalog is equivalent to executing Python. Trust your catalog source.
    if entry.factory_ref is None:
        raise BlueprintResolutionError(f"FACTORY entry {entry.id!r}: payload missing (invariant violation).")
    ref = entry.factory_ref
    module_path, _, attr = ref.partition(":")
    try:
        module = importlib.import_module(module_path)
    except ImportError as exc:
        raise BlueprintResolutionError(
            f"FACTORY entry {entry.id!r}: cannot import module {module_path!r}: {exc}"
        ) from exc

    try:
        factory = getattr(module, attr)
    except AttributeError as exc:
        raise BlueprintResolutionError(
            f"FACTORY entry {entry.id!r}: module {module_path!r} has no attribute {attr!r}"
        ) from exc

    if not callable(factory):
        raise BlueprintResolutionError(f"FACTORY entry {entry.id!r}: {ref!r} is not callable")

    try:
        result = factory()
    except Exception as exc:
        raise BlueprintResolutionError(
            f"FACTORY entry {entry.id!r}: factory raised {type(exc).__name__}: {exc}"
        ) from exc

    if not isinstance(result, Blueprint):
        raise BlueprintResolutionError(
            f"FACTORY entry {entry.id!r}: factory returned {type(result).__name__}, expected Blueprint"
        )
    return result


def _resolve_recipe(entry: BlueprintEntry) -> Blueprint:
    if entry.recipe is None:
        raise BlueprintResolutionError(f"RECIPE entry {entry.id!r}: payload missing (invariant violation).")
    try:
        return parse_recipe(recipe=entry.recipe, default_id=entry.id, default_name=entry.title)
    except Exception as exc:
        raise BlueprintResolutionError(
            f"RECIPE entry {entry.id!r}: parser failed with {type(exc).__name__}: {exc}"
        ) from exc


_RESOLVERS = {
    BlueprintEntryKind.SNAPSHOT: _resolve_snapshot,
    BlueprintEntryKind.FACTORY: _resolve_factory,
    BlueprintEntryKind.RECIPE: _resolve_recipe,
}


# =============================================================================
# Library — in-memory index with search + resolution.
# =============================================================================


_CAMEL_SPLIT_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_WORD_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> set[str]:
    """Camel-aware tokenizer — identical contract to docs_api."""
    camel_split = _CAMEL_SPLIT_RE.sub(" ", text)
    return set(_WORD_RE.findall(camel_split.lower()))


class BlueprintLibrary:
    """In-memory, append-then-query registry of `BlueprintEntry` records.

    Search is weighted token overlap (title ×3, tags ×2, description ×1)
    — deterministic, transparent, no embedding model required. Wrap with
    a vector backend via the same `BlueprintSource` protocol for semantic
    search.

    The library holds *entries*, not live `Blueprint` objects. Resolution
    is lazy: `resolve(entry_id)` materializes the Blueprint the first
    time it's requested. Callers that need caching should cache the
    returned `Blueprint` themselves — the library stays stateless.
    """

    def __init__(self, entries: Iterable[BlueprintEntry] = ()) -> None:
        self._entries: dict[str, BlueprintEntry] = {}
        for entry in entries:
            self.register(entry=entry)

    def register(self, *, entry: BlueprintEntry, overwrite: bool = False) -> None:
        """Add `entry` to the library. Rejects id collisions by default."""
        if entry.id in self._entries and not overwrite:
            raise BlueprintIdCollision(
                f"Entry id {entry.id!r} already registered. Pass overwrite=True to replace."
            )
        self._entries[entry.id] = entry

    def register_from(self, *, sources: Iterable[BlueprintSource], overwrite: bool = False) -> None:
        """Ingest every entry from each source in order."""
        for source in sources:
            for entry in source.load():
                self.register(entry=entry, overwrite=overwrite)

    def get(self, entry_id: str) -> BlueprintEntry | None:
        return self._entries.get(entry_id)

    def entries(self) -> tuple[BlueprintEntry, ...]:
        """Return every registered entry as an immutable tuple."""
        return tuple(self._entries.values())

    def __len__(self) -> int:
        return len(self._entries)

    def __iter__(self) -> Iterator[BlueprintEntry]:
        return iter(self._entries.values())

    def resolve(self, *, entry_id: str) -> Blueprint:
        """Materialize the `Blueprint` for `entry_id`.

        Raises:
            BlueprintNotFound — no entry with that id
            BlueprintResolutionError — entry present but materialization failed
        """
        entry = self._entries.get(entry_id)
        if entry is None:
            raise BlueprintNotFound(f"No blueprint entry with id {entry_id!r}")
        resolver = _RESOLVERS[entry.kind]
        return resolver(entry)

    def search(
        self,
        *,
        query: str,
        k: int = 5,
        kinds: tuple[BlueprintEntryKind, ...] | None = None,
        tags: tuple[str, ...] | None = None,
    ) -> list[tuple[BlueprintEntry, float]]:
        """Top-k entries by weighted token overlap.

        Empty query returns an empty list (no "return everything" footgun).
        `kinds` restricts to a subset (e.g. only SNAPSHOT entries).
        `tags` restricts to entries carrying at least one of the given tags.
        Results are sorted by score descending, then by entry.id for stable
        tie-breaks.
        """
        query_tokens = _tokenize(query)
        if not query_tokens:
            return []

        tag_filter = set(tags) if tags else None

        scored: list[tuple[BlueprintEntry, float]] = []
        for entry in self._entries.values():
            if kinds is not None and entry.kind not in kinds:
                continue
            if tag_filter is not None and not (tag_filter & set(entry.tags)):
                continue

            title_tokens = _tokenize(entry.title)
            tag_tokens: set[str] = set()
            for tag in entry.tags:
                tag_tokens.update(_tokenize(tag))
            desc_tokens = _tokenize(entry.description)

            title_hits = len(query_tokens & title_tokens)
            tag_hits = len(query_tokens & tag_tokens)
            desc_hits = len(query_tokens & desc_tokens)
            score = float(3 * title_hits + 2 * tag_hits + desc_hits)
            if score > 0:
                scored.append((entry, score))

        scored.sort(key=lambda pair: (-pair[1], pair[0].id))
        return scored[:k]


@runtime_checkable
class BlueprintSource(Protocol):
    """Pluggable ingestion seam for a `BlueprintLibrary`."""

    @property
    def name(self) -> str:
        """Short identifier written to `BlueprintEntry.source` for provenance."""
        ...

    def load(self) -> Iterable[BlueprintEntry]:
        """Yield every entry this source produces."""
        ...

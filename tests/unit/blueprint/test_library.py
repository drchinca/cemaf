"""Unit tests for `BlueprintLibrary` — isolated branch coverage."""

from __future__ import annotations

import pytest

from cemaf.blueprint.core import Blueprint, SceneGoal
from cemaf.blueprint.library import (
    BlueprintEntry,
    BlueprintEntryKind,
    BlueprintIdCollision,
    BlueprintLibrary,
    BlueprintLibraryError,
    BlueprintNotFound,
    BlueprintResolutionError,
    BlueprintSource,
    _tokenize,
)


@pytest.fixture
def tiny_blueprint() -> Blueprint:
    return Blueprint(
        id="tiny",
        name="Tiny",
        scene_goal=SceneGoal(objective="x"),
    )


class TestTokenize:
    def test_splits_camel_case(self) -> None:
        assert "runtime" in _tokenize("RuntimeServices")
        assert "services" in _tokenize("RuntimeServices")

    def test_splits_pascal_boundaries(self) -> None:
        # HTTPServer → http, server
        tokens = _tokenize("HTTPServer")
        assert "http" in tokens
        assert "server" in tokens

    def test_lowercases_and_drops_punctuation(self) -> None:
        assert _tokenize("Product-Announcement!") == {"product", "announcement"}

    def test_empty_input(self) -> None:
        assert _tokenize("") == set()

    def test_numeric_tokens(self) -> None:
        assert "v2" in _tokenize("Release v2")


class TestEntryPostInit:
    def test_rejects_missing_payload_for_declared_kind(self, tiny_blueprint: Blueprint) -> None:
        with pytest.raises(BlueprintLibraryError, match="matching payload field is empty"):
            BlueprintEntry(
                id="x",
                kind=BlueprintEntryKind.SNAPSHOT,
                title="X",
                # snapshot deliberately left None
            )

    def test_rejects_foreign_payload(self, tiny_blueprint: Blueprint) -> None:
        with pytest.raises(BlueprintLibraryError, match="foreign payload"):
            BlueprintEntry(
                id="x",
                kind=BlueprintEntryKind.SNAPSHOT,
                title="X",
                snapshot=tiny_blueprint.to_dict(),
                factory_ref="pkg:fn",  # foreign
            )

    def test_rejects_empty_id(self, tiny_blueprint: Blueprint) -> None:
        with pytest.raises(BlueprintLibraryError, match="id must be non-empty"):
            BlueprintEntry(
                id="",
                kind=BlueprintEntryKind.SNAPSHOT,
                title="X",
                snapshot=tiny_blueprint.to_dict(),
            )

    def test_rejects_empty_title(self, tiny_blueprint: Blueprint) -> None:
        with pytest.raises(BlueprintLibraryError, match="title must be non-empty"):
            BlueprintEntry(
                id="x",
                kind=BlueprintEntryKind.SNAPSHOT,
                title="",
                snapshot=tiny_blueprint.to_dict(),
            )


class TestFactoryClassmethodValidation:
    def test_factory_entry_rejects_dot_separator(self) -> None:
        with pytest.raises(BlueprintLibraryError, match="module:callable"):
            BlueprintEntry.factory_entry(
                id="x",
                title="X",
                factory_ref="pkg.module.fn",
            )


class TestLibraryBasics:
    def test_register_and_get(self, tiny_blueprint: Blueprint) -> None:
        library = BlueprintLibrary()
        entry = BlueprintEntry.snapshot_entry(id="a", title="A", blueprint=tiny_blueprint)
        library.register(entry=entry)
        assert library.get("a") is entry
        assert library.get("missing") is None

    def test_length_and_iteration(self, tiny_blueprint: Blueprint) -> None:
        library = BlueprintLibrary()
        library.register(entry=BlueprintEntry.snapshot_entry(id="a", title="A", blueprint=tiny_blueprint))
        library.register(entry=BlueprintEntry.snapshot_entry(id="b", title="B", blueprint=tiny_blueprint))

        assert len(library) == 2
        ids_via_iter = {e.id for e in library}
        assert ids_via_iter == {"a", "b"}

    def test_all_returns_tuple(self, tiny_blueprint: Blueprint) -> None:
        library = BlueprintLibrary(
            entries=(BlueprintEntry.snapshot_entry(id="a", title="A", blueprint=tiny_blueprint),),
        )
        all_entries = library.all()
        assert isinstance(all_entries, tuple)
        assert len(all_entries) == 1

    def test_collision_without_overwrite(self, tiny_blueprint: Blueprint) -> None:
        library = BlueprintLibrary()
        e = BlueprintEntry.snapshot_entry(id="a", title="A", blueprint=tiny_blueprint)
        library.register(entry=e)
        with pytest.raises(BlueprintIdCollision, match="'a'"):
            library.register(entry=e)

    def test_overwrite_replaces(self, tiny_blueprint: Blueprint) -> None:
        library = BlueprintLibrary()
        library.register(entry=BlueprintEntry.snapshot_entry(id="a", title="A1", blueprint=tiny_blueprint))
        library.register(
            entry=BlueprintEntry.snapshot_entry(id="a", title="A2", blueprint=tiny_blueprint),
            overwrite=True,
        )
        got = library.get("a")
        assert got is not None
        assert got.title == "A2"

    def test_resolve_unknown_id(self) -> None:
        library = BlueprintLibrary()
        with pytest.raises(BlueprintNotFound, match="'ghost'"):
            library.resolve(entry_id="ghost")


class TestSourceProtocolConformance:
    def test_in_memory_source_is_blueprint_source(self, tiny_blueprint: Blueprint) -> None:
        from cemaf.blueprint.sources import InMemoryBlueprintSource

        source = InMemoryBlueprintSource(
            entries=(BlueprintEntry.snapshot_entry(id="a", title="A", blueprint=tiny_blueprint),),
        )
        # Structural typing — no inheritance required.
        assert isinstance(source, BlueprintSource)

    def test_register_from_respects_overwrite_flag(self, tiny_blueprint: Blueprint) -> None:
        from cemaf.blueprint.sources import InMemoryBlueprintSource

        original = BlueprintEntry.snapshot_entry(id="a", title="Original", blueprint=tiny_blueprint)
        duplicate = BlueprintEntry.snapshot_entry(id="a", title="Duplicate", blueprint=tiny_blueprint)

        library = BlueprintLibrary()
        library.register(entry=original)

        # Without overwrite, second source's duplicate raises.
        with pytest.raises(BlueprintIdCollision):
            library.register_from(sources=(InMemoryBlueprintSource(entries=(duplicate,)),))

        # With overwrite, it replaces.
        library.register_from(
            sources=(InMemoryBlueprintSource(entries=(duplicate,)),),
            overwrite=True,
        )
        got = library.get("a")
        assert got is not None
        assert got.title == "Duplicate"


class TestSearchBranches:
    @pytest.fixture
    def sample(self, tiny_blueprint: Blueprint) -> BlueprintLibrary:
        library = BlueprintLibrary()
        library.register(
            entry=BlueprintEntry.snapshot_entry(
                id="alpha",
                title="Alpha Release",
                blueprint=tiny_blueprint,
                tags=("release",),
                description="launch prep",
            )
        )
        library.register(
            entry=BlueprintEntry.snapshot_entry(
                id="beta",
                title="Beta Announcement",
                blueprint=tiny_blueprint,
                tags=("announcement", "release"),
                description="product launch",
            )
        )
        return library

    def test_empty_query_returns_empty(self, sample: BlueprintLibrary) -> None:
        assert sample.search(query="") == []
        assert sample.search(query="   ") == []  # whitespace → no tokens

    def test_k_limit_applied(self, sample: BlueprintLibrary) -> None:
        results = sample.search(query="release", k=1)
        assert len(results) <= 1

    def test_stable_tie_break_by_id(self, tiny_blueprint: Blueprint) -> None:
        library = BlueprintLibrary()
        # Identical titles → tie on score, break by id ascending.
        library.register(
            entry=BlueprintEntry.snapshot_entry(id="zz", title="Match", blueprint=tiny_blueprint)
        )
        library.register(
            entry=BlueprintEntry.snapshot_entry(id="aa", title="Match", blueprint=tiny_blueprint)
        )
        library.register(
            entry=BlueprintEntry.snapshot_entry(id="mm", title="Match", blueprint=tiny_blueprint)
        )
        results = sample_ids = [e.id for e, _ in library.search(query="match")]
        assert results == ["aa", "mm", "zz"]
        _ = sample_ids  # keep name explicit for readability

    def test_tag_filter_requires_overlap(self, sample: BlueprintLibrary) -> None:
        results = sample.search(query="launch", tags=("announcement",))
        ids = [e.id for e, _ in results]
        assert "beta" in ids
        assert "alpha" not in ids

    def test_tag_filter_with_no_overlap_returns_empty(self, sample: BlueprintLibrary) -> None:
        results = sample.search(query="launch", tags=("nonexistent",))
        assert results == []

    def test_title_beats_description_by_weight(self, tiny_blueprint: Blueprint) -> None:
        library = BlueprintLibrary()
        library.register(
            entry=BlueprintEntry.snapshot_entry(
                id="title-match",
                title="Announce",
                blueprint=tiny_blueprint,
            )
        )
        library.register(
            entry=BlueprintEntry.snapshot_entry(
                id="desc-match",
                title="Generic",
                blueprint=tiny_blueprint,
                description="announce announce announce",
            )
        )
        results = library.search(query="announce")
        assert results[0][0].id == "title-match"


class TestResolverErrorSurfaces:
    def test_factory_not_callable_raises(self) -> None:
        library = BlueprintLibrary()
        # `_tokenize` is callable but requires args → factory call wraps the TypeError.
        library.register(
            entry=BlueprintEntry.factory_entry(
                id="notcallable",
                title="NotCallable",
                factory_ref="cemaf.blueprint.library:_tokenize",
            )
        )
        # _tokenize is callable but requires args — should wrap as resolution error.
        with pytest.raises(BlueprintResolutionError):
            library.resolve(entry_id="notcallable")

    def test_snapshot_with_extra_unknown_field_still_parses(self, tiny_blueprint: Blueprint) -> None:
        # Pydantic extra fields are ignored by default on Blueprint; ensure this stays true
        # so recipes/snapshots remain forward-compat.
        raw = tiny_blueprint.to_dict()
        raw["unknown_future_field"] = "ok"
        library = BlueprintLibrary()
        library.register(
            entry=BlueprintEntry(
                id="fut",
                kind=BlueprintEntryKind.SNAPSHOT,
                title="Future",
                snapshot=raw,
            )
        )
        resolved = library.resolve(entry_id="fut")
        assert resolved.id == "tiny"

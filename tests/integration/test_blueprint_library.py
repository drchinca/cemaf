"""Integration tests for `BlueprintLibrary` across all three entry kinds.

These tests prove the full loop for each representational kind a library
entry can take — SNAPSHOT (inline serialized Blueprint), FACTORY (Python
import path), and RECIPE (declarative dict). For each kind we verify:

    1. Round-trip: register → resolve → produces a real `Blueprint`
    2. Fidelity:   the resolved Blueprint renders a prompt that contains
                   the expected content (we don't just check type, we
                   check the output is usable)
    3. Failure modes: malformed entries surface clear errors at the right
                       layer (registration vs. resolution)

We also test mixed-kind libraries (search, filtering, id collision) and
`BlueprintSource` ingestion so the full service contract is covered.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cemaf.blueprint import (
    Blueprint,
    BlueprintEntry,
    BlueprintEntryKind,
    BlueprintIdCollision,
    BlueprintLibrary,
    BlueprintNotFound,
    BlueprintResolutionError,
    InMemoryBlueprintSource,
    JSONFileBlueprintSource,
    SceneGoal,
    StyleGuide,
)

# =============================================================================
# Shared fixtures
# =============================================================================


@pytest.fixture
def announcement_blueprint() -> Blueprint:
    """A rich Blueprint used as the canonical fixture across kinds."""
    return Blueprint(
        id="content/announcement",
        name="Product Announcement",
        description="Launch post for external audiences",
        version="1.1",
        tags=("content", "marketing"),
        scene_goal=SceneGoal(
            objective="Write a product announcement",
            success_criteria=("Clear value prop", "Concrete CTA"),
            constraints=("Under 300 words",),
            priority=2,
        ),
        style_guide=StyleGuide(tone="confident", format="markdown", length_hint="concise"),
        instruction="Lead with the user benefit, not the feature list.",
    )


# =============================================================================
# (a) SNAPSHOT — inline serialized Blueprint
# =============================================================================


class TestSnapshotEntryKind:
    """SNAPSHOT entries store the full Blueprint dict inline."""

    def test_round_trip_preserves_blueprint(self, announcement_blueprint: Blueprint) -> None:
        library = BlueprintLibrary()
        library.register(
            entry=BlueprintEntry.snapshot_entry(
                id="content/announcement",
                title="Product Announcement",
                blueprint=announcement_blueprint,
                tags=("content", "marketing"),
            )
        )

        resolved = library.resolve(entry_id="content/announcement")

        # Full structural equality — snapshots are faithful replay.
        assert resolved == announcement_blueprint
        assert resolved.version == "1.1"
        assert resolved.scene_goal.priority == 2

    def test_resolved_blueprint_renders_prompt(self, announcement_blueprint: Blueprint) -> None:
        library = BlueprintLibrary()
        library.register(
            entry=BlueprintEntry.snapshot_entry(
                id="bp1",
                title="Announcement",
                blueprint=announcement_blueprint,
            )
        )

        prompt = library.resolve(entry_id="bp1").to_prompt()

        assert "Write a product announcement" in prompt
        assert "Clear value prop" in prompt
        assert "Tone: confident" in prompt

    def test_snapshot_invariant_rejects_foreign_payload(self) -> None:
        # Can't claim SNAPSHOT but populate factory_ref.
        with pytest.raises(Exception) as exc_info:
            BlueprintEntry(
                id="bad",
                kind=BlueprintEntryKind.SNAPSHOT,
                title="Bad",
                snapshot={"id": "x", "name": "x", "scene_goal": {"objective": "x"}},
                factory_ref="pkg:fn",
            )
        assert "foreign payload" in str(exc_info.value).lower()

    def test_malformed_snapshot_raises_resolution_error(self) -> None:
        library = BlueprintLibrary()
        # Missing required `scene_goal` — Pydantic will reject on resolve.
        library.register(
            entry=BlueprintEntry(
                id="broken",
                kind=BlueprintEntryKind.SNAPSHOT,
                title="Broken",
                snapshot={"id": "broken", "name": "Broken"},
            )
        )
        with pytest.raises(BlueprintResolutionError) as exc_info:
            library.resolve(entry_id="broken")
        assert "SNAPSHOT" in str(exc_info.value)


# =============================================================================
# (b) FACTORY — Python import path
# =============================================================================
#
# Factory entries point at a zero-arg callable. We need a real importable
# factory for the happy path. Since test modules aren't always importable
# from a clean path, we register a factory defined here by placing it in
# a real module that ships with the blueprint package (a conftest-friendly
# sentinel), *or* — simpler — we use `cemaf.blueprint.mock.create_mock_blueprint`,
# which is already an importable callable returning a Blueprint.
# =============================================================================


def _canary_factory() -> Blueprint:
    """Test-only factory. Lives at module path:
    `tests.integration.test_blueprint_library:_canary_factory`.
    """
    return Blueprint(
        id="canary",
        name="Canary Blueprint",
        scene_goal=SceneGoal(objective="Sing a test signal"),
    )


def _boom_factory() -> Blueprint:
    raise RuntimeError("intentional boom")


def _not_a_blueprint_factory() -> str:
    return "not a blueprint"


class TestFactoryEntryKind:
    """FACTORY entries resolve by importing a dotted callable."""

    def test_round_trip_invokes_factory(self) -> None:
        library = BlueprintLibrary()
        library.register(
            entry=BlueprintEntry.factory_entry(
                id="bp/canary",
                title="Canary",
                factory_ref="tests.integration.test_blueprint_library:_canary_factory",
            )
        )

        resolved = library.resolve(entry_id="bp/canary")

        assert isinstance(resolved, Blueprint)
        assert resolved.id == "canary"
        assert resolved.scene_goal.objective == "Sing a test signal"

    def test_resolved_factory_blueprint_renders_prompt(self) -> None:
        library = BlueprintLibrary()
        library.register(
            entry=BlueprintEntry.factory_entry(
                id="bp/canary",
                title="Canary",
                factory_ref="tests.integration.test_blueprint_library:_canary_factory",
            )
        )
        prompt = library.resolve(entry_id="bp/canary").to_prompt()
        assert "Sing a test signal" in prompt

    def test_factory_ref_must_use_colon_separator(self) -> None:
        with pytest.raises(Exception) as exc_info:
            BlueprintEntry.factory_entry(
                id="x",
                title="X",
                factory_ref="tests.integration.test_blueprint_library._canary_factory",  # dot, not colon
            )
        assert "module:callable" in str(exc_info.value)

    def test_missing_module_raises_resolution_error(self) -> None:
        library = BlueprintLibrary()
        library.register(
            entry=BlueprintEntry.factory_entry(
                id="bad",
                title="Bad",
                factory_ref="cemaf.does.not.exist:factory",
            )
        )
        with pytest.raises(BlueprintResolutionError) as exc_info:
            library.resolve(entry_id="bad")
        assert "cannot import" in str(exc_info.value).lower()

    def test_missing_attribute_raises_resolution_error(self) -> None:
        library = BlueprintLibrary()
        library.register(
            entry=BlueprintEntry.factory_entry(
                id="bad",
                title="Bad",
                factory_ref="cemaf.blueprint.mock:no_such_symbol",
            )
        )
        with pytest.raises(BlueprintResolutionError) as exc_info:
            library.resolve(entry_id="bad")
        assert "no attribute" in str(exc_info.value).lower()

    def test_factory_exception_is_wrapped(self) -> None:
        library = BlueprintLibrary()
        library.register(
            entry=BlueprintEntry.factory_entry(
                id="boom",
                title="Boom",
                factory_ref="tests.integration.test_blueprint_library:_boom_factory",
            )
        )
        with pytest.raises(BlueprintResolutionError) as exc_info:
            library.resolve(entry_id="boom")
        assert "intentional boom" in str(exc_info.value)

    def test_factory_that_returns_wrong_type_fails_cleanly(self) -> None:
        library = BlueprintLibrary()
        library.register(
            entry=BlueprintEntry.factory_entry(
                id="wrong",
                title="Wrong",
                factory_ref="tests.integration.test_blueprint_library:_not_a_blueprint_factory",
            )
        )
        with pytest.raises(BlueprintResolutionError) as exc_info:
            library.resolve(entry_id="wrong")
        assert "expected Blueprint" in str(exc_info.value)


# =============================================================================
# (c) RECIPE — declarative dict
# =============================================================================


class TestRecipeEntryKind:
    """RECIPE entries carry a declarative dict parsed into a Blueprint."""

    def test_minimal_recipe_resolves(self) -> None:
        library = BlueprintLibrary()
        library.register(
            entry=BlueprintEntry.recipe_entry(
                id="minimal",
                title="Minimal",
                recipe={"name": "Minimal", "goal": "Do the thing"},
            )
        )

        resolved = library.resolve(entry_id="minimal")

        assert resolved.name == "Minimal"
        assert resolved.scene_goal.objective == "Do the thing"
        assert resolved.scene_goal.priority == 1  # default

    def test_rich_recipe_resolves_all_fields(self) -> None:
        library = BlueprintLibrary()
        library.register(
            entry=BlueprintEntry.recipe_entry(
                id="rich",
                title="Rich Recipe",
                recipe={
                    "name": "Rich Recipe",
                    "description": "A fully populated recipe",
                    "version": "2.0",
                    "tags": ["content"],
                    "goal": {
                        "objective": "Produce output",
                        "success_criteria": ["Correct", "Concise"],
                        "constraints": ["Under 100 words"],
                        "priority": 3,
                    },
                    "style": {
                        "tone": "formal",
                        "format": "markdown",
                        "length_hint": "brief",
                    },
                    "instruction": "Keep it tight.",
                },
            )
        )

        resolved = library.resolve(entry_id="rich")

        assert resolved.version == "2.0"
        assert resolved.tags == ("content",)
        assert resolved.scene_goal.priority == 3
        assert resolved.scene_goal.success_criteria == ("Correct", "Concise")
        assert resolved.style_guide.tone == "formal"
        assert resolved.instruction == "Keep it tight."

    def test_resolved_recipe_renders_prompt(self) -> None:
        library = BlueprintLibrary()
        library.register(
            entry=BlueprintEntry.recipe_entry(
                id="r",
                title="R",
                recipe={
                    "name": "R",
                    "goal": "Render me",
                    "style": {"tone": "formal"},
                },
            )
        )
        prompt = library.resolve(entry_id="r").to_prompt()
        assert "Render me" in prompt
        assert "Tone: formal" in prompt

    def test_recipe_accepts_long_form_keys(self) -> None:
        """Recipe should also accept `scene_goal`/`style_guide` long-form keys.
        This makes `Blueprint.to_dict()` output a valid recipe (important:
        it means SNAPSHOT and RECIPE formats are mutually compatible).
        """
        library = BlueprintLibrary()
        library.register(
            entry=BlueprintEntry.recipe_entry(
                id="long",
                title="Long",
                recipe={
                    "name": "Long",
                    "scene_goal": {"objective": "Long form"},
                    "style_guide": {"tone": "neutral"},
                },
            )
        )
        resolved = library.resolve(entry_id="long")
        assert resolved.scene_goal.objective == "Long form"
        assert resolved.style_guide.tone == "neutral"

    def test_recipe_missing_goal_fails_with_clear_error(self) -> None:
        library = BlueprintLibrary()
        library.register(
            entry=BlueprintEntry.recipe_entry(
                id="noop",
                title="Noop",
                recipe={"name": "Noop"},  # no goal
            )
        )
        with pytest.raises(BlueprintResolutionError) as exc_info:
            library.resolve(entry_id="noop")
        msg = str(exc_info.value).lower()
        assert "goal" in msg

    def test_recipe_with_malformed_tags_fails_clearly(self) -> None:
        library = BlueprintLibrary()
        library.register(
            entry=BlueprintEntry.recipe_entry(
                id="badtags",
                title="Bad Tags",
                recipe={"name": "Bad", "goal": "x", "tags": "notalist"},
            )
        )
        with pytest.raises(BlueprintResolutionError) as exc_info:
            library.resolve(entry_id="badtags")
        assert "list" in str(exc_info.value).lower()


# =============================================================================
# Mixed library — search, filter, collision, source ingestion
# =============================================================================


class TestMixedLibrary:
    """Cross-kind operations: search, filter, collision, source ingestion."""

    @pytest.fixture
    def mixed_library(self, announcement_blueprint: Blueprint) -> BlueprintLibrary:
        library = BlueprintLibrary()
        library.register(
            entry=BlueprintEntry.snapshot_entry(
                id="content/announcement",
                title="Product Announcement",
                blueprint=announcement_blueprint,
                tags=("content", "marketing"),
            )
        )
        library.register(
            entry=BlueprintEntry.factory_entry(
                id="content/canary",
                title="Canary Test Blueprint",
                factory_ref="tests.integration.test_blueprint_library:_canary_factory",
                tags=("testing",),
                description="A factory-backed blueprint for smoke tests.",
            )
        )
        library.register(
            entry=BlueprintEntry.recipe_entry(
                id="content/release-notes",
                title="Release Notes",
                recipe={"name": "Release Notes", "goal": "Summarize a release"},
                tags=("content", "release"),
            )
        )
        return library

    def test_all_kinds_resolve_to_blueprint(self, mixed_library: BlueprintLibrary) -> None:
        for entry in mixed_library.all():
            resolved = mixed_library.resolve(entry_id=entry.id)
            assert isinstance(resolved, Blueprint), f"kind={entry.kind} failed"
            # Every Blueprint can render a prompt — sanity check the real artifact.
            assert resolved.to_prompt()

    def test_search_finds_across_kinds(self, mixed_library: BlueprintLibrary) -> None:
        results = mixed_library.search(query="content announcement")
        ids = [r.id for r, _ in results]
        assert "content/announcement" in ids

    def test_search_filters_by_kind(self, mixed_library: BlueprintLibrary) -> None:
        results = mixed_library.search(
            query="content",
            kinds=(BlueprintEntryKind.FACTORY,),
        )
        # Only the factory-kind entry should appear, and only if its title/tags match.
        for entry, _ in results:
            assert entry.kind == BlueprintEntryKind.FACTORY

    def test_search_filters_by_tag(self, mixed_library: BlueprintLibrary) -> None:
        results = mixed_library.search(query="release", tags=("release",))
        ids = [r.id for r, _ in results]
        assert "content/release-notes" in ids
        assert "content/announcement" not in ids

    def test_collision_rejected_by_default(self, mixed_library: BlueprintLibrary) -> None:
        with pytest.raises(BlueprintIdCollision):
            mixed_library.register(
                entry=BlueprintEntry.recipe_entry(
                    id="content/announcement",
                    title="Dup",
                    recipe={"name": "Dup", "goal": "x"},
                )
            )

    def test_overwrite_flag_replaces_entry(self, mixed_library: BlueprintLibrary) -> None:
        original = mixed_library.get("content/announcement")
        assert original is not None and original.kind == BlueprintEntryKind.SNAPSHOT

        mixed_library.register(
            entry=BlueprintEntry.recipe_entry(
                id="content/announcement",
                title="Replacement",
                recipe={"name": "Replacement", "goal": "new objective"},
            ),
            overwrite=True,
        )

        replaced = mixed_library.get("content/announcement")
        assert replaced is not None
        assert replaced.kind == BlueprintEntryKind.RECIPE
        assert replaced.title == "Replacement"

    def test_resolve_unknown_id_raises(self, mixed_library: BlueprintLibrary) -> None:
        with pytest.raises(BlueprintNotFound):
            mixed_library.resolve(entry_id="does-not-exist")


# =============================================================================
# BlueprintSource ingestion — full plug-in loop
# =============================================================================


class TestSourceIngestion:
    """Sources are the pluggable seam — verify the full plug-in loop."""

    def test_in_memory_source_feeds_library(self, announcement_blueprint: Blueprint) -> None:
        source = InMemoryBlueprintSource(
            entries=(
                BlueprintEntry.snapshot_entry(
                    id="a",
                    title="A",
                    blueprint=announcement_blueprint,
                ),
                BlueprintEntry.recipe_entry(
                    id="b",
                    title="B",
                    recipe={"name": "B", "goal": "objective B"},
                ),
            ),
            name="curated",
        )

        library = BlueprintLibrary()
        library.register_from(sources=(source,))

        assert len(library) == 2
        # Provenance stamped by source.
        assert library.get("a").source == "curated"
        assert library.get("b").source == "curated"
        # Both resolve.
        assert library.resolve(entry_id="a").id == "content/announcement"
        assert library.resolve(entry_id="b").scene_goal.objective == "objective B"

    def test_json_file_source_round_trip(self, tmp_path: Path, announcement_blueprint: Blueprint) -> None:
        # Write a realistic catalog.json with all three kinds.
        catalog_path = tmp_path / "catalog.json"
        catalog_path.write_text(
            json.dumps(
                [
                    {
                        "id": "content/announcement",
                        "kind": "snapshot",
                        "title": "Product Announcement",
                        "tags": ["content"],
                        "snapshot": announcement_blueprint.to_dict(),
                    },
                    {
                        "id": "content/canary",
                        "kind": "factory",
                        "title": "Canary",
                        "factory_ref": ("tests.integration.test_blueprint_library:_canary_factory"),
                    },
                    {
                        "id": "content/release-notes",
                        "kind": "recipe",
                        "title": "Release Notes",
                        "recipe": {"name": "Release Notes", "goal": "Summarize a release"},
                    },
                ]
            )
        )

        source = JSONFileBlueprintSource(path=catalog_path)
        library = BlueprintLibrary()
        library.register_from(sources=(source,))

        assert len(library) == 3
        # All three kinds resolve to real Blueprints.
        for entry_id in ("content/announcement", "content/canary", "content/release-notes"):
            resolved = library.resolve(entry_id=entry_id)
            assert isinstance(resolved, Blueprint)
            assert resolved.to_prompt()

    def test_json_file_source_missing_file_is_noop(self, tmp_path: Path) -> None:
        library = BlueprintLibrary()
        library.register_from(
            sources=(JSONFileBlueprintSource(path=tmp_path / "nope.json"),),
        )
        assert len(library) == 0

    def test_json_file_source_bad_top_level_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.json"
        path.write_text(json.dumps({"not": "a list"}))
        source = JSONFileBlueprintSource(path=path)
        with pytest.raises(ValueError, match="top-level JSON must be a list"):
            list(source.load())

    def test_json_file_source_bad_kind_raises_at_load(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.json"
        path.write_text(json.dumps([{"id": "x", "kind": "unknown", "title": "X"}]))
        source = JSONFileBlueprintSource(path=path)
        with pytest.raises(ValueError, match="kind"):
            list(source.load())

"""Unit tests for `BlueprintSource` implementations."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cemaf.blueprint.core import Blueprint, SceneGoal
from cemaf.blueprint.library import BlueprintEntry, BlueprintEntryKind
from cemaf.blueprint.sources import InMemoryBlueprintSource, JSONFileBlueprintSource


@pytest.fixture
def tiny_blueprint() -> Blueprint:
    return Blueprint(id="tiny", name="Tiny", scene_goal=SceneGoal(objective="x"))


class TestInMemorySource:
    def test_name_defaults_to_in_memory(self) -> None:
        source = InMemoryBlueprintSource(entries=())
        assert source.name == "in-memory"

    def test_custom_name(self) -> None:
        source = InMemoryBlueprintSource(entries=(), name="curated")
        assert source.name == "curated"

    def test_stamps_source_on_entries_without_one(self, tiny_blueprint: Blueprint) -> None:
        entry = BlueprintEntry.snapshot_entry(id="a", title="A", blueprint=tiny_blueprint)
        assert entry.source == ""

        source = InMemoryBlueprintSource(entries=(entry,), name="stamp-me")
        loaded = list(source.load())
        assert loaded[0].source == "stamp-me"

    def test_preserves_explicit_source(self, tiny_blueprint: Blueprint) -> None:
        entry = BlueprintEntry.snapshot_entry(
            id="a",
            title="A",
            blueprint=tiny_blueprint,
            source="already-set",
        )
        source = InMemoryBlueprintSource(entries=(entry,), name="stamp-me")
        loaded = list(source.load())
        assert loaded[0].source == "already-set"

    def test_stamping_preserves_other_fields(self, tiny_blueprint: Blueprint) -> None:
        entry = BlueprintEntry.snapshot_entry(
            id="a",
            title="A",
            blueprint=tiny_blueprint,
            description="desc",
            tags=("t1", "t2"),
            path="/some/path",
        )
        source = InMemoryBlueprintSource(entries=(entry,), name="curated")
        loaded = list(source.load())[0]
        assert loaded.description == "desc"
        assert loaded.tags == ("t1", "t2")
        assert loaded.path == "/some/path"
        assert loaded.kind is BlueprintEntryKind.SNAPSHOT
        assert loaded.snapshot == entry.snapshot


class TestJSONFileSource:
    def test_missing_file_yields_nothing(self, tmp_path: Path) -> None:
        source = JSONFileBlueprintSource(path=tmp_path / "nope.json")
        assert list(source.load()) == []

    def test_top_level_not_list_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.json"
        path.write_text(json.dumps({"not": "a list"}))
        with pytest.raises(ValueError, match="top-level JSON must be a list"):
            list(JSONFileBlueprintSource(path=path).load())

    def test_entry_not_dict_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.json"
        path.write_text(json.dumps(["notadict"]))
        with pytest.raises(ValueError, match="must be a dict"):
            list(JSONFileBlueprintSource(path=path).load())

    def test_unknown_kind_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.json"
        path.write_text(json.dumps([{"id": "x", "kind": "bogus", "title": "X"}]))
        with pytest.raises(ValueError, match="kind"):
            list(JSONFileBlueprintSource(path=path).load())

    def test_missing_required_field_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.json"
        # Missing 'title' on a snapshot entry.
        path.write_text(json.dumps([{"id": "x", "kind": "snapshot", "snapshot": {"id": "x", "name": "X"}}]))
        with pytest.raises(ValueError, match="missing required field"):
            list(JSONFileBlueprintSource(path=path).load())

    def test_default_name_encodes_filename(self, tmp_path: Path) -> None:
        path = tmp_path / "catalog.json"
        path.write_text("[]")
        source = JSONFileBlueprintSource(path=path)
        assert source.name == "json:catalog.json"

    def test_custom_name(self, tmp_path: Path) -> None:
        path = tmp_path / "catalog.json"
        path.write_text("[]")
        source = JSONFileBlueprintSource(path=path, name="corporate-catalog")
        assert source.name == "corporate-catalog"

    def test_round_trip_all_three_kinds(self, tmp_path: Path, tiny_blueprint: Blueprint) -> None:
        path = tmp_path / "catalog.json"
        path.write_text(
            json.dumps(
                [
                    {
                        "id": "snap",
                        "kind": "snapshot",
                        "title": "Snap",
                        "snapshot": tiny_blueprint.to_dict(),
                    },
                    {
                        "id": "fac",
                        "kind": "factory",
                        "title": "Fac",
                        "factory_ref": "mod:fn",
                    },
                    {
                        "id": "rec",
                        "kind": "recipe",
                        "title": "Rec",
                        "recipe": {"name": "Rec", "goal": "o"},
                    },
                ]
            )
        )
        loaded = list(JSONFileBlueprintSource(path=path).load())
        kinds = {e.id: e.kind for e in loaded}
        assert kinds == {
            "snap": BlueprintEntryKind.SNAPSHOT,
            "fac": BlueprintEntryKind.FACTORY,
            "rec": BlueprintEntryKind.RECIPE,
        }

    def test_explicit_source_in_record_wins_over_default(
        self, tmp_path: Path, tiny_blueprint: Blueprint
    ) -> None:
        path = tmp_path / "catalog.json"
        path.write_text(
            json.dumps(
                [
                    {
                        "id": "x",
                        "kind": "snapshot",
                        "title": "X",
                        "source": "explicit",
                        "snapshot": tiny_blueprint.to_dict(),
                    }
                ]
            )
        )
        loaded = list(JSONFileBlueprintSource(path=path).load())[0]
        assert loaded.source == "explicit"

    def test_metadata_and_version_preserved(self, tmp_path: Path, tiny_blueprint: Blueprint) -> None:
        path = tmp_path / "catalog.json"
        path.write_text(
            json.dumps(
                [
                    {
                        "id": "x",
                        "kind": "snapshot",
                        "title": "X",
                        "version": "9.9",
                        "metadata": {"owner": "team-a"},
                        "snapshot": tiny_blueprint.to_dict(),
                    }
                ]
            )
        )
        loaded = list(JSONFileBlueprintSource(path=path).load())[0]
        assert loaded.version == "9.9"
        assert loaded.metadata == {"owner": "team-a"}

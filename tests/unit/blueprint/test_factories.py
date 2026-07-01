"""Unit tests for blueprint composition-root factories."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cemaf.blueprint.core import Blueprint, SceneGoal
from cemaf.blueprint.factories import (
    blueprint_source_registry,
    create_blueprint_library,
    create_blueprint_library_from_env,
    create_blueprint_source,
)
from cemaf.blueprint.library import BlueprintEntry, BlueprintLibrary
from cemaf.blueprint.sources import InMemoryBlueprintSource, JSONFileBlueprintSource
from cemaf.blueprint.sqlite_source import SqliteBlueprintSource


@pytest.fixture
def tiny_blueprint() -> Blueprint:
    return Blueprint(id="tiny", name="Tiny", scene_goal=SceneGoal(objective="x"))


class TestCreateBlueprintLibrary:
    def test_empty_by_default(self) -> None:
        library = create_blueprint_library()
        assert isinstance(library, BlueprintLibrary)
        assert len(library) == 0

    def test_preloads_from_sources(self, tiny_blueprint: Blueprint) -> None:
        source = InMemoryBlueprintSource(
            entries=(BlueprintEntry.snapshot_entry(id="a", title="A", blueprint=tiny_blueprint),),
        )
        library = create_blueprint_library(sources=(source,))
        assert len(library) == 1


class TestCreateBlueprintSource:
    def test_creates_memory_source(self, tiny_blueprint: Blueprint) -> None:
        entry = BlueprintEntry.snapshot_entry(id="a", title="A", blueprint=tiny_blueprint)

        source = create_blueprint_source("memory", entries=(entry,), name="bootstrap")

        assert isinstance(source, InMemoryBlueprintSource)
        assert [loaded.source for loaded in source.load()] == ["bootstrap"]

    def test_creates_json_file_source(self, tmp_path: Path) -> None:
        path = tmp_path / "catalog.json"
        path.write_text("[]")

        source = create_blueprint_source("json_file", path=path, name="catalog")

        assert isinstance(source, JSONFileBlueprintSource)
        assert source.name == "catalog"

    def test_creates_sqlite_source(self, tmp_path: Path) -> None:
        source = create_blueprint_source("sqlite", db_path=tmp_path / "blueprints.db")

        assert isinstance(source, SqliteBlueprintSource)

    def test_unknown_source_type_mentions_registry(self) -> None:
        with pytest.raises(ValueError, match="blueprint_source_registry.register"):
            create_blueprint_source("opensearch")

    def test_supports_custom_registered_source(self, tiny_blueprint: Blueprint) -> None:
        created: dict[str, object] = {}
        entry = BlueprintEntry.snapshot_entry(id="custom", title="Custom", blueprint=tiny_blueprint)

        def _factory(**kwargs):
            created["args"] = kwargs
            return InMemoryBlueprintSource(entries=(entry,), name="custom-source")

        blueprint_source_registry.register(backend="custom-test-blueprint-source", factory=_factory)

        source = create_blueprint_source(
            "custom-test-blueprint-source",
            path="/tmp/ignored.json",
            custom_flag=True,
        )

        assert isinstance(source, InMemoryBlueprintSource)
        assert [loaded.id for loaded in source.load()] == ["custom"]
        assert created["args"]["path"] == "/tmp/ignored.json"
        assert created["args"]["custom_flag"] is True


class TestCreateFromEnv:
    def test_unset_env_returns_empty_library(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CEMAF_BLUEPRINT_CATALOG", raising=False)
        monkeypatch.delenv("CEMAF_BLUEPRINT_SOURCE_BACKEND", raising=False)
        library = create_blueprint_library_from_env()
        assert len(library) == 0

    def test_env_pointing_at_missing_file_is_noop(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.delenv("CEMAF_BLUEPRINT_SOURCE_BACKEND", raising=False)
        monkeypatch.setenv("CEMAF_BLUEPRINT_CATALOG", str(tmp_path / "does-not-exist.json"))
        library = create_blueprint_library_from_env()
        assert len(library) == 0

    def test_env_loads_catalog(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        tiny_blueprint: Blueprint,
    ) -> None:
        path = tmp_path / "catalog.json"
        path.write_text(
            json.dumps(
                [
                    {
                        "id": "x",
                        "kind": "snapshot",
                        "title": "X",
                        "snapshot": tiny_blueprint.to_dict(),
                    }
                ]
            )
        )
        monkeypatch.delenv("CEMAF_BLUEPRINT_SOURCE_BACKEND", raising=False)
        monkeypatch.setenv("CEMAF_BLUEPRINT_CATALOG", str(path))

        library = create_blueprint_library_from_env()

        assert len(library) == 1
        resolved = library.resolve(entry_id="x")
        assert resolved.id == "tiny"

    def test_env_loads_explicit_json_source_backend(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        tiny_blueprint: Blueprint,
    ) -> None:
        path = tmp_path / "catalog.json"
        path.write_text(
            json.dumps(
                [
                    {
                        "id": "x",
                        "kind": "snapshot",
                        "title": "X",
                        "snapshot": tiny_blueprint.to_dict(),
                    }
                ]
            )
        )
        monkeypatch.setenv("CEMAF_BLUEPRINT_SOURCE_BACKEND", "json_file")
        monkeypatch.setenv("CEMAF_BLUEPRINT_SOURCE_PATH", str(path))

        library = create_blueprint_library_from_env()

        assert len(library) == 1
        assert library.resolve(entry_id="x").id == "tiny"

    def test_env_uses_custom_registered_source(
        self, monkeypatch: pytest.MonkeyPatch, tiny_blueprint: Blueprint
    ) -> None:
        entry = BlueprintEntry.snapshot_entry(id="env-custom", title="Env", blueprint=tiny_blueprint)
        created: dict[str, object] = {}

        def _factory(**kwargs):
            created["args"] = kwargs
            return InMemoryBlueprintSource(entries=(entry,), name="env-custom-source")

        blueprint_source_registry.register(backend="env-custom-blueprint-source", factory=_factory)
        monkeypatch.setenv("CEMAF_BLUEPRINT_SOURCE_BACKEND", "env-custom-blueprint-source")
        monkeypatch.setenv("CEMAF_BLUEPRINT_SOURCE_PATH", "/tmp/catalog.json")
        monkeypatch.setenv("CEMAF_BLUEPRINT_SOURCE_NAME", "configured-name")

        library = create_blueprint_library_from_env()

        assert len(library) == 1
        assert library.resolve(entry_id="env-custom").id == "tiny"
        assert created["args"]["path"] == "/tmp/catalog.json"
        assert created["args"]["name"] == "configured-name"

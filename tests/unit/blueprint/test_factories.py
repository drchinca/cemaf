"""Unit tests for blueprint composition-root factories."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cemaf.blueprint.core import Blueprint, SceneGoal
from cemaf.blueprint.factories import (
    create_blueprint_library,
    create_blueprint_library_from_env,
)
from cemaf.blueprint.library import BlueprintEntry, BlueprintLibrary
from cemaf.blueprint.sources import InMemoryBlueprintSource


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


class TestCreateFromEnv:
    def test_unset_env_returns_empty_library(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CEMAF_BLUEPRINT_CATALOG", raising=False)
        library = create_blueprint_library_from_env()
        assert len(library) == 0

    def test_env_pointing_at_missing_file_is_noop(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
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
        monkeypatch.setenv("CEMAF_BLUEPRINT_CATALOG", str(path))

        library = create_blueprint_library_from_env()

        assert len(library) == 1
        resolved = library.resolve(entry_id="x")
        assert resolved.id == "tiny"

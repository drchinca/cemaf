"""Unit tests for the `cemaf blueprint` CLI subcommands."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from cemaf.blueprint.core import Blueprint, SceneGoal
from cemaf.cli import main


@pytest.fixture
def catalog_path(tmp_path: Path) -> Path:
    bp = Blueprint(id="tiny", name="Tiny", scene_goal=SceneGoal(objective="canary objective"))
    path = tmp_path / "catalog.json"
    path.write_text(
        json.dumps(
            [
                {
                    "id": "content/announce",
                    "kind": "snapshot",
                    "title": "Announcement",
                    "tags": ["content", "marketing"],
                    "snapshot": bp.to_dict(),
                },
                {
                    "id": "content/recipe-doc",
                    "kind": "recipe",
                    "title": "Recipe Doc",
                    "tags": ["content"],
                    "recipe": {"name": "Recipe Doc", "goal": "compose docs"},
                },
            ]
        )
    )
    return path


def _run(args: list[str]) -> None:
    # argparse reads sys.argv; simulate invocation.
    sys.argv = ["cemaf", *args]
    main()


class TestBlueprintList:
    def test_empty_library_hint(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.delenv("CEMAF_BLUEPRINT_CATALOG", raising=False)
        _run(["blueprint", "list"])
        out = capsys.readouterr().out
        assert "CEMAF_BLUEPRINT_CATALOG" in out

    def test_lists_all_entries(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        catalog_path: Path,
    ) -> None:
        monkeypatch.setenv("CEMAF_BLUEPRINT_CATALOG", str(catalog_path))
        _run(["blueprint", "list"])
        out = capsys.readouterr().out
        assert "Announcement" in out
        assert "Recipe Doc" in out
        assert "2 shown, 2 total" in out

    def test_list_kind_filter(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        catalog_path: Path,
    ) -> None:
        monkeypatch.setenv("CEMAF_BLUEPRINT_CATALOG", str(catalog_path))
        _run(["blueprint", "list", "--kind", "recipe"])
        out = capsys.readouterr().out
        assert "Recipe Doc" in out
        assert "Announcement" not in out


class TestBlueprintSearch:
    def test_search_finds_by_title(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        catalog_path: Path,
    ) -> None:
        monkeypatch.setenv("CEMAF_BLUEPRINT_CATALOG", str(catalog_path))
        _run(["blueprint", "search", "announcement"])
        out = capsys.readouterr().out
        assert "content/announce" in out

    def test_search_no_matches_message(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        catalog_path: Path,
    ) -> None:
        monkeypatch.setenv("CEMAF_BLUEPRINT_CATALOG", str(catalog_path))
        _run(["blueprint", "search", "zzz-nomatch"])
        out = capsys.readouterr().out
        assert "No matches" in out

    def test_search_tag_filter(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        catalog_path: Path,
    ) -> None:
        monkeypatch.setenv("CEMAF_BLUEPRINT_CATALOG", str(catalog_path))
        _run(["blueprint", "search", "content", "--tag", "marketing"])
        out = capsys.readouterr().out
        assert "content/announce" in out
        assert "content/recipe-doc" not in out


class TestBlueprintShow:
    def test_show_renders_prompt(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        catalog_path: Path,
    ) -> None:
        monkeypatch.setenv("CEMAF_BLUEPRINT_CATALOG", str(catalog_path))
        _run(["blueprint", "show", "content/announce"])
        out = capsys.readouterr().out
        assert "Announcement" in out
        assert "canary objective" in out  # from the rendered prompt
        assert "Rendered Prompt" in out

    def test_show_unknown_id(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        catalog_path: Path,
    ) -> None:
        monkeypatch.setenv("CEMAF_BLUEPRINT_CATALOG", str(catalog_path))
        _run(["blueprint", "show", "does-not-exist"])
        out = capsys.readouterr().out
        assert "No entry with id" in out

    def test_show_resolution_error_surfaces(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        tmp_path: Path,
    ) -> None:
        # A FACTORY entry pointing at a missing module → BlueprintResolutionError.
        path = tmp_path / "catalog.json"
        path.write_text(
            json.dumps(
                [
                    {
                        "id": "broken",
                        "kind": "factory",
                        "title": "Broken",
                        "factory_ref": "nonexistent.module:fn",
                    }
                ]
            )
        )
        monkeypatch.setenv("CEMAF_BLUEPRINT_CATALOG", str(path))
        _run(["blueprint", "show", "broken"])
        out = capsys.readouterr().out
        assert "failed to resolve" in out

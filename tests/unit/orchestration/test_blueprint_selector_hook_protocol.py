"""Contract tests for `BlueprintSelectorHook` — protocol-shape only."""

from __future__ import annotations

import pytest

from cemaf.blueprint.core import Blueprint, SceneGoal
from cemaf.blueprint.library import BlueprintEntry, BlueprintLibrary
from cemaf.meta.blueprint_selector import LibraryBlueprintSelectorHook
from cemaf.orchestration.blueprint_hook import BlueprintSelectorHook


class TestHookProtocol:
    def test_library_adapter_conforms(self) -> None:
        library = BlueprintLibrary()
        hook = LibraryBlueprintSelectorHook(library=library)
        assert isinstance(hook, BlueprintSelectorHook)

    def test_plain_object_does_not_conform(self) -> None:
        class NotAHook:
            pass

        assert not isinstance(NotAHook(), BlueprintSelectorHook)

    def test_callable_without_select_does_not_conform(self) -> None:
        class Impostor:
            async def retrieve(self, query: str) -> str:
                return ""

        assert not isinstance(Impostor(), BlueprintSelectorHook)

    @pytest.mark.asyncio
    async def test_empty_library_returns_empty_prompt(self) -> None:
        hook = LibraryBlueprintSelectorHook(library=BlueprintLibrary())
        assert await hook.select(query="anything") == ""

    @pytest.mark.asyncio
    async def test_empty_query_returns_empty_prompt(self) -> None:
        bp = Blueprint(id="x", name="X", scene_goal=SceneGoal(objective="do x"))
        library = BlueprintLibrary(
            entries=(BlueprintEntry.snapshot_entry(id="x", title="X", blueprint=bp),),
        )
        hook = LibraryBlueprintSelectorHook(library=library)
        assert await hook.select(query="") == ""

    @pytest.mark.asyncio
    async def test_hit_returns_rendered_prompt(self) -> None:
        bp = Blueprint(id="x", name="X", scene_goal=SceneGoal(objective="launch the product"))
        library = BlueprintLibrary(
            entries=(
                BlueprintEntry.snapshot_entry(
                    id="x",
                    title="Launch Blueprint",
                    blueprint=bp,
                    tags=("launch",),
                ),
            ),
        )
        hook = LibraryBlueprintSelectorHook(library=library)
        prompt = await hook.select(query="launch")
        assert "launch the product" in prompt

    @pytest.mark.asyncio
    async def test_tag_filter_is_honored(self) -> None:
        bp1 = Blueprint(id="a", name="A", scene_goal=SceneGoal(objective="announce launch a"))
        bp2 = Blueprint(id="b", name="B", scene_goal=SceneGoal(objective="announce launch b"))
        library = BlueprintLibrary(
            entries=(
                BlueprintEntry.snapshot_entry(
                    id="a",
                    title="Launch Marketing",
                    blueprint=bp1,
                    tags=("marketing",),
                ),
                BlueprintEntry.snapshot_entry(
                    id="b",
                    title="Launch Internal",
                    blueprint=bp2,
                    tags=("internal",),
                ),
            ),
        )
        hook = LibraryBlueprintSelectorHook(library=library, tags=("marketing",))
        prompt = await hook.select(query="launch")
        # Hook must return a non-empty prompt (only the marketing-tagged entry matches).
        assert prompt != ""
        assert "announce launch a" in prompt
        assert "announce launch b" not in prompt

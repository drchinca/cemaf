"""Unit tests for `BlueprintLibrary.register_async` — the concurrent-write seam."""

from __future__ import annotations

import asyncio

import pytest

from cemaf.blueprint.core import Blueprint, SceneGoal
from cemaf.blueprint.library import (
    BlueprintEntry,
    BlueprintIdCollision,
    BlueprintLibrary,
)


@pytest.fixture
def tiny_blueprint() -> Blueprint:
    return Blueprint(id="tiny", name="Tiny", scene_goal=SceneGoal(objective="x"))


class TestRegisterAsync:
    @pytest.mark.asyncio
    async def test_registers_new_entry(self, tiny_blueprint: Blueprint) -> None:
        library = BlueprintLibrary()
        entry = BlueprintEntry.snapshot_entry(id="a", title="A", blueprint=tiny_blueprint)
        await library.register_async(entry=entry)
        assert library.get("a") is entry

    @pytest.mark.asyncio
    async def test_collision_raises(self, tiny_blueprint: Blueprint) -> None:
        library = BlueprintLibrary()
        entry = BlueprintEntry.snapshot_entry(id="a", title="A", blueprint=tiny_blueprint)
        await library.register_async(entry=entry)
        with pytest.raises(BlueprintIdCollision, match="'a'"):
            await library.register_async(entry=entry)

    @pytest.mark.asyncio
    async def test_overwrite_replaces(self, tiny_blueprint: Blueprint) -> None:
        library = BlueprintLibrary()
        await library.register_async(
            entry=BlueprintEntry.snapshot_entry(id="a", title="Original", blueprint=tiny_blueprint)
        )
        await library.register_async(
            entry=BlueprintEntry.snapshot_entry(id="a", title="Replaced", blueprint=tiny_blueprint),
            overwrite=True,
        )
        got = library.get("a")
        assert got is not None
        assert got.title == "Replaced"

    @pytest.mark.asyncio
    async def test_concurrent_appends_are_serialized(self, tiny_blueprint: Blueprint) -> None:
        library = BlueprintLibrary()

        async def _reg(i: int) -> None:
            await library.register_async(
                entry=BlueprintEntry.snapshot_entry(
                    id=f"bp-{i:02d}",
                    title=f"BP {i}",
                    blueprint=tiny_blueprint,
                )
            )

        await asyncio.gather(*(_reg(i) for i in range(50)))

        assert len(library) == 50
        ids = {e.id for e in library.entries()}
        assert ids == {f"bp-{i:02d}" for i in range(50)}

    @pytest.mark.asyncio
    async def test_concurrent_collisions_raise_without_corrupting_state(
        self, tiny_blueprint: Blueprint
    ) -> None:
        """Many concurrent registrations of the same id → one wins, others raise."""
        library = BlueprintLibrary()

        async def _reg(i: int) -> bool:
            try:
                await library.register_async(
                    entry=BlueprintEntry.snapshot_entry(
                        id="contested",
                        title=f"BP {i}",
                        blueprint=tiny_blueprint,
                    )
                )
                return True
            except BlueprintIdCollision:
                return False

        outcomes = await asyncio.gather(*(_reg(i) for i in range(10)))
        # Exactly one success, the rest collide.
        assert outcomes.count(True) == 1
        assert outcomes.count(False) == 9
        # Library holds exactly one entry under the contested id.
        assert len(library) == 1
        assert library.get("contested") is not None

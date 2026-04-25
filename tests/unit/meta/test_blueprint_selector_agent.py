"""Unit tests for `BlueprintSelectorAgent` — deterministic retrieval over a library."""

from __future__ import annotations

import pytest

from cemaf.agents.base import AgentContext
from cemaf.blueprint.core import Blueprint, SceneGoal, StyleGuide
from cemaf.blueprint.library import BlueprintEntry, BlueprintLibrary
from cemaf.meta.blueprint_goals import SelectionGoal
from cemaf.meta.blueprint_selector import BlueprintSelectorAgent


@pytest.fixture
def launch_blueprint() -> Blueprint:
    return Blueprint(
        id="launch",
        name="Launch",
        scene_goal=SceneGoal(objective="write a product launch announcement"),
        style_guide=StyleGuide(tone="confident"),
    )


@pytest.fixture
def context() -> AgentContext:
    return AgentContext(run_id="r1", agent_id="MetaBlueprintSelector")


class TestSelectorAgent:
    @pytest.mark.asyncio
    async def test_returns_top_hit(
        self,
        launch_blueprint: Blueprint,
        context: AgentContext,
    ) -> None:
        library = BlueprintLibrary(
            entries=(
                BlueprintEntry.snapshot_entry(
                    id="launch/announce",
                    title="Launch Announcement",
                    blueprint=launch_blueprint,
                ),
            ),
        )
        agent = BlueprintSelectorAgent(library=library)
        result = await agent.run(
            goal=SelectionGoal(query="launch announcement"),
            context=context,
        )
        assert result.success
        assert result.output is not None
        assert result.output.entry_id == "launch/announce"
        assert "write a product launch announcement" in result.output.prompt
        assert result.output.score > 0.0

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_match(
        self,
        launch_blueprint: Blueprint,
        context: AgentContext,
    ) -> None:
        library = BlueprintLibrary(
            entries=(
                BlueprintEntry.snapshot_entry(
                    id="launch/announce",
                    title="Launch Announcement",
                    blueprint=launch_blueprint,
                ),
            ),
        )
        agent = BlueprintSelectorAgent(library=library)
        result = await agent.run(
            goal=SelectionGoal(query="zzzzzz unrelated zzzzzz"),
            context=context,
        )
        assert result.success
        assert result.output is not None
        assert result.output.entry_id is None
        assert result.output.prompt == ""
        assert result.output.score == 0.0

    @pytest.mark.asyncio
    async def test_tag_filter(
        self,
        launch_blueprint: Blueprint,
        context: AgentContext,
    ) -> None:
        library = BlueprintLibrary(
            entries=(
                BlueprintEntry.snapshot_entry(
                    id="marketing",
                    title="Marketing Launch",
                    blueprint=launch_blueprint,
                    tags=("marketing",),
                ),
                BlueprintEntry.snapshot_entry(
                    id="internal",
                    title="Internal Launch",
                    blueprint=launch_blueprint,
                    tags=("internal",),
                ),
            ),
        )
        agent = BlueprintSelectorAgent(library=library)
        result = await agent.run(
            goal=SelectionGoal(query="launch", tags=("marketing",)),
            context=context,
        )
        assert result.success
        assert result.output is not None
        assert result.output.entry_id == "marketing"

    @pytest.mark.asyncio
    async def test_empty_library_succeeds_with_empty_result(
        self,
        context: AgentContext,
    ) -> None:
        agent = BlueprintSelectorAgent(library=BlueprintLibrary())
        result = await agent.run(
            goal=SelectionGoal(query="anything"),
            context=context,
        )
        assert result.success
        assert result.output is not None
        assert result.output.entry_id is None

"""Tests for MetaScaffolder agent — writes, rejects bad names, refuses overwrite, serializes."""

from __future__ import annotations

import asyncio
import tomllib
from pathlib import Path

import pytest

from cemaf.agents.base import AgentContext
from cemaf.meta.goals import (
    CapabilityDelta,
    GeneratedAgent,
    ProposalDoc,
    Requirement,
    ScaffoldGoal,
    Scenario,
)
from cemaf.meta.scaffolder import MetaScaffolder


def _proposal() -> ProposalDoc:
    return ProposalDoc(
        change_id="add-app",
        title="Add App",
        why="Because it's useful.",
        what_changes=("build the app",),
        impact=("affects: everything",),
        tasks=("implement",),
        deltas=(
            CapabilityDelta(
                capability="core",
                added_requirements=(
                    Requirement(
                        name="it works",
                        statement="The system SHALL work.",
                        scenarios=(
                            Scenario(
                                name="happy",
                                given=("setup",),
                                when=("triggered",),
                                then=("works",),
                            ),
                        ),
                    ),
                ),
            ),
        ),
    )


def _ctx() -> AgentContext:
    return AgentContext(run_id="test", agent_id="MetaScaffolder")


@pytest.mark.asyncio
async def test_scaffold_writes_expected_layout(tmp_path: Path) -> None:
    agent = MetaScaffolder()
    result = await agent.run(
        goal=ScaffoldGoal(
            proposal=_proposal(),
            project_name="my_app",
            target_dir=str(tmp_path),
        ),
        context=_ctx(),
    )
    assert result.success
    project_root = Path(result.output.project_root)  # type: ignore[union-attr]
    assert (project_root / "pyproject.toml").exists()
    assert (project_root / "src" / "my_app" / "bootstrap.py").exists()
    assert (project_root / "src" / "my_app" / "agents.py").exists()
    assert (project_root / "tests" / "test_smoke.py").exists()


@pytest.mark.asyncio
async def test_scaffold_refuses_invalid_identifier(tmp_path: Path) -> None:
    agent = MetaScaffolder()
    result = await agent.run(
        goal=ScaffoldGoal(
            proposal=_proposal(),
            project_name="123-weird",
            target_dir=str(tmp_path),
        ),
        context=_ctx(),
    )
    assert not result.success
    assert "identifier" in (result.error or "").lower()


@pytest.mark.asyncio
async def test_scaffold_refuses_python_keyword(tmp_path: Path) -> None:
    agent = MetaScaffolder()
    result = await agent.run(
        goal=ScaffoldGoal(
            proposal=_proposal(),
            project_name="class",
            target_dir=str(tmp_path),
        ),
        context=_ctx(),
    )
    assert not result.success
    assert "keyword" in (result.error or "").lower()


@pytest.mark.asyncio
@pytest.mark.parametrize("stdlib_name", ["os", "sys", "json", "typing"])
async def test_scaffold_refuses_stdlib_name_collision(tmp_path: Path, stdlib_name: str) -> None:
    agent = MetaScaffolder()
    result = await agent.run(
        goal=ScaffoldGoal(
            proposal=_proposal(),
            project_name=stdlib_name,
            target_dir=str(tmp_path),
        ),
        context=_ctx(),
    )
    assert not result.success
    assert "stdlib" in (result.error or "").lower() or "collid" in (result.error or "").lower()


@pytest.mark.asyncio
@pytest.mark.parametrize("traversal_name", ["../escape", "a/b"])
async def test_scaffold_refuses_path_traversal(tmp_path: Path, traversal_name: str) -> None:
    """Spec invariant: never writes outside target_dir. isidentifier() also rejects these."""
    agent = MetaScaffolder()
    result = await agent.run(
        goal=ScaffoldGoal(
            proposal=_proposal(),
            project_name=traversal_name,
            target_dir=str(tmp_path),
        ),
        context=_ctx(),
    )
    assert not result.success


@pytest.mark.asyncio
async def test_scaffold_refuses_non_empty_existing_dir(tmp_path: Path) -> None:
    existing = tmp_path / "my_app"
    existing.mkdir()
    (existing / "existing.txt").write_text("keep me")
    agent = MetaScaffolder()
    result = await agent.run(
        goal=ScaffoldGoal(
            proposal=_proposal(),
            project_name="my_app",
            target_dir=str(tmp_path),
        ),
        context=_ctx(),
    )
    assert not result.success
    assert "already exists" in (result.error or "").lower()
    assert (existing / "existing.txt").exists(), "must not have touched the dir"


@pytest.mark.asyncio
async def test_scaffold_with_overwrite_replaces_dir(tmp_path: Path) -> None:
    existing = tmp_path / "my_app"
    existing.mkdir()
    (existing / "existing.txt").write_text("replace me")
    agent = MetaScaffolder()
    result = await agent.run(
        goal=ScaffoldGoal(
            proposal=_proposal(),
            project_name="my_app",
            target_dir=str(tmp_path),
            overwrite=True,
        ),
        context=_ctx(),
    )
    assert result.success
    assert not (existing / "existing.txt").exists()
    assert (existing / "pyproject.toml").exists()


@pytest.mark.asyncio
async def test_scaffold_accepts_empty_existing_dir_without_overwrite(tmp_path: Path) -> None:
    existing = tmp_path / "my_app"
    existing.mkdir()
    agent = MetaScaffolder()
    result = await agent.run(
        goal=ScaffoldGoal(
            proposal=_proposal(),
            project_name="my_app",
            target_dir=str(tmp_path),
        ),
        context=_ctx(),
    )
    assert result.success


@pytest.mark.asyncio
async def test_scaffold_writes_generated_agent_sources(tmp_path: Path) -> None:
    agent_src = 'class EchoAgent:\n    """Toy agent."""\n    pass\nclass EchoGoal:\n    pass\n'
    agent = MetaScaffolder()
    result = await agent.run(
        goal=ScaffoldGoal(
            proposal=_proposal(),
            project_name="echo_app",
            target_dir=str(tmp_path),
            generated_agents=(
                GeneratedAgent(
                    class_name="EchoAgent",
                    goal_class_name="EchoGoal",
                    source=agent_src,
                ),
            ),
        ),
        context=_ctx(),
    )
    assert result.success
    agents_py = (Path(result.output.project_root) / "src" / "echo_app" / "agents.py").read_text()  # type: ignore[union-attr]
    assert "class EchoAgent" in agents_py


@pytest.mark.asyncio
async def test_scaffold_truncates_project_description_boundary(tmp_path: Path) -> None:
    """Generated pyproject description is bounded to the renderer contract."""
    proposal = _proposal().model_copy(update={"why": "x" * 240})
    agent = MetaScaffolder()
    result = await agent.run(
        goal=ScaffoldGoal(
            proposal=proposal,
            project_name="bounded_app",
            target_dir=str(tmp_path),
        ),
        context=_ctx(),
    )

    assert result.success
    pyproject = Path(result.output.project_root) / "pyproject.toml"  # type: ignore[union-attr]
    parsed = tomllib.loads(pyproject.read_text())
    assert parsed["project"]["description"] == "x" * 200


@pytest.mark.asyncio
async def test_concurrent_scaffold_same_target_serializes(tmp_path: Path) -> None:
    """Per-project lock prevents two concurrent writes from corrupting the tree."""
    agent = MetaScaffolder()
    goal = ScaffoldGoal(
        proposal=_proposal(),
        project_name="race_app",
        target_dir=str(tmp_path),
        overwrite=True,
    )
    results = await asyncio.gather(
        agent.run(goal=goal, context=_ctx()),
        agent.run(goal=goal, context=_ctx()),
    )
    # Both runs complete without crashing; the final tree is coherent.
    assert all(r.success for r in results)
    project_root = tmp_path / "race_app"
    assert (project_root / "pyproject.toml").exists()
    assert (project_root / "src" / "race_app" / "bootstrap.py").exists()

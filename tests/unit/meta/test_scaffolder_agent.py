"""Tests for MetaScaffolder agent — writes, rejects bad names, refuses overwrite."""

from __future__ import annotations

from pathlib import Path

import pytest

from cemaf.agents.base import AgentContext
from cemaf.meta.goals import (
    CapabilityDelta,
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
    agent_src = 'class EchoAgent:\n    """Toy agent."""\n    pass\n'
    agent = MetaScaffolder()
    result = await agent.run(
        goal=ScaffoldGoal(
            proposal=_proposal(),
            project_name="echo_app",
            target_dir=str(tmp_path),
            generated_agents=(agent_src,),
            agent_class_names=("EchoAgent",),
        ),
        context=_ctx(),
    )
    assert result.success
    agents_py = (Path(result.output.project_root) / "src" / "echo_app" / "agents.py").read_text()  # type: ignore[union-attr]
    assert "class EchoAgent" in agents_py

"""Integration — CEMAF uses CEMAF to build a runnable CEMAF-based app.

This is the headline proof for the self-hosting meta loop. Run MetaScaffolder
with a ProposalDoc + a synthesized agent source, then actually import the
resulting package and exercise its bootstrap.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path

import pytest

from cemaf.agents.base import AgentContext
from cemaf.agents.registry import AgentRegistry
from cemaf.audit.factories import create_audit_system
from cemaf.events.bus import InMemoryEventBus
from cemaf.knowledge.factories import create_knowledge_graph
from cemaf.mcp.bridges.openspec.protocols import SubprocessResult
from cemaf.mcp.bridges.openspec.runtime import FakeOpenSpecRuntime
from cemaf.mcp.bridges.openspec.workspace import OpenSpecWorkspace
from cemaf.meta.bootstrap import MetaServices, create_meta_executor
from cemaf.meta.goals import (
    CapabilityDelta,
    ProposalDoc,
    Requirement,
    ScaffoldGoal,
    Scenario,
)
from cemaf.meta.scaffolder import MetaScaffolder
from cemaf.orchestration.executor import ExecutorConfig
from cemaf.orchestration.services import RuntimeServices
from cemaf.tools.registry import ToolRegistry
from tests.integration.test_self_hosting import FakeMemoryManager


def _proposal() -> ProposalDoc:
    return ProposalDoc(
        change_id="build-echo-app",
        title="Echo App",
        why="A minimal CEMAF-based app that echoes inputs.",
        what_changes=("Scaffold the echo app",),
        impact=("affected: echo-capability",),
        tasks=("scaffold",),
        deltas=(
            CapabilityDelta(
                capability="echo",
                added_requirements=(
                    Requirement(
                        name="Echo returns input",
                        statement="The app SHALL echo its input.",
                        scenarios=(
                            Scenario(
                                name="baseline",
                                given=("an input",),
                                when=("run",),
                                then=("same output",),
                            ),
                        ),
                    ),
                ),
            ),
        ),
    )


def _load_package_from_src(*, project_root: Path, module_name: str):
    """Import the package directly from its src/ layout without installing it."""
    pkg_path = project_root / "src" / module_name
    spec = importlib.util.spec_from_file_location(
        module_name,
        pkg_path / "__init__.py",
        submodule_search_locations=[str(pkg_path)],
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
async def test_scaffolder_output_imports_and_runs(tmp_path: Path) -> None:
    """Generate → import → exercise bootstrap. No agents generated."""
    agent = MetaScaffolder()
    result = await agent.run(
        goal=ScaffoldGoal(
            proposal=_proposal(),
            project_name="echo_app",
            target_dir=str(tmp_path),
        ),
        context=AgentContext(run_id="t", agent_id="MetaScaffolder"),
    )
    assert result.success
    project_root = Path(result.output.project_root)  # type: ignore[union-attr]

    # Clean any stale module cached from prior tests on repeat runs
    for stale in [name for name in sys.modules if name == "echo_app" or name.startswith("echo_app.")]:
        del sys.modules[stale]

    _load_package_from_src(project_root=project_root, module_name="echo_app")
    bootstrap_mod = importlib.import_module("echo_app.bootstrap")
    dags_mod = importlib.import_module("echo_app.dags")

    registry = bootstrap_mod.create_app_registry()
    assert isinstance(registry, AgentRegistry)

    executor = bootstrap_mod.create_app_executor()
    assert executor is not None

    dag = dags_mod.create_main_dag()
    assert dag.name == "echo_app_main"


@pytest.mark.asyncio
async def test_scaffolder_registered_in_meta_executor(tmp_path: Path) -> None:
    """MetaScaffolder is registered whenever create_meta_executor runs."""
    event_bus = InMemoryEventBus()
    memory_manager = FakeMemoryManager()
    audit_log, audit_trail = create_audit_system(event_bus=event_bus)
    kg = create_knowledge_graph(memory_manager=memory_manager)  # type: ignore[arg-type]

    workspace = OpenSpecWorkspace(root=tmp_path / "openspec")
    runtime = FakeOpenSpecRuntime()
    runtime.register_result(("validate",), SubprocessResult(returncode=0, stdout=b"", stderr=b""))

    agent_registry = AgentRegistry()
    tool_registry = ToolRegistry()
    create_meta_executor(
        agent_registry=agent_registry,
        tool_registry=tool_registry,
        config=ExecutorConfig(enable_events=False),
        services=RuntimeServices(
            event_bus=event_bus,
            memory_manager=memory_manager,  # type: ignore[arg-type]
        ),
        meta_services=MetaServices(
            audit_log=audit_log,
            audit_trail=audit_trail,
            knowledge_graph=kg,
            openspec_runtime=runtime,
            openspec_workspace=workspace,
        ),
    )

    assert agent_registry.get("MetaScaffolder") is not None
    assert agent_registry.get("MetaSpecifier") is not None


@pytest.mark.asyncio
async def test_generated_app_package_layout_is_self_contained(tmp_path: Path) -> None:
    """The scaffolded project has everything needed to install via `uv sync`."""
    agent = MetaScaffolder()
    result = await agent.run(
        goal=ScaffoldGoal(
            proposal=_proposal(),
            project_name="standalone_app",
            target_dir=str(tmp_path),
        ),
        context=AgentContext(run_id="t", agent_id="MetaScaffolder"),
    )
    assert result.success
    root = Path(result.output.project_root)  # type: ignore[union-attr]
    assert (root / "pyproject.toml").exists()
    assert (root / "src" / "standalone_app" / "__init__.py").exists()
    assert (root / "src" / "standalone_app" / "bootstrap.py").exists()
    assert (root / "tests" / "test_smoke.py").exists()
    # pyproject declares the package path correctly
    pyproject = (root / "pyproject.toml").read_text()
    assert 'packages = ["src/standalone_app"]' in pyproject

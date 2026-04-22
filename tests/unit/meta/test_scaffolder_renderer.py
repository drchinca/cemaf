"""Tests for MetaScaffolder's pure-function project renderer."""

from __future__ import annotations

from cemaf.meta.goals import ProjectSkeleton
from cemaf.meta.scaffolder import render_project


def _skeleton(
    *,
    project_name: str = "my_app",
    agent_sources: tuple[str, ...] = (),
    agent_class_names: tuple[str, ...] = (),
) -> ProjectSkeleton:
    return ProjectSkeleton(
        project_name=project_name,
        module_name=project_name,
        title="My App",
        description="A CEMAF-based app.",
        agent_sources=agent_sources,
        agent_class_names=agent_class_names,
    )


def test_renders_expected_file_map() -> None:
    files = render_project(skeleton=_skeleton())
    assert set(files.keys()) == {
        "pyproject.toml",
        "README.md",
        "src/my_app/__init__.py",
        "src/my_app/agents.py",
        "src/my_app/dags.py",
        "src/my_app/bootstrap.py",
        "tests/__init__.py",
        "tests/test_smoke.py",
    }


def test_pyproject_declares_name_and_cemaf_dep() -> None:
    files = render_project(skeleton=_skeleton())
    pyproject = files["pyproject.toml"]
    assert 'name = "my_app"' in pyproject
    assert "cemaf" in pyproject


def test_render_is_deterministic() -> None:
    skel = _skeleton()
    assert render_project(skeleton=skel) == render_project(skeleton=skel)


def test_bootstrap_registers_generated_agents() -> None:
    files = render_project(
        skeleton=_skeleton(
            agent_sources=("class EchoAgent:\n    pass\n",),
            agent_class_names=("EchoAgent",),
        )
    )
    bootstrap = files["src/my_app/bootstrap.py"]
    assert "from my_app.agents import" in bootstrap
    assert "EchoAgent" in bootstrap
    assert "registry.register_agent(agent_instance=EchoAgent()" in bootstrap


def test_bootstrap_handles_zero_agents_cleanly() -> None:
    files = render_project(skeleton=_skeleton())
    bootstrap = files["src/my_app/bootstrap.py"]
    assert "no agents registered" in bootstrap
    assert "create_app_executor" in bootstrap


def test_agents_file_contains_generated_sources() -> None:
    src = "class EchoAgent:\n    pass\n"
    files = render_project(skeleton=_skeleton(agent_sources=(src,), agent_class_names=("EchoAgent",)))
    assert src.strip() in files["src/my_app/agents.py"]


def test_smoke_test_imports_package_and_dag() -> None:
    files = render_project(skeleton=_skeleton())
    smoke = files["tests/test_smoke.py"]
    assert "from my_app.bootstrap import" in smoke
    assert "from my_app.dags import create_main_dag" in smoke

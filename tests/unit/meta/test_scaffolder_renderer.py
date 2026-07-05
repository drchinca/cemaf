"""Tests for MetaScaffolder's pure-function project renderer."""

from __future__ import annotations

import tomllib

import pytest

from cemaf.agents.base import AgentContext
from cemaf.meta.agents import AgentSynthesizer
from cemaf.meta.goals import GeneratedAgent, ProjectSkeleton, SynthesizerGoal
from cemaf.meta.scaffolder import render_project


def _skeleton(
    *,
    project_name: str = "my_app",
    generated_agents: tuple[GeneratedAgent, ...] = (),
    cemaf_source: str = "",
    description: str = "A CEMAF-based app.",
    title: str = "My App",
) -> ProjectSkeleton:
    return ProjectSkeleton(
        project_name=project_name,
        module_name=project_name,
        title=title,
        description=description,
        generated_agents=generated_agents,
        cemaf_source=cemaf_source,
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


def test_pyproject_is_valid_toml() -> None:
    """Regression: earlier versions used naive f-string interpolation that broke on quotes."""
    files = render_project(skeleton=_skeleton())
    tomllib.loads(files["pyproject.toml"])


def test_pyproject_declares_name_and_cemaf_dep() -> None:
    files = render_project(skeleton=_skeleton())
    parsed = tomllib.loads(files["pyproject.toml"])
    assert parsed["project"]["name"] == "my_app"
    assert "cemaf" in parsed["project"]["dependencies"]


def test_pyproject_uses_injected_cemaf_source() -> None:
    files = render_project(
        skeleton=_skeleton(cemaf_source="cemaf @ git+https://example.invalid/cemaf.git@abc123")
    )
    parsed = tomllib.loads(files["pyproject.toml"])
    assert parsed["project"]["dependencies"] == [
        "cemaf @ git+https://example.invalid/cemaf.git@abc123",
        "pydantic>=2.0",
    ]
    # No default-source note when explicitly set
    assert "FIXME" not in files["pyproject.toml"]
    assert "CEMAF dependency defaults" not in files["pyproject.toml"]


def test_pyproject_notes_default_dependency_without_cemaf_source() -> None:
    files = render_project(skeleton=_skeleton())
    assert "FIXME" not in files["pyproject.toml"]
    assert "CEMAF dependency defaults to the package name" in files["pyproject.toml"]


@pytest.mark.parametrize(
    "hostile_text",
    [
        'contains "double quotes"',
        "has a backslash \\ escape",
        "contains a newline\nmid-string",
        "contains a tab\tcharacter",
    ],
)
def test_description_with_hostile_chars_still_valid_toml(hostile_text: str) -> None:
    """TOML injection regression: description goes into basic string, must escape."""
    files = render_project(skeleton=_skeleton(description=hostile_text))
    parsed = tomllib.loads(files["pyproject.toml"])
    assert parsed["project"]["description"] == hostile_text


def test_description_with_quote_produces_parseable_dags_py() -> None:
    """dags.py puts description in a Python string literal — must be escapable."""
    import ast

    files = render_project(skeleton=_skeleton(description='has "quotes"'))
    ast.parse(files["src/my_app/dags.py"])


def test_render_is_deterministic() -> None:
    skel = _skeleton()
    assert render_project(skeleton=skel) == render_project(skeleton=skel)


def test_bootstrap_registers_generated_agents_with_goal_classes() -> None:
    """Regression: bootstrap.py MUST import the Goal class too or it NameErrors at runtime."""
    files = render_project(
        skeleton=_skeleton(
            generated_agents=(
                GeneratedAgent(
                    class_name="EchoAgent",
                    goal_class_name="EchoGoal",
                    source="class EchoAgent:\n    pass\n\nclass EchoGoal:\n    pass\n",
                ),
            )
        )
    )
    bootstrap = files["src/my_app/bootstrap.py"]
    assert "from my_app.agents import" in bootstrap
    assert "EchoAgent" in bootstrap
    assert "EchoGoal" in bootstrap
    assert "registry.register_agent(agent_instance=EchoAgent(), goal_type=EchoGoal)" in bootstrap


def test_bootstrap_handles_zero_agents_cleanly() -> None:
    files = render_project(skeleton=_skeleton())
    bootstrap = files["src/my_app/bootstrap.py"]
    assert "no agents registered" in bootstrap
    assert "create_app_executor" in bootstrap


def test_agents_file_contains_generated_sources() -> None:
    src = "class EchoAgent:\n    pass\nclass EchoGoal:\n    pass\n"
    files = render_project(
        skeleton=_skeleton(
            generated_agents=(GeneratedAgent(class_name="EchoAgent", goal_class_name="EchoGoal", source=src),)
        )
    )
    assert src.strip() in files["src/my_app/agents.py"]


@pytest.mark.asyncio
async def test_generated_synthesizer_source_has_no_unused_skill_import() -> None:
    """Generated app agent source should not carry unused framework imports."""
    result = await AgentSynthesizer().run(
        goal=SynthesizerGoal(agent_name="Echo", description="Echo input"),
        context=AgentContext(run_id="test", agent_id="MetaSynthesizer"),
    )
    assert result.success
    source = result.output.agent_code  # type: ignore[union-attr]
    assert "from cemaf.skills.base import Skill" not in source
    assert "from __future__ import annotations" not in source


def test_dags_py_drops_unused_imports() -> None:
    """Generated dags.py should not import NodeID/Edge/Node if unused — fails ruff otherwise."""
    files = render_project(skeleton=_skeleton())
    dags_src = files["src/my_app/dags.py"]
    assert "NodeID" not in dags_src
    assert "Edge" not in dags_src


def test_smoke_test_imports_package_and_dag() -> None:
    files = render_project(skeleton=_skeleton())
    smoke = files["tests/test_smoke.py"]
    assert "from my_app.bootstrap import" in smoke
    assert "from my_app.dags import create_main_dag" in smoke

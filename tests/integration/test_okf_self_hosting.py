"""Architecture, registries, governed descriptions, docs tools, and meta execution."""

from pathlib import Path

import pytest

from cemaf.docs_api import DocIndex, OKFDocSource
from cemaf.docs_api.okf import okf_entry_path
from cemaf.knowledge import OKFBundle


async def test_self_hosted_roundtrip_and_meta_query(tmp_path: Path) -> None:
    from examples.app_shapes.okf_self_hosting import run_example

    bundle = await run_example(tmp_path / "bundle")
    types = {doc.type for doc in bundle.documents}
    assert {
        "Module",
        "Protocol",
        "Agent",
        "Skill",
        "Tool",
        "Capability",
        "Access Policy",
        "Principal",
        "Ontology",
    } <= types
    # The skill's workspace and the registries' dependency objects aren't serialized.
    assert str(tmp_path) not in "\n".join(doc.render() for doc in bundle.documents)
    index = DocIndex()
    index.add_from(sources=(OKFDocSource(bundle, "self"),))
    assert index.get("agent:MetaKnowledgeGraph") is not None
    assert index.get("skill:read_file") is not None
    policy = index.get("grant:curator:0")
    assert policy is not None and policy.metadata["abac_conditions"] == {"department": "research"}


def test_cli_exports_complete_framework_and_refuses_overwrite(tmp_path: Path, monkeypatch, capsys) -> None:
    from cemaf.cli import main

    root = Path(__file__).resolve().parents[2]
    destination = tmp_path / "framework"
    monkeypatch.setattr(
        "sys.argv", ["cemaf", "docs", "export-okf", "--repo-root", str(root), "--output", str(destination)]
    )
    main()
    assert "Exported" in capsys.readouterr().out
    bundle = OKFBundle.load(destination)
    index = DocIndex()
    index.add_from(sources=(OKFDocSource(bundle, "cemaf"),))
    for entry_id in (
        "docs/self-hosting.md",
        "docs/modules.md",
        "docs/patterns.md",
        "module:cemaf.orchestration.services",
        "module:cemaf.meta.bootstrap",
        "contract:cemaf.knowledge.protocols.KnowledgeGraph",
        "contract:cemaf.skills.protocols.Skill",
        "contract:cemaf.security.mappings.MappingProvider",
        "contract:cemaf.security.rbac.ScopeAuthorizer",
        "agent:MetaArchitect",
        "capability:research",
    ):
        assert index.get(entry_id) is not None, entry_id
    assert (
        index.get("contract:cemaf.skills.coding.fileops.ReadFileSkill").metadata["okf"]["okf_type"] == "Skill"
    )
    revision = bundle.revision
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2
    assert OKFBundle.load(destination).revision == revision


def test_live_registry_exports_structural_agents_and_skills(tmp_path: Path) -> None:
    from pydantic import BaseModel

    from cemaf.agents.registry import AgentRegistry
    from cemaf.agents.selection import Capability
    from cemaf.docs_api import build_okf_bundle
    from cemaf.meta.okf import RuntimeDocSource
    from cemaf.skills.coding.fileops import ReadFileSkill
    from cemaf.skills.registry import SkillRegistry
    from cemaf.tools.registry import ToolRegistry

    class Goal(BaseModel):
        query: str

    skill = ReadFileSkill(workspace=tmp_path)

    from cemaf.meta.tools import GenerateDAGTool

    tool = GenerateDAGTool()

    class StructuralSkill:
        id = "compose"
        description = "Compose a workflow with an existing tool."
        tools = (tool,)

        async def execute(self, input, context):
            raise AssertionError("Export must not execute the skill")

    composed_skill = StructuralSkill()

    class StructuralAgent:
        id = "reader"
        description = "Read selected project context."
        skills = (skill, composed_skill)
        private_credential = "must-not-export-this"

        async def run(self, goal, context):
            raise AssertionError("Export must not run the agent")

    agents, skills = AgentRegistry(), SkillRegistry()
    agents.register_agent(StructuralAgent(), goal_type=Goal, capabilities=frozenset({Capability.RESEARCH}))
    skills.register_instance(skill)
    skills.register_instance(composed_skill)
    tools = ToolRegistry()
    tools.register_instance(tool)
    bundle = build_okf_bundle(sources=(RuntimeDocSource(agents, tools, skills),))
    agent = bundle.get(okf_entry_path("agent:reader")[:-3])
    capability = bundle.get(okf_entry_path("capability:research")[:-3])
    assert agent.frontmatter["cemaf_entry"]["metadata"]["goal_schema"]["required"] == ["query"]
    assert capability.frontmatter["cemaf_entry"]["metadata"]["candidate_count"] == 1
    assert f"/{okf_entry_path('skill:read_file')}" in agent.links()
    composed = bundle.get(okf_entry_path("skill:compose")[:-3])
    assert f"/{okf_entry_path('tool:meta_generate_dag')}" in composed.links()
    assert "must-not-export-this" not in "".join(doc.render() for doc in bundle.documents)

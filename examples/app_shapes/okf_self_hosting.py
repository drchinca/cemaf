"""Self-hosted CEMAF reads its own OKF capabilities and governed descriptions.

Run: uv run python examples/app_shapes/okf_self_hosting.py
"""

import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory

from cemaf import DAG, Node
from cemaf.agents.registry import AgentRegistry
from cemaf.context.patch import SecurityLevel
from cemaf.core.enums import MemoryScope
from cemaf.docs_api import (
    CemafDocsSearchTool,
    DocIndex,
    OKFDocSource,
    PythonContractDocSource,
    build_okf_bundle,
)
from cemaf.events.bus import InMemoryEventBus
from cemaf.knowledge import OKFBundle, create_knowledge_graph, import_okf_bundle
from cemaf.memory.factories import create_memory_manager
from cemaf.meta.bootstrap import MetaServices, create_meta_executor
from cemaf.meta.okf import RuntimeDocSource
from cemaf.orchestration.services import RuntimeServices
from cemaf.security.mappings import DictMappingProvider
from cemaf.security.okf import GovernanceDocSource, GovernedDocSource
from cemaf.security.rbac import RBACEnforcer
from cemaf.skills.coding.fileops import ReadFileSkill
from cemaf.skills.registry import SkillRegistry
from cemaf.tools.registry import ToolRegistry


async def run_example(destination: Path) -> OKFBundle:
    agents, tools, skills = AgentRegistry(), ToolRegistry(), SkillRegistry()
    skills.register_instance(ReadFileSkill(workspace=destination.parent))
    memory = create_memory_manager()
    graph = create_knowledge_graph(memory, clearance=SecurityLevel.CONFIDENTIAL)
    executor = create_meta_executor(
        agent_registry=agents,
        tool_registry=tools,
        services=RuntimeServices(memory_manager=memory, knowledge_graph=graph, event_bus=InMemoryEventBus()),
        meta_services=MetaServices(knowledge_graph=graph),
        clearance=SecurityLevel.CONFIDENTIAL,
    )
    provider = DictMappingProvider(
        {
            "users": {
                "curator": {
                    "attributes": {"department": "research"},
                    "direct_access": [
                        {
                            "scope": "project",
                            "scope_path_prefix": "/governance/",
                            "actions": ["read"],
                            "abac_conditions": {"department": "research"},
                        }
                    ],
                }
            }
        }
    )
    governance = GovernanceDocSource(provider=provider, principal_ids=("curator",))
    governed = GovernedDocSource(
        source=governance,
        authorizer=RBACEnforcer(provider),
        principal_id="curator",
        bindings={entry.id: (MemoryScope.PROJECT, "/governance/" + entry.id) for entry in governance.load()},
    )
    package = Path(__file__).resolve().parents[2] / "src" / "cemaf" / "security"
    bundle = build_okf_bundle(
        sources=(
            RuntimeDocSource(agent_registry=agents, tool_registry=tools, skill_registry=skills),
            PythonContractDocSource(root=package, package="cemaf.security"),
            governed,
        )
    )
    bundle.write(destination)
    restored = OKFBundle.load(destination)
    index = DocIndex()
    index.add_from(sources=(OKFDocSource(bundle=restored, bundle_id="self"),))
    search = CemafDocsSearchTool(index=index)
    tools.register_instance(search)
    found = await search.execute(query="MappingProvider", k=3)
    assert found.success and found.data["count"] > 0
    await import_okf_bundle(restored, graph=graph, bundle_id="self")
    dag = DAG(name="okf-self-knowledge").add_node(
        Node.agent(
            id="query",
            name="Query own contracts",
            agent_id="MetaKnowledgeGraph",
            input_mapping={"operation": "query", "query": "MappingProvider", "entity_type": "concept"},
            output_key="knowledge",
            structured_output=True,
        )
    )
    result = await executor.run(dag=dag)
    assert result.success, result.error
    assert result.final_context.get("knowledge")["stats"]["count"] > 0
    assert not RBACEnforcer(provider).can("outsider", "read", MemoryScope.PROJECT)
    print(f"Self-hosting OKF: {len(bundle.documents)} concepts; docs tools and meta-agent query passed")
    return restored


async def main() -> None:
    with TemporaryDirectory(prefix="cemaf-self-okf-") as directory:
        await run_example(Path(directory) / "knowledge")


if __name__ == "__main__":
    asyncio.run(main())

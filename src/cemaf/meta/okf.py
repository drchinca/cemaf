"""Live runtime descriptions for self-hosted OKF exchange, via DocSource."""

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from cemaf.agents.registry import AgentRegistry
from cemaf.agents.selection import Capability
from cemaf.docs_api.index import DocEntry, DocEntryKind
from cemaf.knowledge.okf import OKFBundle
from cemaf.skills.registry import SkillRegistry
from cemaf.tools.registry import ToolRegistry


def build_cemaf_okf_bundle(*, repo_root: Path) -> OKFBundle:
    """Describe repository architecture and an offline self-hosting composition."""
    from cemaf.docs_api.contracts import PythonContractDocSource
    from cemaf.docs_api.okf import build_okf_bundle
    from cemaf.docs_api.sources import MarkdownDocSource
    from cemaf.events.bus import InMemoryEventBus
    from cemaf.memory.factories import create_memory_manager
    from cemaf.meta.bootstrap import create_meta_executor
    from cemaf.orchestration.services import RuntimeServices

    agents, tools = AgentRegistry(), ToolRegistry()
    create_meta_executor(
        agent_registry=agents,
        tool_registry=tools,
        services=RuntimeServices(memory_manager=create_memory_manager(), event_bus=InMemoryEventBus()),
    )
    return build_okf_bundle(
        sources=(
            MarkdownDocSource(root=repo_root / "docs"),
            PythonContractDocSource(root=repo_root / "src" / "cemaf"),
            RuntimeDocSource(agent_registry=agents, tool_registry=tools),
        )
    )


@dataclass(frozen=True)
class RuntimeDocSource:
    """Export registered public interfaces without serializing dependencies.

    Inject registries from the composition root after create_meta_executor has
    registered meta-agents. No agents, skills, or tools are executed here.
    """

    agent_registry: AgentRegistry
    tool_registry: ToolRegistry
    skill_registry: SkillRegistry | None = None

    @property
    def name(self) -> str:
        return "runtime-registries"

    def load(self) -> Iterable[DocEntry]:
        for agent in sorted(self.agent_registry.list_items(), key=lambda item: str(item.id)):
            agent_id = str(agent.id)
            goal = self.agent_registry.get_goal_type(agent_id)
            capabilities = [
                cap.value
                for cap in Capability
                if any(
                    str(candidate.id) == agent_id
                    for candidate in self.agent_registry.get_candidates(capability=cap)
                )
            ]
            yield DocEntry(
                id=f"agent:{agent_id}",
                kind=DocEntryKind.SPEC,
                title=agent_id,
                body=agent.description,
                source=self.name,
                metadata={
                    "okf_type": "Agent",
                    "definition_kind": "registered",
                    "goal_schema": goal.model_json_schema() if goal is not None else {},
                    "capabilities": capabilities,
                    "related_ids": [
                        *(f"capability:{cap}" for cap in capabilities),
                        *(f"skill:{skill.id}" for skill in agent.skills),
                    ],
                },
            )
        for capability in Capability:
            agents = self.agent_registry.get_candidates(capability=capability)
            yield DocEntry(
                id=f"capability:{capability.value}",
                kind=DocEntryKind.SPEC,
                title=capability.value,
                body=(
                    "A capability recognized by CEMAF's agent selector. "
                    "Available candidates reflect this registry snapshot."
                ),
                source=self.name,
                metadata={
                    "okf_type": "Capability",
                    "candidate_count": len(agents),
                    "related_ids": sorted(f"agent:{agent.id}" for agent in agents),
                },
            )
        for tool in sorted(self.tool_registry.list_tools(), key=lambda item: str(item.id)):
            schema = tool.schema
            yield DocEntry(
                id=f"tool:{tool.id}",
                kind=DocEntryKind.SPEC,
                title=schema.name,
                body=schema.description,
                source=self.name,
                metadata={
                    "okf_type": "Tool",
                    "definition_kind": "registered",
                    "parameters": schema.parameters,
                    "required": list(schema.required),
                    "is_read_only": schema.is_read_only,
                    "is_destructive": schema.is_destructive,
                    "is_concurrent_safe": schema.is_concurrent_safe,
                },
            )
        if self.skill_registry is not None:
            for skill in sorted(self.skill_registry.list_skills(), key=lambda item: str(item.id)):
                yield DocEntry(
                    id=f"skill:{skill.id}",
                    kind=DocEntryKind.SPEC,
                    title=str(skill.id),
                    body=skill.description,
                    source=self.name,
                    metadata={
                        "okf_type": "Skill",
                        "definition_kind": "registered",
                        "related_ids": [f"tool:{tool.id}" for tool in skill.tools],
                    },
                )

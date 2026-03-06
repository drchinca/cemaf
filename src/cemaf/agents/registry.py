"""Agent Registry v2 - Dynamic, domain-scoped agent registration."""

import logging
from typing import Any

from pydantic import BaseModel

from cemaf.agents.context_agents import (
    LibrarianAgent,
    LibrarianGoal,
    ResearcherAgent,
    ResearcherGoal,
    SummarizerAgent,
    SummarizerGoal,
    WriterAgent,
    WriterGoal,
)
from cemaf.agents.protocols import Agent
from cemaf.core.registry import BaseRegistry
from cemaf.llm.protocols import LLMClient
from cemaf.retrieval.protocols import VectorStore

logger = logging.getLogger(__name__)

# Agent class to goal type mapping for built-in agents
_BUILTIN_GOAL_TYPES: dict[str, type[BaseModel]] = {
    "Librarian": LibrarianGoal,
    "Researcher": ResearcherGoal,
    "Summarizer": SummarizerGoal,
    "Writer": WriterGoal,
}

_BUILTIN_AGENT_CLASSES: dict[str, type[Agent[Any, Any]]] = {
    "Librarian": LibrarianAgent,
    "Researcher": ResearcherAgent,
    "Summarizer": SummarizerAgent,
    "Writer": WriterAgent,
}


class AgentRegistry(BaseRegistry[Agent[Any, Any]]):
    """Dynamic, domain-scoped agent registry extending BaseRegistry."""

    def __init__(
        self,
        *,
        dependencies: dict[str, object] | None = None,
        namespace: str = "",
    ) -> None:
        super().__init__(
            item_type_name="Agent",
            id_attribute="id",
            dependencies=dependencies or {},
            namespace=namespace,
        )
        self._goal_types: dict[str, type[BaseModel]] = {}
        self._domain_agents: dict[str, set[str]] = {}

    def _implements_protocol(self, obj: Any) -> bool:
        """Check if object implements Agent protocol."""
        if isinstance(obj, type):
            return all(hasattr(obj, attr) for attr in ("id", "description", "skills", "run"))
        return isinstance(obj, Agent)

    def register_agent(
        self,
        agent_instance: Agent[Any, Any],
        goal_type: type[BaseModel] | None = None,
        domain_id: str | None = None,
    ) -> None:
        """Register an agent instance with optional domain scoping."""
        self.register_instance(item=agent_instance)
        agent_key = str(agent_instance.id)
        if goal_type is not None:
            self._goal_types[agent_key] = goal_type
        if domain_id is not None:
            self._domain_agents.setdefault(domain_id, set()).add(agent_key)

    def get_agent_class(self, agent_name: str) -> type[Agent[Any, Any]] | None:
        """Get agent class by name from built-in agents."""
        return _BUILTIN_AGENT_CLASSES.get(agent_name)

    def get_goal_type(self, agent_name: str) -> type[BaseModel] | None:
        """Get goal type for agent by name."""
        return self._goal_types.get(agent_name) or _BUILTIN_GOAL_TYPES.get(agent_name)

    def get_for_domain(self, domain_id: str) -> list[Agent[Any, Any]]:
        """Get agents registered for a specific domain."""
        agent_ids = self._domain_agents.get(domain_id, set())
        return [agent for agent in self.list_items() if str(agent.id) in agent_ids]

    def get_capabilities_description(self) -> str:
        """Auto-generate capabilities description from registered agents."""
        agents = self.list_items()
        if not agents:
            return "No agents registered."

        lines = [
            "Available Agents and their required inputs.",
            "CRITICAL: You MUST use the exact input key names provided for each agent.",
            "",
        ]
        for i, agent in enumerate(agents, start=1):
            lines.append(f"{i}. AGENT: {agent.id}")
            lines.append(f"   ROLE: {agent.description}")
            goal_type = self.get_goal_type(str(agent.id))
            if goal_type and hasattr(goal_type, "model_fields"):
                lines.append("   INPUTS:")
                for fname, finfo in goal_type.model_fields.items():
                    ann = finfo.annotation
                    annotation = ann.__name__ if ann is not None and hasattr(ann, "__name__") else str(ann)
                    lines.append(f'     - "{fname}": ({annotation})')
            lines.append("")
        return "\n".join(lines)

    def create_agent(
        self,
        agent_name: str,
        vector_store: VectorStore | None = None,
        llm_client: LLMClient | None = None,
        namespace_context: str | None = None,
        namespace_knowledge: str | None = None,
        librarian_top_k: int = 1,
        researcher_top_k: int = 15,
    ) -> Agent[Any, Any] | None:
        """Create a built-in agent with dependencies."""
        # Check already registered
        existing = self.get(agent_name)
        if existing is not None:
            return existing

        try:
            if agent_name == "Librarian":
                if not vector_store:
                    raise ValueError("Librarian requires vector_store")
                return LibrarianAgent(
                    vector_store=vector_store,
                    namespace_context=namespace_context,
                    top_k=librarian_top_k,
                )
            elif agent_name == "Researcher":
                if not vector_store or not llm_client:
                    raise ValueError("Researcher requires vector_store and llm_client")
                return ResearcherAgent(
                    vector_store=vector_store,
                    llm_client=llm_client,
                    namespace_knowledge=namespace_knowledge,
                    top_k=researcher_top_k,
                )
            elif agent_name == "Summarizer":
                if not llm_client:
                    raise ValueError("Summarizer requires llm_client")
                return SummarizerAgent(llm_client=llm_client)
            elif agent_name == "Writer":
                if not llm_client:
                    raise ValueError("Writer requires llm_client")
                return WriterAgent(llm_client=llm_client)
            return None
        except Exception as e:
            logger.error("Failed to create agent '%s': %s", agent_name, e, exc_info=True)
            return None

    def list_agents(self) -> list[str]:
        """List all registered agent IDs."""
        return [str(agent.id) for agent in self.list_items()]


def create_default_registry() -> AgentRegistry:
    """Factory to create a fresh default registry."""
    return AgentRegistry()


# Global registry instance
AGENT_TOOLKIT = create_default_registry()

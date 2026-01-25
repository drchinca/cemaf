"""
Agent Registry - Central registry for context engineering agents.

Provides a registry pattern for discovering and accessing agents,
along with capability descriptions for autonomous planning.
"""

import logging
from typing import Any

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
from cemaf.llm.protocols import LLMClient
from cemaf.retrieval.protocols import VectorStore

logger = logging.getLogger(__name__)


class AgentRegistry:
    """
    Registry for context engineering agents.

    Provides:
    - Agent lookup by name
    - Capability descriptions for planning
    - Factory methods for creating agents with dependencies
    """

    def __init__(self) -> None:
        self._agents: dict[str, type[Agent[Any, Any]]] = {
            "Librarian": LibrarianAgent,
            "Researcher": ResearcherAgent,
            "Summarizer": SummarizerAgent,
            "Writer": WriterAgent,
        }
        self._goal_types: dict[str, type[Any]] = {
            "Librarian": LibrarianGoal,
            "Researcher": ResearcherGoal,
            "Summarizer": SummarizerGoal,
            "Writer": WriterGoal,
        }

    def get_agent_class(self, agent_name: str) -> type[Agent[Any, Any]] | None:
        """Get agent class by name."""
        return self._agents.get(agent_name)

    def get_goal_type(self, agent_name: str) -> type | None:
        """Get goal type for agent by name."""
        return self._goal_types.get(agent_name)

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
        """
        Create an agent instance with dependencies.

        Args:
            agent_name: Name of the agent to create
            vector_store: Vector store for retrieval (required for Librarian/Researcher)
            llm_client: LLM client for generation (required for Researcher/Summarizer/Writer)
            namespace_context: Namespace for blueprint storage
            namespace_knowledge: Namespace for knowledge storage

        Returns:
            Agent instance or None if agent not found
        """
        agent_class = self.get_agent_class(agent_name)
        if not agent_class:
            logger.error(f"Agent '{agent_name}' not found in registry.")
            return None

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
            logger.error(f"Failed to create agent '{agent_name}': {e}", exc_info=True)
            return None

    def get_capabilities_description(self) -> str:
        """
        Returns a structured description of the agents for the Planner LLM.

        This description is used by autonomous planning agents to understand
        what agents are available and what inputs they require.
        """
        return """
Available Agents and their required inputs.
CRITICAL: You MUST use the exact input key names provided for each agent.

1. AGENT: Librarian
   ROLE: Retrieves Semantic Blueprints (style/structure instructions).
   INPUTS:
     - "intent_query": (String) A descriptive phrase of the desired style.
   OUTPUT: The blueprint structure (JSON string).

2. AGENT: Researcher
   ROLE: Retrieves and synthesizes factual information on a topic.
   INPUTS:
     - "topic_query": (String) The subject matter to research.
   OUTPUT: Synthesized facts (String).

3. AGENT: Summarizer
   ROLE: Reduces text to concise summary for managing token counts.
   INPUTS:
     - "text_to_summarize": (String/Reference) The long text to summarize.
     - "summary_objective": (String) Goal for summary (e.g., "Extract key specs").
   OUTPUT: A dictionary containing the summary: {"summary": "..."}.

4. AGENT: Writer
   ROLE: Generates or rewrites content by applying a Blueprint to source material.
   INPUTS:
     - "blueprint": (String/Reference) The style instructions (usually from Librarian).
     - "facts": (String/Reference) Factual information (usually from Researcher or Summarizer).
     - "previous_content": (String/Reference) Existing text for rewriting.
   OUTPUT: The final generated text (String).
"""

    def list_agents(self) -> list[str]:
        """List all registered agent names."""
        return list(self._agents.keys())


# Global registry instance
AGENT_TOOLKIT = AgentRegistry()
logger.info("Agent Registry initialized and fully upgraded.")

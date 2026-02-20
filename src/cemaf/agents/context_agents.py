"""
Context Engineering Agents - Librarian, Researcher, Summarizer, and Writer.

These agents implement the core workflow for semantic blueprint-based content generation:
1. Librarian: Retrieves semantic blueprints from vector store
2. Researcher: High-fidelity retrieval (k=15) with synthesis
3. Summarizer: Context density reduction for token management
4. Writer: Deterministic content generation using blueprints
"""

import json
import logging
from typing import Any

from pydantic import BaseModel, Field

from cemaf.agents.base import Agent, AgentContext, AgentResult, AgentState
from cemaf.blueprint.core import Blueprint
from cemaf.core.types import AgentID
from cemaf.llm.protocols import LLMClient, Message
from cemaf.observability.token_telemetry import extract_token_metadata
from cemaf.retrieval.protocols import SearchResult, VectorStore

logger = logging.getLogger(__name__)


# ============================================================================
# Goal Models (Pydantic Inputs)
# ============================================================================


class LibrarianGoal(BaseModel):
    """Goal for Librarian agent - retrieve semantic blueprint."""

    intent_query: str = Field(description="Descriptive phrase of the desired style/structure")


class ResearcherGoal(BaseModel):
    """Goal for Researcher agent - retrieve and synthesize facts."""

    topic_query: str = Field(description="Subject matter to research")


class SummarizerGoal(BaseModel):
    """Goal for Summarizer agent - reduce context density."""

    text_to_summarize: str = Field(description="Long text to be summarized")
    summary_objective: str = Field(description="Clear goal for the summary")


class WriterGoal(BaseModel):
    """Goal for Writer agent - generate content using blueprint."""

    blueprint: str | dict[str, Any] = Field(description="Style instructions (usually from Librarian)")
    facts: str | dict[str, Any] | None = Field(
        default=None, description="Factual information (from Researcher/Summarizer)"
    )
    previous_content: str | None = Field(default=None, description="Existing text for rewriting")


# ============================================================================
# Result Models
# ============================================================================


class LibrarianResult(BaseModel):
    """Result from Librarian agent."""

    blueprint_json: str = Field(description="Blueprint structure as JSON string")


class ResearcherResult(BaseModel):
    """Result from Researcher agent."""

    facts: str = Field(description="Synthesized factual report")


class SummarizerResult(BaseModel):
    """Result from Summarizer agent."""

    summary: str = Field(description="Compressed summary text")


class WriterResult(BaseModel):
    """Result from Writer agent."""

    report: str = Field(description="Generated content")


# ============================================================================
# Agent Implementations
# ============================================================================


class LibrarianAgent(Agent[LibrarianGoal, LibrarianResult]):
    """
    Retrieves the appropriate Semantic Blueprint from vector store.

    Searches for blueprints based on intent query and returns the best match.
    """

    def __init__(
        self,
        vector_store: VectorStore,
        namespace_context: str | None = None,
        top_k: int = 1,
    ):
        self._vector_store = vector_store
        self._namespace_context = namespace_context or "blueprints"
        self._top_k = max(1, top_k)  # Ensure at least 1

    @property
    def id(self) -> AgentID:
        return AgentID("Librarian")

    @property
    def description(self) -> str:
        return "Retrieves Semantic Blueprints (style/structure instructions) from vector store"

    @property
    def skills(self) -> tuple[Any, ...]:
        return ()

    async def run(self, goal: LibrarianGoal, context: AgentContext) -> AgentResult[LibrarianResult]:
        """Execute blueprint retrieval."""
        logger.info("[Librarian] Activated. Analyzing intent...")
        state = AgentState()

        try:
            # Search for blueprint in vector store
            # Note: VectorStore.search_by_text handles embedding generation
            results = await self._vector_store.search_by_text(
                query_text=goal.intent_query,
                k=self._top_k,
                filter={"namespace": self._namespace_context} if self._namespace_context else None,
            )

            if results:
                match: SearchResult = results[0]
                logger.info(f"[Librarian] Found blueprint '{match.document.id}' (Score: {match.score:.2f})")

                # Extract blueprint JSON from metadata
                blueprint_json = match.document.metadata.get("blueprint_json", "")
                if not blueprint_json:
                    # Try to parse document content as blueprint JSON
                    try:
                        blueprint_data = json.loads(match.document.content)
                        blueprint_json = json.dumps(blueprint_data)
                    except (json.JSONDecodeError, TypeError):
                        blueprint_json = json.dumps({"instruction": match.document.content})

                result = LibrarianResult(blueprint_json=blueprint_json)
                return AgentResult.ok(result, state.next(status=state.status))
            else:
                logger.warning("[Librarian] No blueprint found. Returning default.")
                default_blueprint = json.dumps({"instruction": "Generate content neutrally."})
                result = LibrarianResult(blueprint_json=default_blueprint)
                return AgentResult.ok(result, state.next(status=state.status))

        except Exception as e:
            logger.error(f"[Librarian] Error: {e}", exc_info=True)
            return AgentResult.fail(f"Librarian error: {str(e)}", state)


class ResearcherAgent(Agent[ResearcherGoal, ResearcherResult]):
    """
    Retrieves facts with High-Fidelity (k=15) and synthesizes them.

    Uses high-fidelity retrieval to ensure all relevant documents are captured,
    then synthesizes the evidence into a factual report.
    """

    def __init__(
        self,
        vector_store: VectorStore,
        llm_client: LLMClient,
        namespace_knowledge: str | None = None,
        top_k: int = 15,
    ):
        self._vector_store = vector_store
        self._llm_client = llm_client
        self._namespace_knowledge = namespace_knowledge or "knowledge"
        self._top_k = max(1, top_k)  # Ensure at least 1

    @property
    def id(self) -> AgentID:
        return AgentID("Researcher")

    @property
    def description(self) -> str:
        return f"Synthesizes factual information with high-fidelity retrieval (k={self._top_k})"

    @property
    def skills(self) -> tuple[Any, ...]:
        return ()

    async def run(self, goal: ResearcherGoal, context: AgentContext) -> AgentResult[ResearcherResult]:
        """Execute high-fidelity research."""
        logger.info("[Researcher] Activated. Gathering evidence...")
        state = AgentState()

        try:
            # High-fidelity retrieval: configurable k ensures all ingested documents are caught
            results = await self._vector_store.search_by_text(
                query_text=goal.topic_query,
                k=self._top_k,
                filter={"namespace": self._namespace_knowledge} if self._namespace_knowledge else None,
            )

            if not results:
                logger.warning("[Researcher] No evidence found.")
                return AgentResult.ok(ResearcherResult(facts="No evidence found."), state)

            # Format context text with sources
            context_parts: list[str] = []
            for search_result in results:
                source = search_result.document.metadata.get("source", "Unknown")
                content = search_result.document.content or search_result.document.metadata.get("text", "")
                context_parts.append(f"SOURCE: {source}\nCONTENT: {content}")

            context_text = "\n\n".join(context_parts)

            # Synthesize evidence using LLM
            system_prompt = (
                "Synthesize evidence into a factual report. Cite sources. If data is missing, state it."
            )
            user_prompt = f"Objective: {goal.topic_query}\n\nEvidence:\n{context_text}"

            llm_result = await self._llm_client.complete(
                [Message.system(system_prompt), Message.user(user_prompt)]
            )

            if not llm_result.success:
                return AgentResult.fail(f"LLM synthesis failed: {llm_result.error}", state)

            facts = llm_result.content if isinstance(llm_result.content, str) else str(llm_result.content)
            result = ResearcherResult(facts=facts)

            # Extract token telemetry
            token_metadata = extract_token_metadata(
                llm_result=llm_result,
                agent_name="Researcher",
            )

            return AgentResult.ok(
                result,
                state.next(status=state.status),
                metadata=token_metadata,
            )

        except Exception as e:
            logger.error(f"[Researcher] Error: {e}", exc_info=True)
            return AgentResult.fail(f"Researcher error: {str(e)}", state)


class SummarizerAgent(Agent[SummarizerGoal, SummarizerResult]):
    """
    Reduces context density by summarizing large text.

    Ideal for managing token counts before a generation step.
    """

    def __init__(self, llm_client: LLMClient):
        self._llm_client = llm_client

    @property
    def id(self) -> AgentID:
        return AgentID("Summarizer")

    @property
    def description(self) -> str:
        return "Reduces text to summary for token management."

    @property
    def skills(self) -> tuple[Any, ...]:
        return ()

    async def run(self, goal: SummarizerGoal, context: AgentContext) -> AgentResult[SummarizerResult]:
        """Execute summarization."""
        logger.info("[Summarizer] Activated. Compressing context...")
        state = AgentState()

        try:
            # Handle dict input (common with Summarizer output from other agents)
            text = goal.text_to_summarize
            if isinstance(text, dict):
                text = text.get("facts") or text.get("report") or text.get("summary") or str(text)

            system_prompt = "Summarize the text based on the objective."
            user_prompt = f"Objective: {goal.summary_objective}\n\nText: {text}"

            llm_result = await self._llm_client.complete(
                [Message.system(system_prompt), Message.user(user_prompt)]
            )

            if not llm_result.success:
                return AgentResult.fail(f"LLM summarization failed: {llm_result.error}", state)

            summary = llm_result.content if isinstance(llm_result.content, str) else str(llm_result.content)
            result = SummarizerResult(summary=summary)

            # Extract token telemetry (especially tokens_saved for Summarizer)
            token_metadata = extract_token_metadata(
                llm_result=llm_result,
                input_text=text,
                output_text=summary,
                agent_name="Summarizer",
            )

            return AgentResult.ok(
                result,
                state.next(status=state.status),
                metadata=token_metadata,
            )

        except Exception as e:
            logger.error(f"[Summarizer] Error: {e}", exc_info=True)
            return AgentResult.fail(f"Summarizer error: {str(e)}", state)


class WriterAgent(Agent[WriterGoal, WriterResult]):
    """
    Generates the final report with robust key handling.

    Applies Blueprint logic to Evidence to produce deterministic output.
    Handles various input formats and key variations for resilience.
    """

    def __init__(self, llm_client: LLMClient):
        self._llm_client = llm_client

    @property
    def id(self) -> AgentID:
        return AgentID("Writer")

    @property
    def description(self) -> str:
        return "Generates or rewrites content by applying a Blueprint to source material"

    @property
    def skills(self) -> tuple[Any, ...]:
        return ()

    def _extract_text(self, val: Any) -> str:
        """Extract text from various input formats."""
        if isinstance(val, dict):
            return val.get("blueprint_json") or val.get("summary") or val.get("facts") or str(val)
        if isinstance(val, Blueprint):
            return val.to_prompt()
        return str(val) if val else ""

    async def run(self, goal: WriterGoal, context: AgentContext) -> AgentResult[WriterResult]:
        """Execute content generation."""
        logger.info("[Writer] Activated. Synthesizing report...")
        state = AgentState()

        try:
            # Robust key resolution: handle various input formats
            blueprint_text = self._extract_text(goal.blueprint)
            facts_text = self._extract_text(goal.facts) if goal.facts else ""
            previous_text = goal.previous_content or ""

            if not blueprint_text:
                return AgentResult.fail("Writer missing blueprint input", state)

            if not (facts_text or previous_text):
                return AgentResult.fail("Writer missing facts or previous_content input", state)

            # Use blueprint prompt if it's a Blueprint object, otherwise use as-is
            if isinstance(goal.blueprint, Blueprint):
                system_prompt = goal.blueprint.to_prompt()
            else:
                system_prompt = "Apply Blueprint logic to Evidence to produce content."

            evidence = facts_text if facts_text else previous_text
            user_prompt = f"--- BLUEPRINT ---\n{blueprint_text}\n\n--- EVIDENCE ---\n{evidence}"

            llm_result = await self._llm_client.complete(
                [Message.system(system_prompt), Message.user(user_prompt)]
            )

            if not llm_result.success:
                return AgentResult.fail(f"LLM generation failed: {llm_result.error}", state)

            report = llm_result.content if isinstance(llm_result.content, str) else str(llm_result.content)
            result = WriterResult(report=report)

            # Extract token telemetry
            token_metadata = extract_token_metadata(
                llm_result=llm_result,
                agent_name="Writer",
            )

            return AgentResult.ok(
                result,
                state.next(status=state.status),
                metadata=token_metadata,
            )

        except Exception as e:
            logger.error(f"[Writer] Error: {e}", exc_info=True)
            return AgentResult.fail(f"Writer error: {str(e)}", state)

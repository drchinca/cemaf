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
import re
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from cemaf.agents.base import Agent, AgentContext, AgentResult, AgentState
from cemaf.blueprint.core import Blueprint
from cemaf.core.types import AgentID
from cemaf.llm.protocols import LLMClient, Message
from cemaf.observability.token_telemetry import extract_token_metadata
from cemaf.resilience.retry import RetryConfig, RetryPolicy
from cemaf.retrieval.protocols import SearchResult, VectorStore

logger = logging.getLogger(__name__)

# Vector-store lookups are I/O — a transient network blip should not fail
# Librarian/Researcher outright. Deterministic errors (bad filter, auth) are
# excluded from DEFAULT_TRANSIENT_EXCEPTIONS and still fail on first attempt.
_RETRIEVAL_RETRY_CONFIG = RetryConfig(max_attempts=3, initial_delay_seconds=0.5, max_delay_seconds=5.0)

# Matches a source_id the synthesis prompt asks the LLM to cite as
# `[SOURCE: <id>]`. Membership against the retrieved source_ids is the
# fabrication check — a citation.rules.CitationMembershipRule check operates
# on typed Citation objects, which free-form LLM prose is not; this is the
# same membership predicate applied to the shape this agent actually produces.
_SOURCE_TAG_RE = re.compile(r"\[SOURCE:\s*([^\]]+)\]")


def _extract_cited_source_ids(text: str) -> frozenset[str]:
    """Every `[SOURCE: <id>]` tag the LLM's synthesis actually cited."""
    return frozenset(match.strip() for match in _SOURCE_TAG_RE.findall(text))


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
    blueprint_valid: bool = Field(
        default=False, description="True iff blueprint_json parses into a real Blueprint model"
    )


class ResearcherResult(BaseModel):
    """Result from Researcher agent."""

    facts: str = Field(description="Synthesized factual report")
    source_ids: tuple[str, ...] = Field(
        default=(), description="source_ids of every retrieved chunk actually offered to the LLM"
    )
    unverifiable_claim_detected: bool = Field(
        default=False,
        description=(
            "True when the synthesized facts reference a source_id not present in "
            "source_ids — a fabricated citation. Callers SHOULD treat facts as "
            "untrusted when this is True."
        ),
    )


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
    def skills(self) -> tuple[()]:
        return ()

    async def run(self, goal: LibrarianGoal, context: AgentContext) -> AgentResult[LibrarianResult]:
        """Execute blueprint retrieval.

        Fault tolerance: vector-store lookups run under RetryPolicy (transient
        network errors get up to 3 attempts before failing the agent).
        Standard: the retrieved blueprint JSON is validated against the real
        Blueprint model — a malformed or half-written blueprint record is
        NEVER passed downstream silently; blueprint_valid=False signals the
        caller (Writer, or a human) that the default/fallback is in effect.
        """
        logger.info("[Librarian] Activated. Analyzing intent...")
        state = AgentState()

        retry_result = await RetryPolicy(_RETRIEVAL_RETRY_CONFIG).execute(
            self._vector_store.search_by_text,
            query_text=goal.intent_query,
            k=self._top_k,
            filter={"namespace": self._namespace_context} if self._namespace_context else None,
        )
        if not retry_result.success:
            logger.error(f"[Librarian] Retrieval failed after {retry_result.attempts} attempts")
            return AgentResult.fail(
                f"Librarian error: vector store unavailable after {retry_result.attempts} attempts "
                f"({retry_result.error})",
                state,
            )

        results: list[SearchResult] = retry_result.result or []

        if not results:
            logger.warning("[Librarian] No blueprint found. Returning default.")
            default_blueprint = json.dumps({"instruction": "Generate content neutrally."})
            result = LibrarianResult(blueprint_json=default_blueprint, blueprint_valid=False)
            return AgentResult.ok(result, state.next(status=state.status))

        match: SearchResult = results[0]
        logger.info(f"[Librarian] Found blueprint '{match.document.id}' (Score: {match.score:.2f})")

        blueprint_json = match.document.metadata.get("blueprint_json", "")
        if not blueprint_json:
            try:
                blueprint_data = json.loads(match.document.content)
                blueprint_json = json.dumps(blueprint_data)
            except (json.JSONDecodeError, TypeError):
                blueprint_json = json.dumps({"instruction": match.document.content})

        blueprint_valid = self._validate_blueprint(blueprint_json)
        if not blueprint_valid:
            logger.warning(
                f"[Librarian] Retrieved blueprint '{match.document.id}' failed schema validation; "
                "returning it anyway with blueprint_valid=False — callers must check this flag."
            )

        result = LibrarianResult(blueprint_json=blueprint_json, blueprint_valid=blueprint_valid)
        return AgentResult.ok(result, state.next(status=state.status))

    @staticmethod
    def _validate_blueprint(blueprint_json: str) -> bool:
        """True iff blueprint_json parses into a real Blueprint model.

        A retrieved record that is merely a free-text `{"instruction": ...}`
        fallback (this agent's own default shape) is intentionally NOT a
        valid Blueprint — callers that need a full Blueprint should treat
        blueprint_valid=False the same as "no blueprint found."
        """
        try:
            Blueprint.model_validate(json.loads(blueprint_json))
            return True
        except (json.JSONDecodeError, ValidationError, TypeError):
            return False


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
    def skills(self) -> tuple[()]:
        return ()

    async def run(self, goal: ResearcherGoal, context: AgentContext) -> AgentResult[ResearcherResult]:
        """Execute high-fidelity research.

        Fault tolerance: vector-store lookups run under RetryPolicy (transient
        network errors get up to 3 attempts before failing the agent).
        Standard: the synthesized report is checked for citation membership —
        every `[SOURCE: <id>]` tag in the LLM's output must name a source_id
        this agent actually retrieved. A citation to a source_id outside that
        set is a fabrication; unverifiable_claim_detected=True flags it rather
        than silently trusting the model's prose.
        """
        logger.info("[Researcher] Activated. Gathering evidence...")
        state = AgentState()

        retry_result = await RetryPolicy(_RETRIEVAL_RETRY_CONFIG).execute(
            self._vector_store.search_by_text,
            query_text=goal.topic_query,
            k=self._top_k,
            filter={"namespace": self._namespace_knowledge} if self._namespace_knowledge else None,
        )
        if not retry_result.success:
            logger.error(f"[Researcher] Retrieval failed after {retry_result.attempts} attempts")
            return AgentResult.fail(
                f"Researcher error: vector store unavailable after {retry_result.attempts} attempts "
                f"({retry_result.error})",
                state,
            )

        results: list[SearchResult] = retry_result.result or []

        if not results:
            logger.warning("[Researcher] No evidence found.")
            return AgentResult.ok(ResearcherResult(facts="No evidence found."), state)

        # Format context text with sources — [SOURCE: <id>] is the exact tag
        # the synthesis prompt instructs the LLM to echo back when citing.
        source_ids: list[str] = []
        context_parts: list[str] = []
        for search_result in results:
            source = str(search_result.document.metadata.get("source", "Unknown"))
            content = search_result.document.content or search_result.document.metadata.get("text", "")
            source_ids.append(source)
            context_parts.append(f"[SOURCE: {source}]\nCONTENT: {content}")

        context_text = "\n\n".join(context_parts)
        known_source_ids = frozenset(source_ids)

        # Synthesize evidence using LLM
        system_prompt = (
            "Synthesize evidence into a factual report. For every factual claim, cite its "
            "source inline using the exact tag [SOURCE: <id>] from the evidence below — never "
            "invent a source id that doesn't appear in the evidence. If data is missing, state it."
        )
        user_prompt = f"Objective: {goal.topic_query}\n\nEvidence:\n{context_text}"

        llm_result = await self._llm_client.complete(
            [Message.system(system_prompt), Message.user(user_prompt)]
        )

        if not llm_result.success:
            return AgentResult.fail(f"LLM synthesis failed: {llm_result.error}", state)

        facts = llm_result.content if isinstance(llm_result.content, str) else str(llm_result.content)

        cited_source_ids = _extract_cited_source_ids(facts)
        fabricated = cited_source_ids - known_source_ids
        if fabricated:
            logger.warning(f"[Researcher] Unverifiable citation(s) detected: {sorted(fabricated)}")

        result = ResearcherResult(
            facts=facts,
            source_ids=tuple(source_ids),
            unverifiable_claim_detected=bool(fabricated),
        )

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
    def skills(self) -> tuple[()]:
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
    def skills(self) -> tuple[()]:
        return ()

    def _extract_text(self, val: dict[str, str] | Blueprint | str | None) -> str:
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

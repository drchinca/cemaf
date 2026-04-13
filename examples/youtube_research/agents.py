"""YouTube research agents — CEMAF Agents for transcript analysis and knowledge building."""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

from cemaf.agents.base import Agent, AgentContext, AgentResult, AgentState
from cemaf.core.types import AgentID, JSON

from .tools import TranscriptChunkerTool, YouTubeTranscriptTool

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Goal / Result models
# ---------------------------------------------------------------------------


class ResearchGoal(BaseModel):
    """Research a YouTube video — extract and chunk transcript."""

    video_url: str = Field(description="YouTube URL or video ID")
    languages: list[str] = Field(default_factory=lambda: ["en"])


class ResearchResult(BaseModel):
    """Extracted transcript with chunks ready for knowledge building."""

    video_id: str = Field(default="")
    full_text: str = Field(default="")
    chunks: tuple[JSON, ...] = Field(default_factory=tuple)
    char_count: int = Field(default=0)
    chunk_count: int = Field(default=0)


class KnowledgeGoal(BaseModel):
    """Build knowledge entries from transcript chunks."""

    video_id: str = Field(description="Source video ID")
    chunks: tuple[JSON, ...] = Field(description="Transcript chunks to process")
    topic: str = Field(default="", description="Optional topic filter")


class KnowledgeResult(BaseModel):
    """Knowledge entries extracted from transcript."""

    entries: tuple[JSON, ...] = Field(default_factory=tuple)
    summary: str = Field(default="")


# ---------------------------------------------------------------------------
# ResearcherAgent
# ---------------------------------------------------------------------------


class TranscriptResearcherAgent(Agent[ResearchGoal, ResearchResult]):
    """Fetches YouTube transcript and chunks it for knowledge extraction."""

    def __init__(self) -> None:
        self._transcript_tool = YouTubeTranscriptTool()
        self._chunker_tool = TranscriptChunkerTool()

    @property
    def id(self) -> AgentID:
        return AgentID("YouTubeResearcher")

    @property
    def description(self) -> str:
        return "Fetches YouTube transcripts and prepares them for knowledge extraction"

    @property
    def skills(self) -> tuple[()]:
        return ()

    async def run(
        self,
        goal: ResearchGoal,
        context: AgentContext,
    ) -> AgentResult[ResearchResult]:
        state = AgentState()

        try:
            # Step 1: Fetch transcript
            logger.info("[YouTubeResearcher] Fetching transcript for %s", goal.video_url)
            transcript_result = await self._transcript_tool.execute(
                video_url=goal.video_url,
                languages=goal.languages,
            )

            if not transcript_result.success:
                return AgentResult.fail(
                    error=f"Transcript fetch failed: {transcript_result.error}",
                    state=state,
                )

            data = transcript_result.data or {}
            full_text = data.get("full_text", "")
            video_id = data.get("video_id", "")

            if not full_text:
                return AgentResult.fail(error="Empty transcript", state=state)

            # Step 2: Chunk the transcript
            chunk_result = await self._chunker_tool.execute(
                text=full_text,
                chunk_size=2000,
                overlap=200,
            )

            if not chunk_result.success:
                return AgentResult.fail(
                    error=f"Chunking failed: {chunk_result.error}",
                    state=state,
                )

            chunk_data = chunk_result.data or {}
            chunks = chunk_data.get("chunks", [])

            logger.info(
                "[YouTubeResearcher] Got %d chars, %d chunks for %s",
                len(full_text),
                len(chunks),
                video_id,
            )

            result = ResearchResult(
                video_id=video_id,
                full_text=full_text,
                chunks=tuple(chunks),
                char_count=len(full_text),
                chunk_count=len(chunks),
            )
            return AgentResult.ok(output=result, state=state)

        except Exception as exc:
            logger.error("[YouTubeResearcher] Error: %s", exc, exc_info=True)
            return AgentResult.fail(error=str(exc), state=state)


# ---------------------------------------------------------------------------
# KnowledgeBuilderAgent
# ---------------------------------------------------------------------------


class KnowledgeBuilderAgent(Agent[KnowledgeGoal, KnowledgeResult]):
    """Processes transcript chunks into structured knowledge entries."""

    @property
    def id(self) -> AgentID:
        return AgentID("KnowledgeBuilder")

    @property
    def description(self) -> str:
        return "Extracts structured knowledge entries from transcript chunks"

    @property
    def skills(self) -> tuple[()]:
        return ()

    async def run(
        self,
        goal: KnowledgeGoal,
        context: AgentContext,
    ) -> AgentResult[KnowledgeResult]:
        state = AgentState()

        try:
            entries: list[JSON] = []

            for chunk in goal.chunks:
                text = chunk.get("text", "") if isinstance(chunk, dict) else str(chunk)
                if not text:
                    continue

                # Extract key sentences (simple heuristic: sentences with key terms)
                sentences = [s.strip() for s in text.split(".") if len(s.strip()) > 30]

                entry: JSON = {
                    "video_id": goal.video_id,
                    "chunk_index": chunk.get("index", 0) if isinstance(chunk, dict) else 0,
                    "key_sentences": sentences[:5],
                    "char_count": len(text),
                    "topic": goal.topic,
                }
                entries.append(entry)

            summary = (
                f"Extracted {len(entries)} knowledge entries from "
                f"{len(goal.chunks)} chunks (video: {goal.video_id})"
            )

            logger.info("[KnowledgeBuilder] %s", summary)

            result = KnowledgeResult(
                entries=tuple(entries),
                summary=summary,
            )
            return AgentResult.ok(output=result, state=state)

        except Exception as exc:
            logger.error("[KnowledgeBuilder] Error: %s", exc, exc_info=True)
            return AgentResult.fail(error=str(exc), state=state)

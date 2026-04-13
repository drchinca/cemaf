"""
YouTube Research App — Powered by CEMAF

Downloads YouTube transcripts, chunks them, and builds a searchable
knowledge base using CEMAF's agent/DAG/memory primitives.

Usage:
    uv run python -m examples.youtube_research.app <youtube_url> [youtube_url2 ...]

Example:
    uv run python -m examples.youtube_research.app https://www.youtube.com/watch?v=UL67mxvZJXA
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from cemaf import AgentRegistry, DAG, Edge, Node, create_executor
from cemaf.orchestration.services import RuntimeServices

from .agents import (
    KnowledgeBuilderAgent,
    KnowledgeGoal,
    ResearchGoal,
    TranscriptResearcherAgent,
)
from .tools import TranscriptChunkerTool, YouTubeTranscriptTool


def build_research_dag(*, video_count: int = 1) -> DAG:
    """Build a DAG: fetch transcript → chunk → extract knowledge."""
    dag = DAG(name="youtube_research", description="YouTube transcript to knowledge")

    dag = dag.add_node(
        node=Node.agent(
            id="research",
            name="Transcript Researcher",
            agent_id="YouTubeResearcher",
            output_key="transcript",
        ).with_checkpoint(enabled=True)
    )

    dag = dag.add_node(
        node=Node.agent(
            id="knowledge",
            name="Knowledge Builder",
            agent_id="KnowledgeBuilder",
            output_key="knowledge",
        ).with_checkpoint(enabled=True)
    )

    dag = dag.add_edge(edge=Edge(source="research", target="knowledge"))
    return dag


async def research_video(*, video_url: str, output_dir: Path) -> dict[str, object]:
    """Run the full research pipeline for a single video."""
    # Register agents
    registry = AgentRegistry()
    registry.register_agent(
        agent_instance=TranscriptResearcherAgent(),
        goal_type=ResearchGoal,
    )
    registry.register_agent(
        agent_instance=KnowledgeBuilderAgent(),
        goal_type=KnowledgeGoal,
    )

    # Build and run DAG
    dag = build_research_dag()
    executor = create_executor(agent_registry=registry)
    result = await executor.run(dag=dag)

    # Extract results from context
    transcript_data = result.final_context.data.get("transcript", {})
    knowledge_data = result.final_context.data.get("knowledge", {})

    # Also run the tools directly for now (DAG doesn't pass input_mapping to agent goals yet)
    researcher = TranscriptResearcherAgent()
    research_result = await researcher.run(
        goal=ResearchGoal(video_url=video_url),
        context=type("Ctx", (), {"run_id": "direct", "agent_id": "YouTubeResearcher"})(),  # type: ignore[arg-type]
    )

    if not research_result.success:
        print(f"FAILED: {research_result.error}")
        return {"error": research_result.error}

    research_output = research_result.output

    # Build knowledge
    builder = KnowledgeBuilderAgent()
    knowledge_result = await builder.run(
        goal=KnowledgeGoal(
            video_id=research_output.video_id,
            chunks=research_output.chunks,
        ),
        context=type("Ctx", (), {"run_id": "direct", "agent_id": "KnowledgeBuilder"})(),  # type: ignore[arg-type]
    )

    if not knowledge_result.success:
        print(f"Knowledge extraction failed: {knowledge_result.error}")
        return {"error": knowledge_result.error}

    # Save to knowledge base
    output_dir.mkdir(parents=True, exist_ok=True)

    transcript_path = output_dir / f"{research_output.video_id}_transcript.txt"
    transcript_path.write_text(research_output.full_text, encoding="utf-8")

    knowledge_path = output_dir / f"{research_output.video_id}_knowledge.json"
    knowledge_path.write_text(
        json.dumps(
            {
                "video_id": research_output.video_id,
                "chunk_count": research_output.chunk_count,
                "char_count": research_output.char_count,
                "entries": [e for e in knowledge_result.output.entries],
                "summary": knowledge_result.output.summary,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"Transcript: {transcript_path} ({research_output.char_count} chars)")
    print(f"Knowledge:  {knowledge_path} ({len(knowledge_result.output.entries)} entries)")
    print(f"Summary:    {knowledge_result.output.summary}")

    return {
        "video_id": research_output.video_id,
        "transcript_path": str(transcript_path),
        "knowledge_path": str(knowledge_path),
        "char_count": research_output.char_count,
        "chunk_count": research_output.chunk_count,
        "entry_count": len(knowledge_result.output.entries),
    }


async def main() -> None:
    """CLI entry point."""
    if len(sys.argv) < 2:
        print("Usage: python -m examples.youtube_research.app <youtube_url> [...]")
        sys.exit(1)

    output_dir = Path("knowledge_base")
    urls = sys.argv[1:]

    print(f"Researching {len(urls)} video(s)...\n")

    for url in urls:
        print(f"--- {url} ---")
        result = await research_video(video_url=url, output_dir=output_dir)
        print(f"Result: {json.dumps(result, indent=2)}\n")

    print(f"Knowledge base saved to: {output_dir.absolute()}")


if __name__ == "__main__":
    asyncio.run(main())

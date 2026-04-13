"""YouTube research tools — CEMAF Tools for transcript extraction and analysis."""

from __future__ import annotations

import re
from typing import Any

from cemaf.core.enums import ToolRiskLevel
from cemaf.core.result import Result
from cemaf.core.types import ToolID
from cemaf.tools.base import Tool, ToolResult, ToolSchema


class YouTubeTranscriptTool(Tool):
    """Fetch transcript from a YouTube video URL or ID."""

    @property
    def id(self) -> ToolID:
        return ToolID("youtube_transcript")

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="youtube_transcript",
            description="Fetch the transcript/captions from a YouTube video.",
            parameters={
                "type": "object",
                "properties": {
                    "video_url": {
                        "type": "string",
                        "description": "YouTube URL or video ID",
                    },
                    "languages": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Preferred languages (default: ['en'])",
                    },
                },
            },
            required=("video_url",),
            is_read_only=True,
            is_concurrent_safe=True,
            risk_level=ToolRiskLevel.LOW,
        )

    @property
    def is_read_only(self) -> bool:
        return True

    @property
    def is_concurrent_safe(self) -> bool:
        return True

    @property
    def risk_level(self) -> ToolRiskLevel:
        return ToolRiskLevel.LOW

    async def execute(self, **kwargs: Any) -> ToolResult:
        video_url: str = kwargs.get("video_url", "")
        languages: list[str] = kwargs.get("languages", ["en"])

        video_id = _extract_video_id(url=video_url)
        if not video_id:
            return Result.fail(error=f"Could not extract video ID from: {video_url}")

        try:
            from youtube_transcript_api import YouTubeTranscriptApi

            api = YouTubeTranscriptApi()
            fetched = api.fetch(video_id=video_id, languages=languages)

            segments = [
                {
                    "text": snippet.text,
                    "start": snippet.start,
                    "duration": snippet.duration,
                }
                for snippet in fetched
            ]

            full_text = " ".join(seg["text"] for seg in segments)

            return Result.ok(
                data={
                    "video_id": video_id,
                    "language": languages[0] if languages else "en",
                    "segment_count": len(segments),
                    "full_text": full_text,
                    "segments": segments[:10],  # First 10 for preview
                    "char_count": len(full_text),
                },
                metadata={"source": "youtube_transcript_api"},
            )

        except Exception as e:
            return Result.fail(
                error=f"Transcript fetch failed for {video_id}: {e}",
                metadata={"video_id": video_id},
            )


class TranscriptChunkerTool(Tool):
    """Split a transcript into chunks for knowledge extraction."""

    @property
    def id(self) -> ToolID:
        return ToolID("transcript_chunker")

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="transcript_chunker",
            description="Split transcript text into semantic chunks for processing.",
            parameters={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Full transcript text"},
                    "chunk_size": {
                        "type": "integer",
                        "description": "Target chars per chunk (default: 2000)",
                    },
                    "overlap": {
                        "type": "integer",
                        "description": "Overlap chars between chunks (default: 200)",
                    },
                },
            },
            required=("text",),
            is_read_only=True,
            is_concurrent_safe=True,
            risk_level=ToolRiskLevel.LOW,
        )

    @property
    def is_read_only(self) -> bool:
        return True

    @property
    def is_concurrent_safe(self) -> bool:
        return True

    @property
    def risk_level(self) -> ToolRiskLevel:
        return ToolRiskLevel.LOW

    async def execute(self, **kwargs: Any) -> ToolResult:
        text: str = kwargs.get("text", "")
        chunk_size: int = kwargs.get("chunk_size", 2000)
        overlap: int = kwargs.get("overlap", 200)

        if not text:
            return Result.fail(error="No text provided")

        chunks: list[dict[str, Any]] = []
        start = 0
        idx = 0

        while start < len(text):
            end = min(start + chunk_size, len(text))

            # Try to break at sentence boundary
            if end < len(text):
                last_period = text.rfind(".", start, end)
                if last_period > start + chunk_size // 2:
                    end = last_period + 1

            chunk_text = text[start:end].strip()
            if chunk_text:
                chunks.append(
                    {
                        "index": idx,
                        "text": chunk_text,
                        "char_start": start,
                        "char_end": end,
                    }
                )
                idx += 1

            start = end - overlap if end < len(text) else len(text)

        return Result.ok(
            data={
                "chunk_count": len(chunks),
                "chunks": chunks,
                "total_chars": len(text),
            }
        )


def _extract_video_id(*, url: str) -> str | None:
    """Extract YouTube video ID from various URL formats."""
    if not url:
        return None

    # Already a plain ID (11 chars)
    if re.match(r"^[a-zA-Z0-9_-]{11}$", url):
        return url

    patterns = [
        r"(?:youtube\.com/watch\?v=)([a-zA-Z0-9_-]{11})",
        r"(?:youtu\.be/)([a-zA-Z0-9_-]{11})",
        r"(?:youtube\.com/embed/)([a-zA-Z0-9_-]{11})",
        r"(?:youtube\.com/v/)([a-zA-Z0-9_-]{11})",
    ]

    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)

    return None

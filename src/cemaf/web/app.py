"""FastAPI application — serves the architecture advisor UI and SSE API."""

import json
import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from cemaf.llm.anthropic import AnthropicLLMClient
from cemaf.web.architect import ArchitectAgent

_STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(
    title="CEMAF Architecture Advisor",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


def _get_llm_client() -> AnthropicLLMClient:
    """Build an Anthropic LLM client from env vars."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY not set")
    model = os.environ.get("CEMAF_ARCHITECT_MODEL", "claude-sonnet-4-20250514")
    return AnthropicLLMClient(api_key=api_key, model=model)


class ArchitectRequest(BaseModel):
    """Incoming request body for /api/architect."""

    prompt: str


@app.get("/")  # type: ignore[misc]
async def index() -> FileResponse:
    """Serve the main HTML page."""
    return FileResponse(path=str(_STATIC_DIR / "index.html"))


@app.get("/api/health")  # type: ignore[misc]
async def health() -> dict[str, str]:
    """Liveness check."""
    return {"status": "ok"}


async def _stream_events(*, agent: ArchitectAgent, prompt: str) -> AsyncIterator[dict[str, Any]]:
    """Yield SSE data dicts from the architect agent stream."""
    try:
        async for chunk in agent.stream_architecture(prompt=prompt):
            yield {"data": json.dumps({"content": chunk})}
        yield {"data": json.dumps({"done": True})}
    except Exception as exc:
        yield {"data": json.dumps({"error": str(exc)})}


@app.post("/api/architect")  # type: ignore[misc]
async def architect(request: ArchitectRequest) -> EventSourceResponse:
    """Stream an architecture plan as Server-Sent Events."""
    llm_client = _get_llm_client()
    agent = ArchitectAgent(llm_client=llm_client)
    return EventSourceResponse(content=_stream_events(agent=agent, prompt=request.prompt))

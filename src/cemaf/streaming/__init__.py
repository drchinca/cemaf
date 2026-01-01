"""
Streaming module - Async streaming support for LLM outputs.

Provides:
- StreamBuffer for accumulating chunks
- StreamHandler protocol for UI callbacks
- SSE (Server-Sent Events) formatting
"""

from cemaf.streaming.protocols import (
    EventType,
    StreamBuffer,
    StreamEvent,
    StreamHandler,
)
from cemaf.streaming.sse import SSEFormatter

__all__ = [
    "StreamHandler",
    "StreamBuffer",
    "StreamEvent",
    "EventType",
    "SSEFormatter",
]

"""
Streaming protocols - Interfaces for streaming output handling.

Supports:
- Chunk accumulation
- Progress callbacks
- Cancellation
- Event typing
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from cemaf.core.types import JSON
from cemaf.core.utils import utc_now


class EventType(str, Enum):
    """Type of streaming event."""

    CONTENT = "content"  # Text content chunk
    TOOL_CALL_START = "tool_call_start"  # Starting a tool call
    TOOL_CALL_ARGS = "tool_call_args"  # Tool call arguments (streaming)
    TOOL_CALL_END = "tool_call_end"  # Tool call complete
    THINKING = "thinking"  # Model thinking/reasoning
    ERROR = "error"  # Error occurred
    DONE = "done"  # Stream complete


@dataclass(frozen=True)
class StreamEvent:
    """
    A single event in a stream.

    Used for typed event handling.
    """

    type: EventType
    data: Any = None
    timestamp: datetime = field(default_factory=utc_now)
    metadata: JSON = field(default_factory=dict)

    @classmethod
    def content(cls, text: str) -> StreamEvent:
        """Create a content event."""
        return cls(type=EventType.CONTENT, data=text)

    @classmethod
    def tool_start(cls, tool_name: str, call_id: str) -> StreamEvent:
        """Create a tool call start event."""
        return cls(
            type=EventType.TOOL_CALL_START,
            data={"name": tool_name, "id": call_id},
        )

    @classmethod
    def tool_end(cls, call_id: str, result: Any) -> StreamEvent:
        """Create a tool call end event."""
        return cls(
            type=EventType.TOOL_CALL_END,
            data={"id": call_id, "result": result},
        )

    @classmethod
    def error(cls, message: str) -> StreamEvent:
        """Create an error event."""
        return cls(type=EventType.ERROR, data=message)

    @classmethod
    def done(cls, final_content: str = "") -> StreamEvent:
        """Create a done event."""
        return cls(type=EventType.DONE, data=final_content)


@runtime_checkable
class StreamHandler(Protocol):
    """
    Protocol for handling stream events.

    Implement for different output targets:
    - Console (print as received)
    - WebSocket (send to client)
    - File (write to disk)
    - Buffer (accumulate in memory)
    """

    async def on_event(self, event: StreamEvent) -> None:
        """Handle a streaming event."""
        ...

    async def on_content(self, content: str) -> None:
        """Handle content chunk (convenience method)."""
        ...

    async def on_error(self, error: str) -> None:
        """Handle error."""
        ...

    async def on_done(self) -> None:
        """Handle stream completion."""
        ...


class StreamBuffer:
    """
    Buffer that accumulates streaming content.

    Tracks:
    - Accumulated text content
    - All events
    - Tool calls
    - Timing

    Usage:
        buffer = StreamBuffer()
        async for chunk in llm.stream(messages):
            await buffer.add_chunk(chunk)
        print(buffer.content)
    """

    def __init__(self) -> None:
        self._content_parts: list[str] = []
        self._events: list[StreamEvent] = []
        self._tool_calls: list[JSON] = []
        self._started_at: datetime | None = None
        self._completed_at: datetime | None = None
        self._is_complete = False
        self._error: str | None = None

    @property
    def content(self) -> str:
        """Get accumulated content."""
        return "".join(self._content_parts)

    @property
    def events(self) -> tuple[StreamEvent, ...]:
        """Get all events."""
        return tuple(self._events)

    @property
    def tool_calls(self) -> tuple[JSON, ...]:
        """Get all tool calls."""
        return tuple(self._tool_calls)

    @property
    def is_complete(self) -> bool:
        """Whether stream is complete."""
        return self._is_complete

    @property
    def error(self) -> str | None:
        """Error if any."""
        return self._error

    @property
    def duration_ms(self) -> float:
        """Duration in milliseconds."""
        if not self._started_at:
            return 0.0
        end = self._completed_at or utc_now()
        return (end - self._started_at).total_seconds() * 1000

    async def add_event(self, event: StreamEvent) -> None:
        """Add an event to the buffer."""
        if self._started_at is None:
            self._started_at = utc_now()

        self._events.append(event)

        if event.type == EventType.CONTENT:
            self._content_parts.append(str(event.data))
        elif event.type == EventType.TOOL_CALL_END:
            self._tool_calls.append(event.data)
        elif event.type == EventType.ERROR:
            self._error = str(event.data)
        elif event.type == EventType.DONE:
            self._is_complete = True
            self._completed_at = utc_now()

    async def add_content(self, content: str) -> None:
        """Add content chunk."""
        await self.add_event(StreamEvent.content(content))

    def clear(self) -> None:
        """Clear the buffer."""
        self._content_parts.clear()
        self._events.clear()
        self._tool_calls.clear()
        self._started_at = None
        self._completed_at = None
        self._is_complete = False
        self._error = None


class CallbackStreamHandler:
    """
    Stream handler that calls user-provided callbacks.

    Usage:
        handler = CallbackStreamHandler(
            on_content=lambda c: print(c, end=""),
            on_done=lambda: print("\\nDone!")
        )
    """

    def __init__(
        self,
        on_content: Callable[[str], None] | None = None,
        on_error: Callable[[str], None] | None = None,
        on_done: Callable[[], None] | None = None,
        on_event: Callable[[StreamEvent], None] | None = None,
    ) -> None:
        self._on_content = on_content
        self._on_error = on_error
        self._on_done = on_done
        self._on_event = on_event

    async def on_event(self, event: StreamEvent) -> None:
        """Handle a streaming event."""
        if self._on_event:
            self._on_event(event)

    async def on_content(self, content: str) -> None:
        """Handle content chunk."""
        if self._on_content:
            self._on_content(content)

    async def on_error(self, error: str) -> None:
        """Handle error."""
        if self._on_error:
            self._on_error(error)

    async def on_done(self) -> None:
        """Handle stream completion."""
        if self._on_done:
            self._on_done()

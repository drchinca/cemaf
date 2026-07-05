"""
SSE (Server-Sent Events) formatting.

Converts stream events to SSE format for HTTP streaming.
"""

import json
from collections.abc import AsyncIterator

from cemaf.streaming.protocols import EventType, StreamEvent


class SSEFormatter:
    """
    Formats stream events as Server-Sent Events.

    SSE Format:
        event: <type>
        data: <json>

    Usage:
        formatter = SSEFormatter()
        async for sse_line in formatter.format_stream(events):
            yield sse_line
    """

    def __init__(
        self,
        include_event_type: bool = True,
        buffer_size: int = 1000,
        chunk_timeout_seconds: float = 30.0,
    ) -> None:
        self._include_event_type = include_event_type
        self._buffer_size = buffer_size
        self._chunk_timeout_seconds = chunk_timeout_seconds

    @property
    def include_event_type(self) -> bool:
        """Whether formatted SSE events include the event type line."""
        return self._include_event_type

    @property
    def buffer_size(self) -> int:
        """Configured stream buffer size."""
        return self._buffer_size

    @property
    def chunk_timeout_seconds(self) -> float:
        """Configured chunk delivery timeout."""
        return self._chunk_timeout_seconds

    def format_event(self, event: StreamEvent) -> str:
        """
        Format a single event as SSE.

        Returns the SSE-formatted string with trailing newlines.
        """
        lines: list[str] = []

        if self._include_event_type:
            lines.append(f"event: {event.type.value}")

        # Serialize data
        data = json.dumps({"content": event.data}) if isinstance(event.data, str) else json.dumps(event.data)

        lines.append(f"data: {data}")
        lines.append("")  # Empty line to end event

        return "\n".join(lines) + "\n"

    async def format_stream(
        self,
        events: AsyncIterator[StreamEvent],
    ) -> AsyncIterator[str]:
        """
        Format a stream of events as SSE.

        Yields SSE-formatted strings.
        """
        async for event in events:
            yield self.format_event(event)

    @staticmethod
    def parse_sse(sse_text: str, *, strict: bool = False) -> list[StreamEvent]:
        """
        Parse SSE text back into events.

        Useful for testing and client-side parsing.
        Set ``strict=True`` to raise ``ValueError`` on malformed event frames.
        """
        events: list[StreamEvent] = []
        current_event_type: str | None = None
        current_data: str | None = None

        for line in sse_text.split("\n"):
            line = line.strip()

            if line.startswith("event:"):
                current_event_type = line[6:].strip()
            elif line.startswith("data:"):
                current_data = line[5:].strip()
            elif line == "" and current_data:
                # End of event
                try:
                    data = json.loads(current_data)
                    event_type = EventType(current_event_type) if current_event_type else EventType.CONTENT

                    # Extract content if wrapped
                    if isinstance(data, dict) and "content" in data:
                        data = data["content"]

                    events.append(StreamEvent(type=event_type, data=data))
                except (json.JSONDecodeError, ValueError) as exc:
                    if strict:
                        raise ValueError(f"Invalid SSE event frame: {current_data}") from exc

                current_event_type = None
                current_data = None

        return events

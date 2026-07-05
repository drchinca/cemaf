"""
Tests for streaming module.
"""

import pytest

from cemaf.config.protocols import Settings, StreamingSettings
from cemaf.streaming.factories import (
    create_sse_stream_processor,
    create_sse_stream_processor_from_config,
)
from cemaf.streaming.protocols import (
    CallbackStreamHandler,
    EventType,
    StreamBuffer,
    StreamEvent,
)
from cemaf.streaming.sse import SSEFormatter


class TestStreamEvent:
    """Tests for StreamEvent."""

    def test_content_event(self):
        """Create content event."""
        event = StreamEvent.content("Hello")

        assert event.type == EventType.CONTENT
        assert event.data == "Hello"

    def test_tool_start_event(self):
        """Create tool start event."""
        event = StreamEvent.tool_start("search", "call_123")

        assert event.type == EventType.TOOL_CALL_START
        assert event.data["name"] == "search"

    def test_done_event(self):
        """Create done event."""
        event = StreamEvent.done("Final content")

        assert event.type == EventType.DONE
        assert event.data == "Final content"

    def test_error_event(self):
        """Create error event."""
        event = StreamEvent.error("Something went wrong")

        assert event.type == EventType.ERROR
        assert event.data == "Something went wrong"


class TestStreamBuffer:
    """Tests for StreamBuffer."""

    @pytest.mark.asyncio
    async def test_accumulate_content(self):
        """Buffer accumulates content."""
        buffer = StreamBuffer()

        await buffer.add_content("Hello ")
        await buffer.add_content("world!")

        assert buffer.content == "Hello world!"

    @pytest.mark.asyncio
    async def test_tracks_events(self):
        """Buffer tracks all events."""
        buffer = StreamBuffer()

        await buffer.add_event(StreamEvent.content("Hi"))
        await buffer.add_event(StreamEvent.done())

        assert len(buffer.events) == 2

    @pytest.mark.asyncio
    async def test_is_complete(self):
        """Buffer knows when stream is complete."""
        buffer = StreamBuffer()

        assert not buffer.is_complete

        await buffer.add_event(StreamEvent.done())

        assert buffer.is_complete

    @pytest.mark.asyncio
    async def test_tracks_errors(self):
        """Buffer tracks errors."""
        buffer = StreamBuffer()

        await buffer.add_event(StreamEvent.error("Failed!"))

        assert buffer.error == "Failed!"

    @pytest.mark.asyncio
    async def test_duration(self):
        """Buffer tracks duration."""
        buffer = StreamBuffer()

        await buffer.add_content("Start")
        import asyncio

        await asyncio.sleep(0.01)
        await buffer.add_event(StreamEvent.done())

        assert buffer.duration_ms >= 10

    def test_clear(self):
        """Clear resets buffer."""
        buffer = StreamBuffer()
        buffer._content_parts.append("test")
        buffer._is_complete = True

        buffer.clear()

        assert buffer.content == ""
        assert not buffer.is_complete


class TestCallbackStreamHandler:
    """Tests for CallbackStreamHandler."""

    @pytest.mark.asyncio
    async def test_content_callback(self):
        """Content callback is called."""
        received = []
        handler = CallbackStreamHandler(on_content=lambda c: received.append(c))

        await handler.on_content("Hello")

        assert received == ["Hello"]

    @pytest.mark.asyncio
    async def test_done_callback(self):
        """Done callback is called."""
        done_called = []
        handler = CallbackStreamHandler(on_done=lambda: done_called.append(True))

        await handler.on_done()

        assert done_called == [True]


class TestSSEFormatter:
    """Tests for SSEFormatter."""

    def test_format_content_event(self):
        """Format content event as SSE."""
        formatter = SSEFormatter()
        event = StreamEvent.content("Hello")

        sse = formatter.format_event(event)

        assert "event: content" in sse
        assert "data:" in sse
        assert "Hello" in sse

    def test_format_without_event_type(self):
        """Format without event type line."""
        formatter = SSEFormatter(include_event_type=False)
        event = StreamEvent.content("Test")

        sse = formatter.format_event(event)

        assert "event:" not in sse
        assert "data:" in sse

    def test_parse_sse(self):
        """Parse SSE back to events."""
        formatter = SSEFormatter()
        original = StreamEvent.content("Test content")

        sse = formatter.format_event(original)
        parsed = SSEFormatter.parse_sse(sse)

        assert len(parsed) == 1
        assert parsed[0].type == EventType.CONTENT
        assert parsed[0].data == "Test content"

    def test_parse_sse_lenient_mode_skips_invalid_frames(self):
        """Lenient parsing preserves historical behavior for malformed frames."""
        parsed = SSEFormatter.parse_sse("event: content\ndata: NOT JSON\n\n")

        assert parsed == []

    def test_parse_sse_strict_mode_rejects_invalid_frames(self):
        """Strict parsing gives callers a fail-loud option for malformed frames."""
        with pytest.raises(ValueError, match="Invalid SSE event frame"):
            SSEFormatter.parse_sse("event: content\ndata: NOT JSON\n\n", strict=True)

    def test_factory_preserves_streaming_configuration(self):
        formatter = create_sse_stream_processor(buffer_size=250, chunk_timeout_seconds=4.5)

        assert formatter.include_event_type is True
        assert formatter.buffer_size == 250
        assert formatter.chunk_timeout_seconds == 4.5

    def test_factory_from_config_uses_settings(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("CEMAF_STREAMING_BUFFER_SIZE", raising=False)
        monkeypatch.delenv("CEMAF_STREAMING_CHUNK_TIMEOUT_SECONDS", raising=False)
        settings = Settings(
            streaming=StreamingSettings(
                buffer_size=333,
                chunk_timeout_seconds=6.25,
            )
        )

        formatter = create_sse_stream_processor_from_config(settings=settings)

        assert formatter.buffer_size == 333
        assert formatter.chunk_timeout_seconds == 6.25

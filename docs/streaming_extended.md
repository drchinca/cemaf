# Streaming Module - Extended Documentation

## Overview

The streaming module provides async streaming support for LLM outputs, enabling real-time token-by-token processing, buffering, and UI callbacks for responsive applications.

**What it does**: Provides StreamBuffer for accumulating streamed tokens, StreamHandler protocol for UI callbacks on new tokens, and SSEFormatter for Server-Sent Events formatting. Enables real-time display of LLM generation in web applications without waiting for completion.

**Key use cases**:
- Display LLM output in real-time as it generates (chat interfaces)
- Process tokens as they arrive for early stopping or filtering
- Send streaming output to web clients via SSE/WebSocket
- Aggregate streamed tokens into final output
- Monitor streaming for cost/token count
- Implement progressive generation displays

**When to use vs. alternatives**: Use streaming when you need to show output to users in real-time. Use it for interactive applications where latency matters. Don't use for batch processing (wait for completion) or when you need full output before processing (use regular non-streaming).

## Core Concepts

### Stream Events

Streaming generates a sequence of events:

**TokenGenerated**: A new token was generated. Contains token text and metadata.

**StreamStarted**: Generation started. Contains model info, parameters.

**StreamCompleted**: Generation finished. Contains final stats.

**StreamError**: Generation failed. Contains error details.

**MetadataUpdated**: Stream metadata changed (finish reason, stop details).

### StreamBuffer

Accumulates streamed tokens into final output:

```
Token 1 → Buffer
Token 2 → Buffer
Token 3 → Buffer
...
Token N → Buffer
→ Final output = all tokens combined
```

Provides:
- Accumulated text
- Token count
- Partial outputs (for progressive display)

### Handlers

StreamHandler callbacks receive stream events. Handlers can:
- Display tokens in UI
- Process tokens for content filtering
- Collect statistics
- Redirect to files or queues

## Usage Examples

### Basic Token Streaming

```python
from cemaf.streaming import StreamBuffer, StreamHandler

# Create buffer to accumulate tokens
buffer = StreamBuffer(max_size=10000)

# Define handler for tokens
class PrintHandler(StreamHandler):
    async def on_token(self, token: str):
        print(token, end="", flush=True)  # Print immediately

    async def on_complete(self, final_text: str):
        print(f"\n\nGeneration complete. Total: {len(final_text)} chars")

# Stream from LLM
handler = PrintHandler()
llm_stream = await llm.generate_stream(
    prompt="Write a story",
    on_token=handler.on_token,
    buffer=buffer
)

# Access final output from buffer
print(f"\nFinal output:\n{buffer.text}")
print(f"Tokens: {buffer.token_count}")
```

### Streaming to Web Clients (SSE)

```python
from cemaf.streaming import SSEFormatter
from fastapi import FastAPI
from fastapi.responses import StreamingResponse

app = FastAPI()

@app.get("/generate-stream")
async def generate_stream(prompt: str):
    """Stream LLM output to client via SSE."""

    async def event_generator():
        buffer = StreamBuffer()
        formatter = SSEFormatter()

        async def send_token(token: str):
            buffer.append(token)
            # Format as SSE event
            event = formatter.format_token(token, buffer.token_count)
            yield event

        # Stream from LLM
        final_text = ""
        async for token in llm.generate_stream(prompt):
            yield await send_token(token)
            final_text += token

        # Send completion event
        completion = formatter.format_complete(final_text, buffer.token_count)
        yield completion

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream"
    )

# Client receives:
# data: {"token": "The", "position": 0}
# data: {"token": " cat", "position": 1}
# data: {"complete": true, "text": "The cat...", "tokens": 42}
```

### Progressive Display with Chunking

```python
from cemaf.streaming import StreamBuffer

class ProgressiveDisplay(StreamHandler):
    def __init__(self, chunk_size: int = 50):
        self.chunk_size = chunk_size
        self.buffer = ""

    async def on_token(self, token: str):
        self.buffer += token

        # Display when we have a full chunk
        if len(self.buffer) >= self.chunk_size:
            print(self.buffer, end="", flush=True)
            self.buffer = ""

    async def on_complete(self, final_text: str):
        # Display remaining
        if self.buffer:
            print(self.buffer, end="", flush=True)
        print("\n[Complete]")

# Use handler
handler = ProgressiveDisplay(chunk_size=100)
async for token in llm.generate_stream(prompt, handler=handler):
    pass
```

### Processing Streamed Tokens

```python
from cemaf.streaming import StreamHandler

class FilteringHandler(StreamHandler):
    """Filter and modify tokens as they stream."""

    def __init__(self):
        self.output = []
        self.context_length = 0

    async def on_token(self, token: str):
        # Filter out unwanted tokens
        if self._is_acceptable(token):
            self.output.append(token)
            self.context_length += len(token)

        # Stop if getting too long
        if self.context_length > 1000:
            raise StreamStoppedException("Token limit reached")

    def _is_acceptable(self, token: str) -> bool:
        # Remove tokens that appear in blocklist
        blocklist = ["[STOP]", "[END]"]
        return not any(block in token for block in blocklist)

class StreamStoppedException(Exception):
    pass

# Use in streaming
handler = FilteringHandler()
try:
    async for token in llm.generate_stream(prompt, handler=handler):
        pass
except StreamStoppedException:
    print(f"Stopped early. Output: {''.join(handler.output)}")
```

### Streaming with Metrics

```python
from cemaf.streaming import StreamHandler
import time

class MetricsHandler(StreamHandler):
    def __init__(self):
        self.token_count = 0
        self.start_time = time.time()
        self.tokens_per_second = 0
        self.output = []

    async def on_token(self, token: str):
        self.output.append(token)
        self.token_count += 1

        # Calculate tokens/sec every 10 tokens
        if self.token_count % 10 == 0:
            elapsed = time.time() - self.start_time
            self.tokens_per_second = self.token_count / elapsed
            print(f"[{self.tokens_per_second:.1f} tokens/sec]", end=" ")

    async def on_complete(self, final_text: str):
        elapsed = time.time() - self.start_time
        print(f"\nGenerated {self.token_count} tokens in {elapsed:.1f}s")
        print(f"Average: {self.token_count / elapsed:.1f} tokens/sec")
```

### Streaming with Buffering

```python
from cemaf.streaming import StreamBuffer

class BatchedStreamHandler(StreamHandler):
    """Buffer tokens and process in batches."""

    def __init__(self, batch_size: int = 10):
        self.buffer = StreamBuffer()
        self.batch_size = batch_size
        self.batch = []

    async def on_token(self, token: str):
        self.buffer.append(token)
        self.batch.append(token)

        # Process when batch is full
        if len(self.batch) >= self.batch_size:
            batch_text = "".join(self.batch)
            await self._process_batch(batch_text)
            self.batch = []

    async def on_complete(self, final_text: str):
        # Process remaining
        if self.batch:
            batch_text = "".join(self.batch)
            await self._process_batch(batch_text)

        print(f"Completed: {final_text}")

    async def _process_batch(self, batch_text: str):
        # Process batch: validate, transform, etc.
        print(f"Batch: {batch_text}", end=" ")
```

### Common Mistake: Blocking on Streaming

```python
# ❌ WRONG - Synchronous processing blocks stream
async def handle_token(token: str):
    process_slowly(token)  # Blocks streaming!
    save_to_database(token)  # Waits for IO

# ✅ CORRECT - Async processing
async def handle_token(token: str):
    await asyncio.gather(
        asyncio.create_task(validate_token(token)),
        asyncio.create_task(save_to_database(token))
    )  # Non-blocking
```

## Integration

### With Generation Module

```python
from cemaf.generation import CodeGenerator
from cemaf.streaming import StreamBuffer

# Stream code generation
class StreamingCodeGenerator:
    async def generate_streaming(self, spec):
        buffer = StreamBuffer()

        async def on_token(token: str):
            buffer.append(token)
            print(token, end="", flush=True)  # Real-time display

        code = await self.generator.generate_streaming(
            spec,
            on_token=on_token,
            buffer=buffer
        )

        return buffer.text
```

### With WebSocket for Chat

```python
from fastapi import WebSocket
from cemaf.streaming import StreamBuffer

@app.websocket("/ws/chat")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()

    while True:
        data = await websocket.receive_text()
        prompt = json.loads(data)["prompt"]

        # Stream response
        buffer = StreamBuffer()
        async for token in llm.generate_stream(prompt):
            buffer.append(token)

            # Send to client
            await websocket.send_json({
                "token": token,
                "position": buffer.token_count
            })

        # Send completion
        await websocket.send_json({
            "complete": True,
            "text": buffer.text,
            "tokens": buffer.token_count
        })
```

## API Reference

### StreamBuffer

```python
class StreamBuffer:
    def __init__(self, max_size: int = 100000):
        """Initialize stream buffer."""

    def append(self, token: str) -> None:
        """Add token to buffer."""

    @property
    def text(self) -> str:
        """Get accumulated text."""

    @property
    def token_count(self) -> int:
        """Get token count."""

    def clear(self) -> None:
        """Clear buffer."""
```

### StreamEvent

```python
@dataclass
class StreamEvent:
    type: str  # "token", "complete", "error", "metadata"
    data: Any
    timestamp: datetime = Field(default_factory=utc_now)
```

### StreamHandler Protocol

```python
@runtime_checkable
class StreamHandler(Protocol):
    async def on_start(self, metadata: dict) -> None:
        """Called when streaming starts."""

    async def on_token(self, token: str) -> None:
        """Called for each token."""

    async def on_complete(self, final_text: str) -> None:
        """Called when streaming completes."""

    async def on_error(self, error: Exception) -> None:
        """Called on error."""
```

### SSEFormatter

```python
class SSEFormatter:
    def format_token(
        self,
        token: str,
        position: int
    ) -> str:
        """Format token as SSE event."""
        return f'data: {json.dumps({"token": token, "position": position})}\n\n'

    def format_complete(
        self,
        text: str,
        token_count: int
    ) -> str:
        """Format completion as SSE event."""
        return f'data: {json.dumps({"complete": true, "text": text, "tokens": token_count})}\n\n'

    def format_error(self, error: str) -> str:
        """Format error as SSE event."""
        return f'data: {json.dumps({"error": error})}\n\n'
```

## Best Practices

### Performance Tips

- **Chunk size tuning**: Find optimal chunk size for your UI (100-500 chars usually good)
- **Async handlers**: Never block in handlers. Use async throughout.
- **Buffer limits**: Set max buffer size to prevent memory issues
- **Client-side throttling**: Web browsers can only render so fast. Throttle updates.

### Network Optimization

```python
# SSE vs WebSocket: choose based on needs
# SSE: simpler, one-way (server → client)
# WebSocket: bidirectional, more overhead

# For chat: WebSocket
# For one-way streaming: SSE
```

### Error Handling

```python
class RobustHandler(StreamHandler):
    async def on_token(self, token: str):
        try:
            await self.process(token)
        except Exception as e:
            await logger.error(f"Token processing failed: {e}")
            # Continue with next token, don't crash

    async def on_error(self, error: Exception):
        await logger.error(f"Stream error: {error}")
        # Graceful degradation
```

### Common Pitfalls

**Blocking on I/O**: Don't do blocking operations in handlers. Queue work instead.

**Buffer overflow**: Monitor buffer size. Stop stream if buffer grows unbounded.

**Incomplete streaming**: Always handle completion properly. Don't lose final tokens.

**No timeout**: Streaming might hang. Always set timeout for safety.

### When NOT to Use

- **Batch processing**: Non-streaming is simpler
- **Fully offline**: Streaming requires async
- **Small outputs**: Overhead not worth it
- **Deterministic workflows**: Streaming complicates logic flow

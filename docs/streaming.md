# Streaming

Server-Sent Events (SSE) and stream buffers for real-time updates.

## Streaming Architecture

```mermaid
flowchart TB
    subgraph Source
        LLM[LLM Stream<br/>Token chunks]
        API[API Stream<br/>Data events]
    end

    subgraph Buffer
        BUF[StreamBuffer<br/>Accumulator]
        CONTENT[Content<br/>Accumulated text]
        COMPLETE[is_complete<br/>Stream status]
    end

    subgraph Output
        SSE[SSEFormatter<br/>Event format]
        CLIENT[Client<br/>Consumer]
    end

    LLM --> BUF
    API --> BUF
    BUF --> CONTENT
    BUF --> COMPLETE
    CONTENT --> SSE
    SSE --> CLIENT
```

## Streaming Flow

```mermaid
sequenceDiagram
    participant Source
    participant Buffer as StreamBuffer
    participant Formatter as SSEFormatter
    participant Client

    Source->>Buffer: accumulate("Hello ")
    Note over Buffer: content: "Hello "

    Source->>Buffer: accumulate("World")
    Note over Buffer: content: "Hello World"

    Buffer->>Formatter: format_content_event(content)
    Formatter-->>Client: SSE data

    Source->>Buffer: mark_complete()
    Note over Buffer: is_complete: true
    Buffer->>Formatter: format_done_event()
    Formatter-->>Client: SSE done
```

## Stream Buffer

```python
from cemaf.streaming.protocols import StreamBuffer

buffer = StreamBuffer()

# Accumulate content
buffer.accumulate("Hello ")
buffer.accumulate("World")

# Get accumulated content
content = buffer.content  # "Hello World"

# Check completion
if buffer.is_complete:
    print("Stream finished")
```

## SSE Formatter

```python
from cemaf.streaming.sse import SSEFormatter

formatter = SSEFormatter()
sse_data = formatter.format_content_event("Hello")
```

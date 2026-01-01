# LLM Module

Protocol-based LLM client abstraction for pluggable backends.

## LLM Architecture

```mermaid
flowchart TB
    subgraph Protocol
        CLIENT[LLMClient<br/>Protocol]
    end

    subgraph Implementations
        OPENAI[OpenAIClient]
        ANTHROPIC[AnthropicClient]
        MOCK[MockLLMClient]
    end

    subgraph Messages
        SYS[System<br/>Instructions]
        USER[User<br/>Input]
        ASST[Assistant<br/>Response]
        TOOL[Tool Result<br/>Function output]
    end

    subgraph Output
        COMPLETE[complete<br/>Full response]
        STREAM[stream<br/>Chunked output]
    end

    CLIENT --> OPENAI
    CLIENT --> ANTHROPIC
    CLIENT --> MOCK
    SYS --> CLIENT
    USER --> CLIENT
    ASST --> CLIENT
    TOOL --> CLIENT
    CLIENT --> COMPLETE
    CLIENT --> STREAM
```

## LLM Request Flow

```mermaid
sequenceDiagram
    participant Caller
    participant Client as LLMClient
    participant API as LLM API
    participant Result as CompletionResult

    Caller->>Client: complete(messages)
    Client->>API: HTTP Request

    alt Success
        API-->>Client: Response
        Client-->>Caller: Result.ok(message)
    else Error
        API-->>Client: Error
        Client-->>Caller: Result.fail(error)
    end

    Note over Caller,Result: Streaming variant
    Caller->>Client: stream(messages)
    loop Chunks
        API-->>Client: Chunk
        Client-->>Caller: yield chunk
    end
```

## LLM Client Protocol

```python
from cemaf.llm.protocols import LLMClient, Message, CompletionResult

# Use any LLM implementation
llm: LLMClient = OpenAIClient()  # or AnthropicClient(), MockLLMClient()

# Complete
result = await llm.complete([
    Message.system("You are a helpful assistant"),
    Message.user("Hello!")
])

if result.success:
    print(result.message.content)
```

## Message Types

```python
from cemaf.llm.protocols import Message

system_msg = Message.system("System prompt")
user_msg = Message.user("User input")
assistant_msg = Message.assistant("Response")
tool_msg = Message.tool_result("tool_id", "result")
```

## Streaming

```python
async for chunk in llm.stream(messages):
    print(chunk.content, end="", flush=True)
```

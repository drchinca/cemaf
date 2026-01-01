# Events

Event bus and notifiers for system-wide communication.

## Event Architecture

```mermaid
flowchart TB
    subgraph Publishers
        PUB1[Publisher 1]
        PUB2[Publisher 2]
    end

    subgraph Event Bus
        BUS[InMemoryEventBus]
        TOPICS[Topics<br/>Event routing]
    end

    subgraph Subscribers
        SUB1[Handler 1]
        SUB2[Handler 2]
        SUB3[Handler 3]
    end

    PUB1 --> BUS
    PUB2 --> BUS
    BUS --> TOPICS
    TOPICS --> SUB1
    TOPICS --> SUB2
    TOPICS --> SUB3
```

## Event Flow

```mermaid
sequenceDiagram
    participant Publisher
    participant Bus as EventBus
    participant Handler1
    participant Handler2

    Note over Bus: Register handlers
    Handler1->>Bus: subscribe("my_event", handler1)
    Handler2->>Bus: subscribe("my_event", handler2)

    Note over Bus: Publish event
    Publisher->>Bus: publish(Event)
    Bus->>Handler1: handler1(event)
    Bus->>Handler2: handler2(event)
    Handler1-->>Bus: Done
    Handler2-->>Bus: Done
```

## Event Bus

```python
from cemaf.events.bus import InMemoryEventBus
from cemaf.events.protocols import Event

bus = InMemoryEventBus()

# Subscribe
async def handler(event: Event):
    print(f"Received: {event.type}")

await bus.subscribe("my_event", handler)

# Publish
await bus.publish(Event(type="my_event", data={"key": "value"}))
```

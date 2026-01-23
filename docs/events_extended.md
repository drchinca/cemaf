# Events Module - Extended Documentation

## Overview

The events module provides pub/sub event bus infrastructure with support for async event handling, webhook notifications, and third-party integrators.

**What it does**: Implements event bus pattern enabling decoupled component communication. Publishers emit events (content published, run completed, error occurred), subscribers listen and react asynchronously. Supports webhooks for external system integration and composite notifiers for multi-channel notifications.

**Key use cases**:
- Notify external systems when content is published (Slack, Discord, webhooks)
- Trigger downstream workflows when events occur
- Implement audit logging through events
- Decouple components (generation doesn't know about publishing)
- Build real-time dashboards through event streaming
- Enable third-party integrations via webhooks

**When to use vs. alternatives**: Use events for async notifications and decoupling. Use it when publishers don't need to wait for responses. Don't use for request-response patterns (use direct calls) or critical state changes (use persistence first, then events).

## Core Concepts

### Event Architecture

**Event**: Data structure describing something that happened (ContentPublished, RunCompleted, ErrorOccurred). Contains type, timestamp, and payload.

**Publisher**: Entity that emits events. Generation system publishes RunCompleted. Publishing system publishes ContentPublished.

**Subscriber**: Async handler that listens for events. Slack notifier subscribes to errors. Webhook subscriber subscribes to all events.

**EventBus**: Central hub routing events from publishers to subscribers. In-memory for single process, distributed for multi-process.

**Notifier**: Specialized subscriber sending notifications (webhook, logging, email, Slack, etc.).

### Event Flow

```
Publisher emits Event → EventBus → Routes to Subscribers → Subscribers handle async
                                 → Routes to Notifiers → Notifiers notify external
```

Publishers don't wait for subscribers. Subscribers handle events asynchronously.

## Usage Examples

### Basic Event Pub/Sub

```python
from cemaf.events import InMemoryEventBus, Event, EventType

# Create event bus
bus = InMemoryEventBus()

# Define events
class ContentPublishedEvent(Event):
    type: EventType = "content.published"
    content_id: str
    platform: str
    timestamp: datetime

class ErrorEvent(Event):
    type: EventType = "error.occurred"
    error_message: str
    component: str
    timestamp: datetime

# Subscribe to events
async def handle_content_published(event: ContentPublishedEvent):
    print(f"Content published: {event.content_id} on {event.platform}")

async def handle_error(event: ErrorEvent):
    await logger.error(
        "Event error occurred",
        component=event.component,
        error=event.error_message
    )

bus.subscribe("content.published", handle_content_published)
bus.subscribe("error.occurred", handle_error)

# Publish events
await bus.publish(ContentPublishedEvent(
    content_id="cnt_123",
    platform="twitter",
    timestamp=utc_now()
))
```

### Webhook Notifications

```python
from cemaf.events import WebhookNotifier

# Setup webhook notifier
webhook = WebhookNotifier(
    url="https://example.com/webhooks/cemaf",
    events=["content.published", "error.occurred"],
    retry_attempts=3,
    timeout_seconds=10
)

bus.register_notifier(webhook)

# Now all events are sent to webhook
# POST https://example.com/webhooks/cemaf
# {
#     "type": "content.published",
#     "content_id": "cnt_123",
#     "platform": "twitter",
#     "timestamp": "2025-01-23T10:30:00Z"
# }
```

### Multi-Channel Notifications

```python
from cemaf.events import (
    CompositeNotifier,
    WebhookNotifier,
    LoggingNotifier,
    SlackNotifier  # if available
)

# Create composite notifier with multiple channels
notifier = CompositeNotifier([
    WebhookNotifier("https://example.com/webhooks"),
    LoggingNotifier(),  # Log all events
    SlackNotifier(channel="#alerts", only_errors=True),  # Slack on errors only
])

bus.register_notifier(notifier)
```

### Event-Driven Publishing Workflow

```python
from cemaf.events import InMemoryEventBus

bus = InMemoryEventBus()

# Step 1: When content is generated, emit event
async def on_content_generated(event):
    """React to generation completion."""
    print(f"Generated content {event.content_id}")
    await send_for_review(event.content_id)

# Step 2: When approved, emit approval event
async def on_content_approved(event):
    """React to approval."""
    print(f"Content {event.content_id} approved")
    await schedule_publishing(event.content_id)

# Step 3: When published, emit publication event
async def on_content_published(event):
    """React to publication."""
    print(f"Published {event.content_id} on {event.platform}")
    await notify_team(event)

bus.subscribe("content.generated", on_content_generated)
bus.subscribe("content.approved", on_content_approved)
bus.subscribe("content.published", on_content_published)

# Workflow executes as sequence of events
await bus.publish(Event(type="content.generated", content_id="cnt_123"))
# → triggers on_content_generated
# → emits content.approved event
# → triggers on_content_approved
# → emits content.published event
# → triggers on_content_published
```

### Async Error Handling

```python
from cemaf.events import EventBus

class ResilientSubscriber:
    """Subscriber that doesn't crash on handler errors."""

    async def handle_with_retry(self, event: Event, handler):
        """Handle event with retry and error logging."""
        for attempt in range(3):
            try:
                await handler(event)
                return  # Success

            except asyncio.TimeoutError:
                await logger.warning(
                    "Event handler timeout",
                    event_type=event.type,
                    attempt=attempt
                )
            except Exception as e:
                if attempt < 2:
                    await asyncio.sleep(2 ** attempt)  # Exponential backoff
                else:
                    await logger.error(
                        "Event handler failed",
                        event_type=event.type,
                        error=str(e)
                    )
```

### Audit Trail Through Events

```python
from cemaf.events import InMemoryEventBus, LoggingNotifier

# Setup audit logging
audit_notifier = LoggingNotifier(logger="audit")

bus = InMemoryEventBus()
bus.register_notifier(audit_notifier)

# All events automatically logged for audit
await bus.publish(Event(
    type="content.published",
    content_id="cnt_123",
    publisher="user_456",
    timestamp=utc_now()
))

# Audit log:
# [2025-01-23 10:30:00] AUDIT: content.published
# content_id: cnt_123, publisher: user_456
```

### Event Filtering and Routing

```python
class SmartRouter:
    """Route events to different handlers based on criteria."""

    async def route(self, event: Event, bus: EventBus):
        """Route event based on content."""
        if event.type == "error.occurred":
            # Critical errors go to emergency channel
            if event.severity == "critical":
                await bus.publish(Event(
                    type="alert.critical",
                    original_event=event
                ))
            else:
                await logger.warning(f"Error: {event.error}")

        elif event.type == "content.published":
            # Notify different channels by platform
            if event.platform == "twitter":
                await slack.notify(f"Tweet posted: {event.content_id}")
            elif event.platform == "linkedin":
                await slack.notify(f"Article published: {event.content_id}")
```

### Common Mistake: Synchronous Event Handling

```python
# ❌ WRONG - Blocking subscribers delay publishing
async def slow_handler(event):
    time.sleep(5)  # Blocks everything!
    process(event)

# ✅ CORRECT - Non-blocking async handling
async def fast_handler(event):
    asyncio.create_task(async_process(event))  # Non-blocking
    return immediately

# ✅ CORRECT - Offload to background task
async def offloading_handler(event):
    await background_queue.add(event)  # Queue for later
    return immediately
```

## Integration

### With Persistence Module

```python
from cemaf.events import EventBus
from cemaf.persistence.entities import Run

# Publish event when run completes
async def complete_run(run_store, bus: EventBus, run: Run):
    updated_run = run.with_completion(
        status=RunStatus.COMPLETED,
        outputs={...}
    )
    await run_store.update(updated_run)

    # Notify subscribers
    await bus.publish(Event(
        type="run.completed",
        run_id=run.id,
        project_id=run.project_id,
        timestamp=utc_now()
    ))
```

### With Observability

```python
from cemaf.observability.logger import StructuredLogger

class EventLogger(LoggingNotifier):
    """Log events with structured format."""

    async def notify(self, event: Event) -> NotifyResult:
        await logger.info(
            f"Event: {event.type}",
            event_type=event.type,
            timestamp=event.timestamp,
            **event.to_dict()
        )
        return NotifyResult.ok()
```

### With Scheduling

```python
from cemaf.scheduler import Scheduler, Job, IntervalTrigger
from cemaf.events import EventBus

# Scheduled job that publishes events
async def scheduled_analysis():
    results = await perform_analysis()
    await bus.publish(Event(
        type="analysis.completed",
        results=results
    ))

scheduler = Scheduler()
job = Job(
    name="periodic_analysis",
    func=scheduled_analysis,
    trigger=IntervalTrigger(hours=1)
)
await scheduler.schedule(job)
```

## API Reference

### Event Base Class

```python
@dataclass
class Event:
    type: str              # Event type identifier
    timestamp: datetime = Field(default_factory=utc_now)
    # Additional fields in subclasses
```

### EventHandler Protocol

```python
@runtime_checkable
class EventHandler(Protocol):
    async def __call__(self, event: Event) -> None:
        """Handle event asynchronously."""
```

### EventBus Protocol

```python
@runtime_checkable
class EventBus(Protocol):
    async def publish(self, event: Event) -> None:
        """Publish event to all subscribers."""

    def subscribe(
        self,
        event_type: str,
        handler: EventHandler
    ) -> None:
        """Subscribe to event type."""

    def unsubscribe(
        self,
        event_type: str,
        handler: EventHandler
    ) -> bool:
        """Unsubscribe from event type."""

    def register_notifier(self, notifier: Notifier) -> None:
        """Register notifier."""
```

### Notifier Protocol

```python
@dataclass
class NotifyResult:
    success: bool
    message: str = ""

    @classmethod
    def ok(cls) -> NotifyResult:
        return cls(success=True)

    @classmethod
    def error(cls, message: str) -> NotifyResult:
        return cls(success=False, message=message)

@runtime_checkable
class Notifier(Protocol):
    async def notify(self, event: Event) -> NotifyResult:
        """Send notification based on event."""
```

### Notifier Implementations

```python
class LoggingNotifier(Notifier):
    """Log events."""
    def __init__(self, logger=None, level="info"): ...

class WebhookNotifier(Notifier):
    """Send events via HTTP webhook."""
    def __init__(
        self,
        url: str,
        events: list[str] | None = None,
        retry_attempts: int = 3,
        timeout_seconds: int = 10
    ): ...

class CompositeNotifier(Notifier):
    """Combine multiple notifiers."""
    def __init__(self, notifiers: list[Notifier]): ...
```

## Best Practices

### Performance Tips

- **Non-blocking handlers**: Never block in event handlers. Use async throughout.
- **Offload heavy work**: Long operations should be queued, not handled synchronously
- **Error isolation**: Handler errors shouldn't affect other handlers
- **Batch processing**: When many events arrive, batch processing is more efficient

### Event Design

```python
# ✅ GOOD - Events are immutable data
@dataclass(frozen=True)
class ContentPublishedEvent(Event):
    type: EventType = "content.published"
    content_id: str
    platform: str
    url: str
    timestamp: datetime = Field(default_factory=utc_now)

# ❌ BAD - Events with mutable state
class Event:
    def __init__(self, data):
        self.data = data  # Mutable!
        self.data['processed'] = False

    def process(self):
        self.data['processed'] = True  # Side effects
```

### Subscriber Pattern

```python
# ✅ GOOD - Idempotent handling
async def handle_publish(event):
    # Can safely run multiple times
    content = await content_store.get(event.content_id)
    if content.status == ContentStatus.PUBLISHED:
        return  # Already processed

    # Process
    await content_store.update(content.with_status(...))

# ❌ BAD - Non-idempotent
async def handle_publish(event):
    await increment_counter()  # What if called twice?
    await publish_content(event.content_id)  # What if fails and retries?
```

### Common Pitfalls

**Fire and forget without guarantees**: Events don't guarantee delivery. For critical state changes, persist first, then publish event.

**Unbounded handler delays**: If handlers are slow, events queue up. Monitor and optimize.

**Lost errors**: Always log handler errors. Use try/catch and observability.

**Tight coupling**: Don't let subscribers know about other subscribers. Keep decoupled.

**No replay capability**: Store events if you need to replay history. In-memory bus loses events on crash.

### When NOT to Use

- **Request/Response**: Use direct calls, not events
- **Critical state changes**: Persist first, then event
- **Real-time sync**: Events are async, not suitable for real-time
- **Guaranteed delivery**: Events don't guarantee delivery without persistent queue

### Event Strategy

```python
# Identify all state changes worth notifying about
STATE_CHANGE_EVENTS = {
    # Content lifecycle
    "content.generated": "Content created by generation",
    "content.approved": "Content approved for publishing",
    "content.published": "Content published to platform",
    "content.failed": "Content failed validation/moderation",

    # Run lifecycle
    "run.started": "Pipeline execution started",
    "run.completed": "Pipeline execution completed",
    "run.failed": "Pipeline execution failed",

    # System events
    "system.error": "System error occurred",
    "system.health_degraded": "System health is degraded",
}

# Map to handlers
handlers = {
    "content.published": [notify_slack, update_dashboard, send_webhook],
    "run.failed": [alert_ops, log_error],
    "system.error": [page_oncall],
}
```

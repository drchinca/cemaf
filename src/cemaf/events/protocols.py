"""
Event protocols and base types.

Defines the contracts for event buses, handlers, and notifiers.
"""

from collections.abc import Callable
from datetime import datetime
from enum import Enum
from typing import Any, Protocol, runtime_checkable
from uuid import uuid4

from pydantic import BaseModel, Field

from cemaf.core.types import JSON


class EventType(str, Enum):
    """Common event types."""

    # Task lifecycle
    TASK_STARTED = "task.started"
    TASK_COMPLETED = "task.completed"
    TASK_FAILED = "task.failed"

    # Validation
    VALIDATION_PASSED = "validation.passed"
    VALIDATION_FAILED = "validation.failed"

    # Content
    CONTENT_GENERATED = "content.generated"
    CONTENT_SCHEDULED = "content.scheduled"
    CONTENT_PUBLISHED = "content.published"

    # Agent
    AGENT_SPAWNED = "agent.spawned"
    AGENT_COMPLETED = "agent.completed"

    # DAG
    DAG_STARTED = "dag.started"
    DAG_COMPLETED = "dag.completed"
    DAG_CHECKPOINT = "dag.checkpoint"

    # System
    SYSTEM_ERROR = "system.error"
    SYSTEM_WARNING = "system.warning"

    # Context events (context engineering)
    CONTEXT_PATCH_APPLIED = "context.patch.applied"
    CONTEXT_COMPILED = "context.compiled"
    CONTEXT_BUDGET_EXCEEDED = "context.budget.exceeded"

    # Tool events
    TOOL_CALL_STARTED = "tool.call.started"
    TOOL_CALL_COMPLETED = "tool.call.completed"
    TOOL_CALL_FAILED = "tool.call.failed"

    # Replay events
    REPLAY_STARTED = "replay.started"
    REPLAY_COMPLETED = "replay.completed"

    # Memory events
    MEMORY_ITEM_SET = "memory.item.set"
    MEMORY_ITEM_EXPIRED = "memory.item.expired"
    MEMORY_CLEANUP = "memory.cleanup"

    # Execution events
    EXECUTION_CANCELLED = "execution.cancelled"
    EXECUTION_TIMEOUT = "execution.timeout"

    # Moderation events
    MODERATION_CHECK_STARTED = "moderation.check.started"
    MODERATION_CHECK_PASSED = "moderation.check.passed"
    MODERATION_CHECK_BLOCKED = "moderation.check.blocked"
    MODERATION_VIOLATION = "moderation.violation"

    # Citation events
    CITATION_ADDED = "citation.added"
    CITATION_MISSING = "citation.missing"
    CITATION_VALIDATION_FAILED = "citation.validation.failed"

    # MCP events
    MCP_SERVER_STARTED = "mcp.server.started"
    MCP_SERVER_STOPPED = "mcp.server.stopped"
    MCP_TOOL_CALLED = "mcp.tool.called"
    MCP_RESOURCE_READ = "mcp.resource.read"
    MCP_PROMPT_GET = "mcp.prompt.get"

    # Blueprint events
    BLUEPRINT_VALIDATED = "blueprint.validated"
    BLUEPRINT_VALIDATION_FAILED = "blueprint.validation.failed"


class Event(BaseModel):
    """
    An event in the system.

    Events are immutable records of something that happened.
    """

    model_config = {"frozen": True}

    id: str = Field(default_factory=lambda: str(uuid4()))
    type: str  # Event type (use EventType enum or custom string)
    payload: JSON = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.now)
    source: str = ""  # Component that emitted the event
    correlation_id: str | None = None  # For tracing related events
    metadata: JSON = Field(default_factory=dict)

    @classmethod
    def create(
        cls,
        type: str | EventType,
        payload: JSON | None = None,
        source: str = "",
        correlation_id: str | None = None,
        metadata: JSON | None = None,
    ) -> Event:
        """
        Factory method to create an event.

        Args:
            type: Event type.
            payload: Event data.
            source: Component that emitted the event.
            correlation_id: For tracing related events.
            metadata: Additional metadata.

        Returns:
            New Event instance.
        """
        event_type = type.value if isinstance(type, EventType) else type
        return cls(
            type=event_type,
            payload=payload or {},
            source=source,
            correlation_id=correlation_id,
            metadata=metadata or {},
        )


class NotifyResult(BaseModel):
    """Result of a notification attempt."""

    model_config = {"frozen": True}

    success: bool
    message: str = ""
    error: str | None = None
    retry_after: int | None = None  # Seconds to wait before retry
    metadata: JSON = Field(default_factory=dict)

    @classmethod
    def ok(cls, message: str = "Success") -> NotifyResult:
        return cls(success=True, message=message)

    @classmethod
    def fail(
        cls,
        error: str,
        retry_after: int | None = None,
    ) -> NotifyResult:
        return cls(success=False, error=error, retry_after=retry_after)


@runtime_checkable
class EventHandler(Protocol):
    """
    Protocol for event handlers.

    An EventHandler processes events of specific types.
    """

    async def handle(self, event: Event) -> None:
        """
        Handle an event.

        Args:
            event: The event to process.

        Raises:
            Any exception if handling fails.
        """
        ...


@runtime_checkable
class EventBus(Protocol):
    """
    Protocol for event buses.

    An EventBus provides pub/sub functionality for events.
    """

    async def publish(self, event: Event) -> None:
        """
        Publish an event to all subscribers.

        Args:
            event: The event to publish.
        """
        ...

    async def publish_batch(self, events: list[Event]) -> None:
        """
        Publish multiple events.

        Args:
            events: Events to publish.
        """
        ...

    def subscribe(
        self,
        event_type: str | EventType,
        handler: EventHandler | Callable[[Event], Any],
    ) -> Callable[[], None]:
        """
        Subscribe to events of a specific type.

        Args:
            event_type: Type of events to subscribe to.
            handler: Handler to call when event occurs.

        Returns:
            Unsubscribe function.
        """
        ...

    def subscribe_all(
        self,
        handler: EventHandler | Callable[[Event], Any],
    ) -> Callable[[], None]:
        """
        Subscribe to all events.

        Args:
            handler: Handler to call for any event.

        Returns:
            Unsubscribe function.
        """
        ...


@runtime_checkable
class Notifier(Protocol):
    """
    Protocol for external notifiers.

    A Notifier sends events to external systems
    (webhooks, Slack, email, etc.).
    """

    @property
    def name(self) -> str:
        """Notifier identifier."""
        ...

    async def notify(self, event: Event) -> NotifyResult:
        """
        Send notification for an event.

        Args:
            event: Event to notify about.

        Returns:
            NotifyResult indicating success/failure.
        """
        ...

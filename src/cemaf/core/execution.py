"""
Execution context and cancellation support.

This module provides:
- CancellationToken: Cooperative cancellation for async operations
- ExecutionContext: Context for execution with timeout/cancellation
- CancelledException: Exception raised when operation is cancelled
"""

import asyncio
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from cemaf.core.utils import utc_now


class CancelledException(Exception):
    """Exception raised when an operation is cancelled."""

    def __init__(self, message: str = "Operation was cancelled") -> None:
        super().__init__(message)
        self.message = message


class TimeoutException(Exception):
    """Exception raised when an operation times out."""

    def __init__(
        self,
        message: str = "Operation timed out",
        timeout_ms: float | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.timeout_ms = timeout_ms


class CancellationToken:
    """
    Cooperative cancellation token for async operations.

    Usage:
        token = CancellationToken()

        # In async code, check periodically
        async def long_running():
            for i in range(100):
                token.raise_if_cancelled()
                await process_item(i)

        # From outside, cancel the operation
        token.cancel()

    Can be linked to other tokens:
        parent = CancellationToken()
        child = CancellationToken(parent=parent)

        parent.cancel()  # Also cancels child
    """

    def __init__(
        self,
        parent: CancellationToken | None = None,
        reason: str = "",
    ) -> None:
        self._cancelled = False
        self._reason = reason
        self._parent = parent
        self._callbacks: list[Callable[[], None]] = []
        self._cancelled_at: datetime | None = None

    @property
    def is_cancelled(self) -> bool:
        """Check if cancellation has been requested."""
        if self._cancelled:
            return True
        return bool(self._parent and self._parent.is_cancelled)

    @property
    def reason(self) -> str:
        """Get the cancellation reason."""
        if self._cancelled:
            return self._reason
        if self._parent and self._parent.is_cancelled:
            return self._parent.reason
        return ""

    @property
    def cancelled_at(self) -> datetime | None:
        """Get when cancellation occurred."""
        if self._cancelled:
            return self._cancelled_at
        if self._parent and self._parent.is_cancelled:
            return self._parent.cancelled_at
        return None

    def cancel(self, reason: str = "") -> None:
        """
        Request cancellation.

        Args:
            reason: Optional reason for cancellation
        """
        if self._cancelled:
            return

        self._cancelled = True
        self._reason = reason
        self._cancelled_at = utc_now()

        # Notify callbacks
        for callback in self._callbacks:
            try:
                callback()
            except Exception:
                pass  # Ignore callback errors

    def raise_if_cancelled(self) -> None:
        """
        Raise CancelledException if cancellation has been requested.

        Call this periodically in long-running operations.
        """
        if self.is_cancelled:
            raise CancelledException(self.reason or "Operation was cancelled")

    def on_cancel(self, callback: Callable[[], None]) -> Callable[[], None]:
        """
        Register a callback to be called on cancellation.

        Args:
            callback: Function to call when cancelled

        Returns:
            Function to unregister the callback
        """
        self._callbacks.append(callback)

        def unregister() -> None:
            if callback in self._callbacks:
                self._callbacks.remove(callback)

        return unregister

    def create_child(self, reason: str = "") -> CancellationToken:
        """
        Create a child token linked to this one.

        The child is cancelled when either:
        - The child's cancel() is called
        - The parent's cancel() is called
        """
        return CancellationToken(parent=self, reason=reason)

    @classmethod
    def none(cls) -> CancellationToken:
        """Create a token that is never cancelled."""
        return cls()


@dataclass
class ExecutionContext:
    """
    Context for execution with timeout, cancellation, and metadata.

    Provides a unified way to pass execution parameters through
    the call stack.

    Usage:
        ctx = ExecutionContext(
            timeout_ms=5000,
            cancellation_token=token,
        )

        # Check deadline
        if ctx.is_expired:
            return

        # Check cancellation
        ctx.raise_if_cancelled()

        # Get remaining time
        remaining = ctx.remaining_ms
    """

    cancellation_token: CancellationToken = field(default_factory=CancellationToken)
    timeout_ms: int | None = None
    deadline: datetime | None = None
    correlation_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    # Internal tracking
    _started_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        """Set deadline from timeout if not provided."""
        if self.timeout_ms and not self.deadline:
            self.deadline = self._started_at + timedelta(milliseconds=self.timeout_ms)

    @property
    def is_cancelled(self) -> bool:
        """Check if cancelled."""
        return self.cancellation_token.is_cancelled

    @property
    def is_expired(self) -> bool:
        """Check if deadline has passed."""
        if not self.deadline:
            return False
        return utc_now() >= self.deadline

    @property
    def is_active(self) -> bool:
        """Check if execution can continue (not cancelled, not expired)."""
        return not self.is_cancelled and not self.is_expired

    @property
    def remaining_ms(self) -> float | None:
        """Get remaining time in milliseconds, or None if no deadline."""
        if not self.deadline:
            return None
        remaining = (self.deadline - utc_now()).total_seconds() * 1000
        return max(0, remaining)

    @property
    def elapsed_ms(self) -> float:
        """Get elapsed time in milliseconds."""
        return (utc_now() - self._started_at).total_seconds() * 1000

    def raise_if_cancelled(self) -> None:
        """Raise CancelledException if cancelled."""
        self.cancellation_token.raise_if_cancelled()

    def raise_if_expired(self) -> None:
        """Raise TimeoutException if expired."""
        if self.is_expired:
            raise TimeoutException(
                f"Operation timed out after {self.timeout_ms}ms",
                timeout_ms=self.timeout_ms,
            )

    def raise_if_inactive(self) -> None:
        """Raise if either cancelled or expired."""
        self.raise_if_cancelled()
        self.raise_if_expired()

    def with_timeout(self, timeout_ms: int) -> ExecutionContext:
        """
        Create a new context with a different timeout.

        The new timeout is capped by the current deadline.
        """
        new_deadline = utc_now() + timedelta(milliseconds=timeout_ms)

        # Cap by existing deadline if present
        if self.deadline and new_deadline > self.deadline:
            new_deadline = self.deadline

        return ExecutionContext(
            cancellation_token=self.cancellation_token.create_child(),
            timeout_ms=timeout_ms,
            deadline=new_deadline,
            correlation_id=self.correlation_id,
            metadata=dict(self.metadata),
        )

    def with_correlation_id(self, correlation_id: str) -> ExecutionContext:
        """Create a new context with a different correlation ID."""
        return ExecutionContext(
            cancellation_token=self.cancellation_token,
            timeout_ms=self.timeout_ms,
            deadline=self.deadline,
            correlation_id=correlation_id,
            metadata=dict(self.metadata),
        )

    @classmethod
    def default(cls) -> ExecutionContext:
        """Create a default execution context with no timeout."""
        return cls()

    @classmethod
    def with_deadline(cls, deadline: datetime) -> ExecutionContext:
        """Create a context with a specific deadline."""
        timeout_ms = int((deadline - utc_now()).total_seconds() * 1000)
        return cls(timeout_ms=max(0, timeout_ms), deadline=deadline)


async def with_cancellation[T](
    coro: Coroutine[Any, Any, T],
    token: CancellationToken,
) -> T:
    """
    Execute a coroutine with cancellation support.

    Periodically checks the token and cancels the coroutine if requested.

    Args:
        coro: The coroutine to execute
        token: Cancellation token to check

    Returns:
        The result of the coroutine

    Raises:
        CancelledException: If cancelled before completion
    """
    task = asyncio.create_task(coro)

    # Register callback to cancel task
    def on_cancel() -> None:
        task.cancel()

    unregister = token.on_cancel(on_cancel)

    try:
        if token.is_cancelled:
            task.cancel()
            raise CancelledException(token.reason)

        return await task

    except asyncio.CancelledError:
        if token.is_cancelled:
            raise CancelledException(token.reason) from None
        raise

    finally:
        unregister()


async def with_timeout[T](
    coro: Coroutine[Any, Any, T],
    timeout_ms: int,
) -> T:
    """
    Execute a coroutine with a timeout.

    Args:
        coro: The coroutine to execute
        timeout_ms: Timeout in milliseconds

    Returns:
        The result of the coroutine

    Raises:
        TimeoutException: If the timeout is exceeded
    """
    try:
        return await asyncio.wait_for(
            coro,
            timeout=timeout_ms / 1000,
        )
    except TimeoutError:
        raise TimeoutException(
            f"Operation timed out after {timeout_ms}ms",
            timeout_ms=timeout_ms,
        ) from None


async def with_execution_context[T](
    coro: Coroutine[Any, Any, T],
    ctx: ExecutionContext,
) -> T:
    """
    Execute a coroutine with an execution context.

    Combines cancellation and timeout checking.

    Args:
        coro: The coroutine to execute
        ctx: Execution context with timeout/cancellation

    Returns:
        The result of the coroutine

    Raises:
        CancelledException: If cancelled
        TimeoutException: If timeout exceeded
    """
    # Check pre-conditions
    ctx.raise_if_inactive()

    # Wrap with cancellation
    coro_with_cancel = with_cancellation(coro, ctx.cancellation_token)

    # Wrap with timeout if deadline set
    if ctx.remaining_ms is not None:
        return await with_timeout(coro_with_cancel, int(ctx.remaining_ms))

    return await coro_with_cancel

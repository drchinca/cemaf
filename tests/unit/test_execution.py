"""Tests for execution context and cancellation."""

import asyncio

import pytest

from cemaf.core.execution import (
    CancellationToken,
    CancelledException,
    ExecutionContext,
    TimeoutException,
    with_cancellation,
    with_execution_context,
    with_timeout,
)


class TestCancellationToken:
    """Tests for CancellationToken."""

    def test_initial_state(self) -> None:
        """Test that token starts not cancelled."""
        token = CancellationToken()

        assert token.is_cancelled is False
        assert token.reason == ""
        assert token.cancelled_at is None

    def test_cancel(self) -> None:
        """Test cancelling a token."""
        token = CancellationToken()
        token.cancel(reason="User requested")

        assert token.is_cancelled is True
        assert token.reason == "User requested"
        assert token.cancelled_at is not None

    def test_cancel_idempotent(self) -> None:
        """Test that cancelling twice doesn't change state."""
        token = CancellationToken()
        token.cancel(reason="First")
        first_time = token.cancelled_at

        token.cancel(reason="Second")

        assert token.reason == "First"
        assert token.cancelled_at == first_time

    def test_raise_if_cancelled(self) -> None:
        """Test raise_if_cancelled."""
        token = CancellationToken()

        # Should not raise when not cancelled
        token.raise_if_cancelled()

        # Should raise when cancelled
        token.cancel(reason="Test")
        with pytest.raises(CancelledException) as exc_info:
            token.raise_if_cancelled()

        assert "Test" in str(exc_info.value)

    def test_on_cancel_callback(self) -> None:
        """Test cancellation callback."""
        token = CancellationToken()
        callback_called = False

        def callback() -> None:
            nonlocal callback_called
            callback_called = True

        token.on_cancel(callback)
        assert callback_called is False

        token.cancel()
        assert callback_called is True

    def test_unregister_callback(self) -> None:
        """Test unregistering callback."""
        token = CancellationToken()
        callback_called = False

        def callback() -> None:
            nonlocal callback_called
            callback_called = True

        unregister = token.on_cancel(callback)
        unregister()

        token.cancel()
        assert callback_called is False

    def test_parent_child_tokens(self) -> None:
        """Test parent-child token relationship."""
        parent = CancellationToken()
        child = parent.create_child()

        # Child should not be cancelled initially
        assert child.is_cancelled is False

        # Cancelling parent should cancel child
        parent.cancel(reason="Parent cancelled")
        assert child.is_cancelled is True
        assert child.reason == "Parent cancelled"

    def test_child_cancel_independent(self) -> None:
        """Test that cancelling child doesn't cancel parent."""
        parent = CancellationToken()
        child = parent.create_child()

        child.cancel(reason="Child cancelled")

        assert child.is_cancelled is True
        assert parent.is_cancelled is False

    def test_none_token(self) -> None:
        """Test CancellationToken.none()."""
        token = CancellationToken.none()
        assert token.is_cancelled is False


class TestExecutionContext:
    """Tests for ExecutionContext."""

    def test_default_context(self) -> None:
        """Test default execution context."""
        ctx = ExecutionContext.default()

        assert ctx.is_cancelled is False
        assert ctx.is_expired is False
        assert ctx.is_active is True
        assert ctx.deadline is None
        assert ctx.remaining_ms is None

    def test_with_timeout(self) -> None:
        """Test context with timeout."""
        ctx = ExecutionContext(timeout_ms=5000)

        assert ctx.timeout_ms == 5000
        assert ctx.deadline is not None
        assert ctx.is_expired is False
        # Should have roughly 5 seconds remaining
        remaining = ctx.remaining_ms
        assert remaining is not None
        assert 4000 < remaining <= 5000

    def test_elapsed_time(self) -> None:
        """Test elapsed time tracking."""
        ctx = ExecutionContext()

        # Should have some elapsed time
        elapsed = ctx.elapsed_ms
        assert elapsed >= 0

    def test_is_cancelled(self) -> None:
        """Test cancelled state."""
        token = CancellationToken()
        ctx = ExecutionContext(cancellation_token=token)

        assert ctx.is_cancelled is False

        token.cancel()
        assert ctx.is_cancelled is True
        assert ctx.is_active is False

    def test_raise_if_cancelled(self) -> None:
        """Test raise_if_cancelled."""
        token = CancellationToken()
        ctx = ExecutionContext(cancellation_token=token)

        # Should not raise
        ctx.raise_if_cancelled()

        token.cancel()
        with pytest.raises(CancelledException):
            ctx.raise_if_cancelled()

    def test_raise_if_inactive(self) -> None:
        """Test raise_if_inactive."""
        token = CancellationToken()
        ctx = ExecutionContext(cancellation_token=token, timeout_ms=5000)

        # Should not raise when active
        ctx.raise_if_inactive()

        # Should raise when cancelled
        token.cancel()
        with pytest.raises(CancelledException):
            ctx.raise_if_inactive()

    def test_with_timeout_caps_deadline(self) -> None:
        """Test that with_timeout caps the deadline."""
        ctx = ExecutionContext(timeout_ms=1000)
        original_deadline = ctx.deadline

        # Creating with longer timeout should still use parent deadline
        child = ctx.with_timeout(5000)
        assert child.deadline == original_deadline

    def test_with_correlation_id(self) -> None:
        """Test with_correlation_id."""
        ctx = ExecutionContext(correlation_id="parent-123")
        child = ctx.with_correlation_id("child-456")

        assert child.correlation_id == "child-456"


class TestWithCancellation:
    """Tests for with_cancellation helper."""

    @pytest.mark.asyncio
    async def test_normal_completion(self) -> None:
        """Test normal completion without cancellation."""
        token = CancellationToken()

        async def task() -> int:
            return 42

        result = await with_cancellation(task(), token)
        assert result == 42

    @pytest.mark.asyncio
    async def test_cancelled_before_start(self) -> None:
        """Test cancellation before task starts."""
        token = CancellationToken()
        token.cancel()

        async def task() -> int:
            return 42

        with pytest.raises(CancelledException):
            await with_cancellation(task(), token)


class TestWithTimeout:
    """Tests for with_timeout helper."""

    @pytest.mark.asyncio
    async def test_normal_completion(self) -> None:
        """Test normal completion within timeout."""

        async def task() -> int:
            await asyncio.sleep(0.01)
            return 42

        result = await with_timeout(task(), timeout_ms=1000)
        assert result == 42

    @pytest.mark.asyncio
    async def test_timeout(self) -> None:
        """Test timeout exception."""

        async def slow_task() -> int:
            await asyncio.sleep(10)
            return 42

        with pytest.raises(TimeoutException) as exc_info:
            await with_timeout(slow_task(), timeout_ms=50)

        assert exc_info.value.timeout_ms == 50


class TestWithExecutionContext:
    """Tests for with_execution_context helper."""

    @pytest.mark.asyncio
    async def test_normal_execution(self) -> None:
        """Test normal execution with context."""
        ctx = ExecutionContext(timeout_ms=1000)

        async def task() -> int:
            return 42

        result = await with_execution_context(task(), ctx)
        assert result == 42

    @pytest.mark.asyncio
    async def test_cancelled_context(self) -> None:
        """Test execution with cancelled context."""
        token = CancellationToken()
        token.cancel()
        ctx = ExecutionContext(cancellation_token=token)

        async def task() -> int:
            return 42

        with pytest.raises(CancelledException):
            await with_execution_context(task(), ctx)

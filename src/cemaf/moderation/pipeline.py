"""
Moderation pipeline for chaining pre-flight and post-flight gates.

Provides a complete moderation solution with event integration
for observability and convenient methods for input/output checking.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from cemaf.moderation.gates import PostFlightGate, PreFlightGate
from cemaf.moderation.protocols import ModerationResult


class ModerationPipeline:
    """
    Complete moderation pipeline with pre-flight and post-flight gates.

    Chains pre-flight checks (for inputs) and post-flight checks (for outputs)
    into a unified moderation workflow. Integrates with EventBus for emitting
    moderation events for observability.

    Example:
        >>> pre_gate = PreFlightGate([KeywordRule(), PIIRule()])
        >>> post_gate = PostFlightGate([ToxicityRule()])
        >>> pipeline = ModerationPipeline(
        ...     pre_flight=pre_gate,
        ...     post_flight=post_gate,
        ...     event_bus=my_event_bus,
        ... )
        >>> # Check input before processing
        >>> result = await pipeline.check_input(user_message)
        >>> if not result.allowed:
        ...     raise ContentBlockedError(result.violations)
        >>> # Or wrap entire execution
        >>> mod_result, output = await pipeline.wrap_execution(
        ...     content=user_message,
        ...     executor=my_llm_call,
        ... )
    """

    def __init__(
        self,
        pre_flight: PreFlightGate | None = None,
        post_flight: PostFlightGate | None = None,
        event_bus: EventBus | None = None,  # noqa: F821
        name: str = "moderation_pipeline",
    ) -> None:
        """
        Initialize the moderation pipeline.

        Args:
            pre_flight: Gate for checking inputs before processing.
            post_flight: Gate for checking outputs after processing.
            event_bus: Optional event bus for emitting moderation events.
            name: Unique identifier for this pipeline.
        """
        self._pre_flight = pre_flight
        self._post_flight = post_flight
        self._event_bus = event_bus
        self._name = name

    @property
    def name(self) -> str:
        """Unique identifier for this pipeline."""
        return self._name

    @property
    def pre_flight(self) -> PreFlightGate | None:
        """The pre-flight gate for input moderation."""
        return self._pre_flight

    @property
    def post_flight(self) -> PostFlightGate | None:
        """The post-flight gate for output moderation."""
        return self._post_flight

    @property
    def event_bus(self) -> EventBus | None:  # noqa: F821
        """The event bus for emitting moderation events."""
        return self._event_bus

    async def check_input(
        self,
        content: Any,
        context: Context | None = None,  # noqa: F821
    ) -> ModerationResult:
        """
        Run pre-flight moderation on input.

        Applies the pre-flight gate to check input content before it is
        processed by the system. Emits moderation events if an event bus
        is configured.

        Events emitted:
            - moderation.check.started: When check begins
            - moderation.check.passed: When content passes moderation
            - moderation.check.blocked: When content is blocked

        Args:
            content: The input content to moderate.
            context: Optional context for moderation decisions.

        Returns:
            ModerationResult with the moderation decision and any violations.
        """
        # Emit start event
        self._emit_event(
            "moderation.check.started",
            {
                "pipeline": self._name,
                "phase": "pre_flight",
                "gate": self._pre_flight.name if self._pre_flight else None,
            },
        )

        # If no pre-flight gate, pass through
        if self._pre_flight is None:
            result = ModerationResult.success()
            self._emit_event(
                "moderation.check.passed",
                {
                    "pipeline": self._name,
                    "phase": "pre_flight",
                    "gate": None,
                    "reason": "no_gate_configured",
                },
            )
            return result

        # Run the pre-flight check
        result = await self._pre_flight.check(content, context)

        # Emit result event
        if result.allowed:
            self._emit_event(
                "moderation.check.passed",
                {
                    "pipeline": self._name,
                    "phase": "pre_flight",
                    "gate": self._pre_flight.name,
                    "warnings_count": len(result.violations),
                    "metadata": result.metadata,
                },
            )
        else:
            self._emit_event(
                "moderation.check.blocked",
                {
                    "pipeline": self._name,
                    "phase": "pre_flight",
                    "gate": self._pre_flight.name,
                    "violations_count": len(result.violations),
                    "violation_codes": [v.code for v in result.violations],
                    "metadata": result.metadata,
                },
            )

        return result

    async def check_output(
        self,
        content: Any,
        context: Context | None = None,  # noqa: F821
    ) -> ModerationResult:
        """
        Run post-flight moderation on output.

        Applies the post-flight gate to check output content after it has
        been generated by the system. Emits moderation events if an event
        bus is configured.

        Events emitted:
            - moderation.check.started: When check begins
            - moderation.check.passed: When content passes moderation
            - moderation.check.blocked: When content is blocked

        Args:
            content: The output content to moderate.
            context: Optional context for moderation decisions.

        Returns:
            ModerationResult with the moderation decision and any violations.
        """
        # Emit start event
        self._emit_event(
            "moderation.check.started",
            {
                "pipeline": self._name,
                "phase": "post_flight",
                "gate": self._post_flight.name if self._post_flight else None,
            },
        )

        # If no post-flight gate, pass through
        if self._post_flight is None:
            result = ModerationResult.success()
            self._emit_event(
                "moderation.check.passed",
                {
                    "pipeline": self._name,
                    "phase": "post_flight",
                    "gate": None,
                    "reason": "no_gate_configured",
                },
            )
            return result

        # Run the post-flight check
        result = await self._post_flight.check(content, context)

        # Emit result event
        if result.allowed:
            self._emit_event(
                "moderation.check.passed",
                {
                    "pipeline": self._name,
                    "phase": "post_flight",
                    "gate": self._post_flight.name,
                    "warnings_count": len(result.violations),
                    "has_redacted_content": result.redacted_content is not None,
                    "metadata": result.metadata,
                },
            )
        else:
            self._emit_event(
                "moderation.check.blocked",
                {
                    "pipeline": self._name,
                    "phase": "post_flight",
                    "gate": self._post_flight.name,
                    "violations_count": len(result.violations),
                    "violation_codes": [v.code for v in result.violations],
                    "metadata": result.metadata,
                },
            )

        return result

    async def wrap_execution(
        self,
        content: Any,
        executor: Callable[..., Awaitable[Any]],
        context: Context | None = None,  # noqa: F821
        **executor_kwargs: Any,
    ) -> tuple[ModerationResult, Any | None]:
        """
        Wrap an execution with pre and post-flight moderation.

        Provides a complete moderation workflow:
        1. Run pre-flight check on input content
        2. If pre-flight passes, execute the provided callable
        3. Run post-flight check on the execution result
        4. Return the final moderation result and execution output

        Args:
            content: The input content to moderate and process.
            executor: Async callable to execute if pre-flight passes.
            context: Optional context for moderation decisions.
            **executor_kwargs: Additional keyword arguments to pass to executor.

        Returns:
            Tuple of (final_moderation_result, execution_result_or_none).
            - If pre-flight blocks: (blocked_result, None)
            - If post-flight blocks: (blocked_result, None)
            - If all passes: (passed_result, executor_result)
        """
        # Emit pipeline start event
        self._emit_event(
            "moderation.pipeline.started",
            {
                "pipeline": self._name,
                "has_pre_flight": self._pre_flight is not None,
                "has_post_flight": self._post_flight is not None,
            },
        )

        # Step 1: Pre-flight check
        pre_result = await self.check_input(content, context)
        if not pre_result.allowed:
            self._emit_event(
                "moderation.pipeline.blocked",
                {
                    "pipeline": self._name,
                    "blocked_at": "pre_flight",
                    "violations_count": len(pre_result.violations),
                },
            )
            return pre_result, None

        # Step 2: Execute the callable
        try:
            self._emit_event(
                "moderation.execution.started",
                {
                    "pipeline": self._name,
                },
            )
            execution_result = await executor(**executor_kwargs)
            self._emit_event(
                "moderation.execution.completed",
                {
                    "pipeline": self._name,
                },
            )
        except Exception as e:
            self._emit_event(
                "moderation.execution.failed",
                {
                    "pipeline": self._name,
                    "error": str(e),
                    "error_type": type(e).__name__,
                },
            )
            raise

        # Step 3: Post-flight check
        post_result = await self.check_output(execution_result, context)
        if not post_result.allowed:
            self._emit_event(
                "moderation.pipeline.blocked",
                {
                    "pipeline": self._name,
                    "blocked_at": "post_flight",
                    "violations_count": len(post_result.violations),
                },
            )
            return post_result, None

        # Step 4: All checks passed
        self._emit_event(
            "moderation.pipeline.completed",
            {
                "pipeline": self._name,
                "pre_flight_warnings": len(pre_result.violations),
                "post_flight_warnings": len(post_result.violations),
            },
        )

        # Combine violations from both phases
        all_violations = pre_result.violations + post_result.violations
        combined_metadata = {
            "pipeline": self._name,
            "pre_flight_metadata": pre_result.metadata,
            "post_flight_metadata": post_result.metadata,
        }

        # Create final result
        if all_violations:
            final_result = ModerationResult.with_warnings(
                violations=all_violations,
                redacted_content=post_result.redacted_content,
                metadata=combined_metadata,
            )
        else:
            final_result = ModerationResult.success()

        # Return redacted content if available, otherwise the original result
        output = (
            post_result.redacted_content if post_result.redacted_content is not None else execution_result
        )
        return final_result, output

    def _emit_event(self, event_type: str, payload: dict[str, Any]) -> None:
        """
        Emit event if event_bus is configured.

        Creates and publishes an event to the event bus. This is a fire-and-forget
        operation - any errors during event publishing are silently ignored.

        Args:
            event_type: The type of event (e.g., "moderation.check.started").
            payload: The event payload data.
        """
        if self._event_bus is None:
            return

        # Import Event here to avoid circular imports
        from cemaf.events.protocols import Event

        event = Event.create(
            type=event_type,
            payload=payload,
            source=self._name,
        )

        # Use asyncio to schedule the publish without blocking
        import asyncio

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._event_bus.publish(event))
        except RuntimeError:
            # No running loop - skip event emission
            pass

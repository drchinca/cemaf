"""Helpers for recording skill/tool invocations into RunLogger."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any

from cemaf.observability.run_logger import RunLogger, ToolCall


async def record_tool_call[OutputT](
    *,
    run_logger: RunLogger | None,
    tool_id: str,
    input_payload: dict[str, Any],
    executor: Callable[[], Awaitable[OutputT]],
    node_id: str | None = None,
    agent_id: str | None = None,
    correlation_id: str = "",
) -> OutputT:
    """Execute ``executor`` and record a ToolCall with timing and outcome."""
    if run_logger is None:
        return await executor()

    start_ns = time.perf_counter_ns()
    try:
        output = await executor()
    except Exception as exc:
        duration_ms = (time.perf_counter_ns() - start_ns) / 1_000_000
        run_logger.record_tool_call(
            ToolCall(
                tool_id=tool_id,
                input=input_payload,
                output={},
                duration_ms=duration_ms,
                success=False,
                error=str(exc),
                node_id=node_id,
                agent_id=agent_id,
                correlation_id=correlation_id,
            )
        )
        raise

    duration_ms = (time.perf_counter_ns() - start_ns) / 1_000_000
    run_logger.record_tool_call(
        ToolCall(
            tool_id=tool_id,
            input=input_payload,
            output=_serialize_output(output),
            duration_ms=duration_ms,
            success=True,
            node_id=node_id,
            agent_id=agent_id,
            correlation_id=correlation_id,
        )
    )
    return output


def _serialize_output(output: Any) -> dict[str, Any]:
    if hasattr(output, "model_dump"):
        dumped = output.model_dump(mode="json")
        if isinstance(dumped, dict):
            return dumped
        return {"value": dumped}
    if isinstance(output, dict):
        return output
    return {"value": str(output)}

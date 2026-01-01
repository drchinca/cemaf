"""
Factory functions for replay components.

Provides convenient ways to create replayer instances
with sensible defaults while maintaining dependency injection principles.
"""

from collections.abc import Callable
from typing import Any

from cemaf.core.types import JSON
from cemaf.observability.run_logger import RunRecord
from cemaf.replay.replayer import Replayer


def create_replayer(
    record: RunRecord,
    mock_tools: dict[str, JSON] | None = None,
    tool_executors: dict[str, Callable[..., Any]] | None = None,
) -> Replayer:
    """
    Factory for Replayer with sensible defaults.

    Args:
        record: The RunRecord to replay
        mock_tools: Mock tool outputs for MOCK_TOOLS mode (optional)
        tool_executors: Real tool executors for LIVE_TOOLS mode (optional)

    Returns:
        Configured Replayer instance

    Example:
        # Basic replay (PATCH_ONLY mode)
        replayer = create_replayer(record=run_record)
        result = await replayer.replay()

        # With mocked tools
        mocks = {"web_search": {"results": [...]}}
        replayer = create_replayer(record=run_record, mock_tools=mocks)
        result = await replayer.replay(mode=ReplayMode.MOCK_TOOLS)

        # With real tool executors
        executors = {"calculator": my_calculator_fn}
        replayer = create_replayer(record=run_record, tool_executors=executors)
        result = await replayer.replay(mode=ReplayMode.LIVE_TOOLS)
    """
    return Replayer(
        record=record,
        mock_tools=mock_tools,
        tool_executors=tool_executors,
    )

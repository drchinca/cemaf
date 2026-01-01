"""
Deterministic replay executor for agent runs.

This module provides:
- Replayer: Replay recorded runs with mocked tool outputs
- ReplayMode: Control how the replay behaves
- ReplayResult: Result of a replay operation
"""

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any

from cemaf.context.context import Context
from cemaf.core.types import JSON
from cemaf.core.utils import utc_now
from cemaf.observability.run_logger import RunRecord, ToolCall


class ReplayMode(str, Enum):
    """Mode for replaying runs."""

    # Apply recorded patches exactly
    PATCH_ONLY = "patch_only"

    # Re-execute tools with mocked outputs
    MOCK_TOOLS = "mock_tools"

    # Re-execute tools with real implementations (for validation)
    LIVE_TOOLS = "live_tools"


@dataclass(frozen=True)
class ReplayResult:
    """Result of a replay operation."""

    success: bool
    final_context: Context
    mode: ReplayMode
    duration_ms: float = 0.0
    patches_applied: int = 0
    tools_replayed: int = 0
    divergences: tuple[str, ...] = ()  # Any differences from original
    error: str | None = None

    @classmethod
    def ok(
        cls,
        final_context: Context,
        mode: ReplayMode,
        duration_ms: float = 0.0,
        patches_applied: int = 0,
        tools_replayed: int = 0,
        divergences: tuple[str, ...] = (),
    ) -> ReplayResult:
        """Create a successful replay result."""
        return cls(
            success=True,
            final_context=final_context,
            mode=mode,
            duration_ms=duration_ms,
            patches_applied=patches_applied,
            tools_replayed=tools_replayed,
            divergences=divergences,
        )

    @classmethod
    def fail(
        cls,
        error: str,
        final_context: Context,
        mode: ReplayMode,
    ) -> ReplayResult:
        """Create a failed replay result."""
        return cls(
            success=False,
            final_context=final_context,
            mode=mode,
            error=error,
        )


class Replayer:
    """
    Deterministic replay executor for agent runs.

    Given a RunRecord, replays the run to reproduce the final context.
    Supports multiple replay modes:
    - PATCH_ONLY: Just apply recorded patches (fastest, always deterministic)
    - MOCK_TOOLS: Re-execute tools with mocked outputs (validates logic)
    - LIVE_TOOLS: Re-execute with real tools (validates real behavior)

    Example:
        # Replay by applying patches only
        replayer = Replayer(record)
        result = await replayer.replay()

        # Replay with mocked tool outputs
        replayer = Replayer(record, mock_tools={"web_search": {"results": [...]}})
        result = await replayer.replay(mode=ReplayMode.MOCK_TOOLS)

        # Verify final context matches
        assert result.final_context == record.final_context
    """

    def __init__(
        self,
        record: RunRecord,
        mock_tools: dict[str, JSON] | None = None,
        tool_executors: dict[str, Callable[..., Any]] | None = None,
    ) -> None:
        """
        Initialize replayer.

        Args:
            record: The RunRecord to replay
            mock_tools: Dict mapping tool_id to mocked output (for MOCK_TOOLS mode)
            tool_executors: Dict mapping tool_id to executor function (for LIVE_TOOLS mode)
        """
        self._record = record
        self._mock_tools = mock_tools or {}
        self._tool_executors = tool_executors or {}

        # Build tool call index for MOCK_TOOLS mode
        self._tool_call_index: dict[str, list[ToolCall]] = {}
        for call in record.tool_calls:
            if call.tool_id not in self._tool_call_index:
                self._tool_call_index[call.tool_id] = []
            self._tool_call_index[call.tool_id].append(call)

        # Track which calls have been replayed
        self._replay_counters: dict[str, int] = {}

    async def replay(
        self,
        mode: ReplayMode = ReplayMode.PATCH_ONLY,
        initial_context: Context | None = None,
    ) -> ReplayResult:
        """
        Replay the recorded run.

        Args:
            mode: Replay mode to use
            initial_context: Override initial context (defaults to record's initial)

        Returns:
            ReplayResult with final context and statistics
        """
        start_time = utc_now()
        context = initial_context or self._record.initial_context or Context()

        try:
            if mode == ReplayMode.PATCH_ONLY:
                result = await self._replay_patches(context)
            elif mode == ReplayMode.MOCK_TOOLS:
                result = await self._replay_with_mocks(context)
            elif mode == ReplayMode.LIVE_TOOLS:
                result = await self._replay_with_live_tools(context)
            else:
                result = await self._replay_patches(context)

            duration_ms = (utc_now() - start_time).total_seconds() * 1000
            return ReplayResult(
                success=result.success,
                final_context=result.final_context,
                mode=mode,
                duration_ms=duration_ms,
                patches_applied=result.patches_applied,
                tools_replayed=result.tools_replayed,
                divergences=result.divergences,
                error=result.error,
            )

        except Exception as e:
            return ReplayResult.fail(
                error=str(e),
                final_context=context,
                mode=mode,
            )

    async def _replay_patches(self, context: Context) -> ReplayResult:
        """Replay by applying patches only."""
        patch_log = self._record.get_patch_log()
        final_context = patch_log.replay(context)

        return ReplayResult.ok(
            final_context=final_context,
            mode=ReplayMode.PATCH_ONLY,
            patches_applied=len(patch_log),
        )

    async def _replay_with_mocks(self, context: Context) -> ReplayResult:
        """Replay with mocked tool outputs."""
        self._replay_counters = {}
        divergences: list[str] = []
        tools_replayed = 0

        # Apply patches, but verify tool outputs match mocks
        for patch in self._record.patches:
            context = context.apply(patch)

            # If this patch came from a tool, check the mock
            if patch.source_id and patch.source_id in self._mock_tools:
                expected = self._mock_tools[patch.source_id]
                # Record any divergence
                if patch.value != expected:
                    divergences.append(f"Tool '{patch.source_id}' mock differs from recorded value")

            tools_replayed += 1

        return ReplayResult.ok(
            final_context=context,
            mode=ReplayMode.MOCK_TOOLS,
            patches_applied=len(self._record.patches),
            tools_replayed=tools_replayed,
            divergences=tuple(divergences),
        )

    async def _replay_with_live_tools(self, context: Context) -> ReplayResult:
        """Replay with live tool execution."""
        divergences: list[str] = []
        tools_replayed = 0

        for tool_call in self._record.tool_calls:
            tool_id = tool_call.tool_id

            if tool_id not in self._tool_executors:
                divergences.append(f"No executor for tool '{tool_id}'")
                continue

            # Execute the tool
            executor = self._tool_executors[tool_id]
            try:
                result = await executor(**tool_call.input)

                # Compare with recorded output
                if result != tool_call.output:
                    divergences.append(f"Tool '{tool_id}' output differs from recorded")

                tools_replayed += 1

            except Exception as e:
                divergences.append(f"Tool '{tool_id}' execution failed: {e}")

        # Apply all patches to get final context
        patch_log = self._record.get_patch_log()
        final_context = patch_log.replay(context)

        return ReplayResult.ok(
            final_context=final_context,
            mode=ReplayMode.LIVE_TOOLS,
            patches_applied=len(patch_log),
            tools_replayed=tools_replayed,
            divergences=tuple(divergences),
        )

    def get_tool_call(self, tool_id: str, call_index: int = 0) -> ToolCall | None:
        """
        Get a specific tool call from the record.

        Args:
            tool_id: The tool ID
            call_index: Which call (0-indexed) if tool was called multiple times

        Returns:
            ToolCall or None if not found
        """
        calls = self._tool_call_index.get(tool_id, [])
        if call_index < len(calls):
            return calls[call_index]
        return None

    def get_next_tool_output(self, tool_id: str) -> JSON | None:
        """
        Get the next recorded output for a tool.

        Useful when replaying tools in order.

        Args:
            tool_id: The tool ID

        Returns:
            The recorded output or None if exhausted
        """
        counter = self._replay_counters.get(tool_id, 0)
        call = self.get_tool_call(tool_id, counter)

        if call:
            self._replay_counters[tool_id] = counter + 1
            return call.output

        return None

    def verify_determinism(self, replayed_context: Context) -> tuple[bool, list[str]]:
        """
        Verify the replayed context matches the recorded final context.

        Args:
            replayed_context: The context from replay

        Returns:
            Tuple of (is_deterministic, list of differences)
        """
        if not self._record.final_context:
            return True, []

        recorded = self._record.final_context
        differences: list[str] = []

        # Generate diff
        patches = replayed_context.diff(recorded)

        for patch in patches:
            differences.append(f"{patch.operation.value} at '{patch.path}': {patch.value}")

        return len(differences) == 0, differences

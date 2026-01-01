"""Tests for replay system."""

import pytest

from cemaf.context.context import Context
from cemaf.context.patch import ContextPatch
from cemaf.observability.run_logger import RunRecord, ToolCall
from cemaf.replay.replayer import Replayer, ReplayMode, ReplayResult


class TestReplayResult:
    """Tests for ReplayResult."""

    def test_ok_result(self) -> None:
        """Test creating successful result."""
        ctx = Context(data={"result": 42})
        result = ReplayResult.ok(
            final_context=ctx,
            mode=ReplayMode.PATCH_ONLY,
            patches_applied=5,
        )

        assert result.success is True
        assert result.patches_applied == 5
        assert result.error is None

    def test_fail_result(self) -> None:
        """Test creating failed result."""
        ctx = Context()
        result = ReplayResult.fail(
            error="Replay failed",
            final_context=ctx,
            mode=ReplayMode.MOCK_TOOLS,
        )

        assert result.success is False
        assert result.error == "Replay failed"


class TestReplayer:
    """Tests for Replayer."""

    def test_replay_patches_only(self) -> None:
        """Test replaying with patches only."""
        # Create a record with patches
        initial_ctx = Context()
        record = RunRecord(
            run_id="run-123",
            initial_context=initial_ctx,
            final_context=Context(data={"a": 1, "b": 2}),
        )
        record.patches.append(ContextPatch.set("a", 1))
        record.patches.append(ContextPatch.set("b", 2))

        Replayer(record)

    @pytest.mark.asyncio
    async def test_replay_produces_correct_context(self) -> None:
        """Test that replay produces the correct final context."""
        initial_ctx = Context()
        record = RunRecord(
            run_id="run-123",
            initial_context=initial_ctx,
        )
        record.patches.append(ContextPatch.set("user.name", "Alice"))
        record.patches.append(ContextPatch.set("user.age", 30))

        replayer = Replayer(record)
        result = await replayer.replay(mode=ReplayMode.PATCH_ONLY)

        assert result.success is True
        assert result.final_context.get("user.name") == "Alice"
        assert result.final_context.get("user.age") == 30
        assert result.patches_applied == 2

    @pytest.mark.asyncio
    async def test_replay_with_custom_initial_context(self) -> None:
        """Test replay with custom initial context."""
        record = RunRecord(run_id="run-123")
        record.patches.append(ContextPatch.set("count", 10))

        replayer = Replayer(record)
        custom_initial = Context(data={"existing": "value"})
        result = await replayer.replay(
            mode=ReplayMode.PATCH_ONLY,
            initial_context=custom_initial,
        )

        assert result.final_context.get("existing") == "value"
        assert result.final_context.get("count") == 10

    def test_get_tool_call(self) -> None:
        """Test getting specific tool call."""
        record = RunRecord(run_id="run-123")
        record.tool_calls.append(ToolCall(tool_id="tool_a", input={"x": 1}, output={"y": 1}))
        record.tool_calls.append(ToolCall(tool_id="tool_a", input={"x": 2}, output={"y": 2}))
        record.tool_calls.append(ToolCall(tool_id="tool_b", input={}, output={}))

        replayer = Replayer(record)

        # Get first call for tool_a
        call = replayer.get_tool_call("tool_a", 0)
        assert call is not None
        assert call.input == {"x": 1}

        # Get second call for tool_a
        call = replayer.get_tool_call("tool_a", 1)
        assert call is not None
        assert call.input == {"x": 2}

        # Get call for tool_b
        call = replayer.get_tool_call("tool_b", 0)
        assert call is not None

        # Non-existent call
        call = replayer.get_tool_call("tool_c", 0)
        assert call is None

    def test_get_next_tool_output(self) -> None:
        """Test getting next tool output in sequence."""
        record = RunRecord(run_id="run-123")
        record.tool_calls.append(ToolCall(tool_id="tool_a", input={}, output={"result": 1}))
        record.tool_calls.append(ToolCall(tool_id="tool_a", input={}, output={"result": 2}))

        replayer = Replayer(record)

        # Get outputs in sequence
        output1 = replayer.get_next_tool_output("tool_a")
        assert output1 == {"result": 1}

        output2 = replayer.get_next_tool_output("tool_a")
        assert output2 == {"result": 2}

        # Exhausted
        output3 = replayer.get_next_tool_output("tool_a")
        assert output3 is None

    def test_verify_determinism_matching(self) -> None:
        """Test verifying determinism when contexts match."""
        final_ctx = Context(data={"result": 42})
        record = RunRecord(
            run_id="run-123",
            final_context=final_ctx,
        )

        replayer = Replayer(record)
        is_deterministic, differences = replayer.verify_determinism(final_ctx)

        assert is_deterministic is True
        assert len(differences) == 0

    def test_verify_determinism_different(self) -> None:
        """Test verifying determinism when contexts differ."""
        recorded_ctx = Context(data={"result": 42})
        replayed_ctx = Context(data={"result": 43})
        record = RunRecord(
            run_id="run-123",
            final_context=recorded_ctx,
        )

        replayer = Replayer(record)
        is_deterministic, differences = replayer.verify_determinism(replayed_ctx)

        assert is_deterministic is False
        assert len(differences) > 0

    @pytest.mark.asyncio
    async def test_replay_error_handling(self) -> None:
        """Test error handling during replay."""
        # Create an invalid record
        record = RunRecord(run_id="run-123")

        replayer = Replayer(record)
        # This should succeed with empty patches
        result = await replayer.replay(mode=ReplayMode.PATCH_ONLY)

        assert result.success is True
        assert result.patches_applied == 0

    @pytest.mark.asyncio
    async def test_replay_modes(self) -> None:
        """Test different replay modes."""
        record = RunRecord(run_id="run-123")
        record.patches.append(ContextPatch.set("key", "value"))

        replayer = Replayer(record)

        # PATCH_ONLY mode
        result = await replayer.replay(mode=ReplayMode.PATCH_ONLY)
        assert result.mode == ReplayMode.PATCH_ONLY

        # MOCK_TOOLS mode
        result = await replayer.replay(mode=ReplayMode.MOCK_TOOLS)
        assert result.mode == ReplayMode.MOCK_TOOLS

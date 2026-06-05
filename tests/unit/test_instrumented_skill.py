"""Tests for instrumented skill/tool call recording."""

import pytest

from cemaf.observability.instrumented_skill import record_tool_call
from cemaf.observability.run_logger import InMemoryRunLogger


@pytest.mark.unit
@pytest.mark.asyncio
async def test_record_tool_call_success() -> None:
    logger = InMemoryRunLogger()
    logger.start_run(run_id="run-1", dag_name="test")

    async def _execute() -> dict[str, str]:
        return {"status": "ok"}

    result = await record_tool_call(
        run_logger=logger,
        tool_id="write_file",
        input_payload={"path": "a.py"},
        executor=_execute,
        node_id="step-1",
        agent_id="coding_agent",
    )

    assert result == {"status": "ok"}
    record = logger.get_current_record()
    assert record is not None
    assert len(record.tool_calls) == 1
    assert record.tool_calls[0].tool_id == "write_file"
    assert record.tool_calls[0].success is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_record_tool_call_failure() -> None:
    logger = InMemoryRunLogger()
    logger.start_run(run_id="run-1", dag_name="test")

    async def _execute() -> None:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        await record_tool_call(
            run_logger=logger,
            tool_id="shell",
            input_payload={"command": "false"},
            executor=_execute,
        )

    record = logger.get_current_record()
    assert record is not None
    assert record.tool_calls[0].success is False
    assert record.tool_calls[0].error == "boom"

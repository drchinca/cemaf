"""Integration tests for dreaming-mode scheduling via the plain AsyncJobExecutor."""

import pytest

from cemaf.core.enums import MemoryScope
from cemaf.memory.factories import create_memory_manager
from cemaf.meta.dreaming import DreamingMode
from cemaf.scheduler.executor import AsyncJobExecutor


@pytest.mark.asyncio
async def test_dreaming_mode_runs_under_async_job_executor() -> None:
    memory_manager = create_memory_manager()
    await memory_manager.remember(
        scope=MemoryScope.PROJECT,
        key="fact",
        value={"summary": "A durable project fact."},
    )

    mode = DreamingMode(min_sessions=1, use_lock_gate=False)
    handle = mode.build(memory_manager=memory_manager, current_sessions=1)

    executor = AsyncJobExecutor(max_concurrent=2)
    executor.add_job(handle.definition.to_job(handler=handle.handler))

    result = await executor.run_now(handle.definition.id)

    assert result.status.value == "completed"
    assert isinstance(result.result, dict)
    assert result.result["consolidated_count"] >= 1

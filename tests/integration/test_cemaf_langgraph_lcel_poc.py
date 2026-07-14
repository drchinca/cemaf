"""Integration proof for CEMAF outer orchestration over LangGraph/LCEL."""

from __future__ import annotations

import pytest

pytest.importorskip("langchain_core")
pytest.importorskip("langgraph")

from examples.app_shapes.cemaf_langgraph_lcel_poc import run_poc


@pytest.mark.asyncio
async def test_cemaf_outer_runtime_wraps_langgraph_lcel_adapter() -> None:
    summary = await run_poc()

    assert summary["success"] is True
    assert summary["decision"]["adopt_cemaf_outer_orchestration"] is True
    assert summary["events"]["has_task_events"] is True
    assert summary["events"]["has_checkpoints"] == 2
    assert summary["audit_log"]["patch_paths"] == ["studio_assessment", "decision"]
    assert summary["replay"]["success"] is True
    assert summary["replay"]["matches_final_context"] is True

"""Tests for dreaming-mode composition."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from cemaf.core.enums import MemoryScope
from cemaf.meta.dreaming import DreamingMode
from cemaf.scheduler.nightshift import NightShiftWindow


class FakeMemoryManager:
    def __init__(self, *, items: dict[str, dict[str, Any]] | None = None) -> None:
        self._items = items or {}

    async def remember(
        self,
        scope: MemoryScope,
        key: str,
        value: Any,
        *,
        confidence: float = 1.0,
        content_for_embedding: str | None = None,
    ) -> Any:
        return {"scope": scope.value, "key": key, "value": value}

    async def recall(self, query: Any) -> tuple[Any, ...]:
        from cemaf.core.enums import MemoryScope as _Scope
        from cemaf.core.types import Confidence
        from cemaf.memory.base import MemoryItem
        from cemaf.memory.semantic import MemorySearchResult

        results = []
        for rank, raw in enumerate(self._items.values()):
            item = MemoryItem(
                scope=_Scope.PROJECT,
                key=str(raw["key"]),
                value=raw["value"],
                confidence=Confidence(float(raw.get("confidence", 1.0))),
            )
            results.append(MemorySearchResult(item=item, similarity=1.0, combined_score=1.0, rank=rank))
        return tuple(results)

    async def recall_by_key(self, scope: MemoryScope, key: str) -> Any | None:
        return self._items.get(key)

    async def forget(self, scope: MemoryScope, key: str) -> bool:
        return key in self._items

    async def start_episode(self, session_id: str) -> Any:
        return {"id": session_id}

    async def record_event(self, episode_id: str, event: Any) -> None:
        return None

    async def end_episode(self, episode_id: str) -> Any:
        return {"id": episode_id}

    async def get_recent_history(self, session_id: str, *, limit: int = 20) -> tuple[Any, ...]:
        return ()

    async def cleanup(self) -> int:
        return 0


class TestDreamingMode:
    def test_create_job_definition_wraps_nightshift_trigger(self) -> None:
        mode = DreamingMode(
            nightshift=NightShiftWindow(start_hour=1, end_hour=5, timezone_name="UTC"),
        )

        definition = mode.create_job_definition()

        assert definition.kind.value == "dream"
        assert "nightshift" in definition.tags
        assert definition.trigger.name.endswith(".nightshift")

    @pytest.mark.asyncio
    async def test_build_runs_dream_agent_and_resets_session_gate(self) -> None:
        mode = DreamingMode(
            min_interval=timedelta(hours=1),
            min_sessions=2,
            use_lock_gate=False,
        )
        handle = mode.build(
            memory_manager=FakeMemoryManager(
                items={
                    "fact": {"key": "fact", "value": "data"},
                    "fact_dup": {"key": "fact_dup", "value": "data"},
                }
            ),  # type: ignore[arg-type]
            current_sessions=2,
            last_execution=datetime(2026, 6, 9, 0, 0, tzinfo=UTC),
        )

        output = await handle.handler()

        # One real duplicate ("data" appears twice) was merged away.
        assert output["consolidated_count"] == 1
        assert handle.session_gate is not None
        assert handle.session_gate._current_count == 0

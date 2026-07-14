"""Tests for nightshift scheduling primitives."""

from datetime import UTC, datetime, timedelta

import pytest

from cemaf.scheduler.nightshift import NightShiftGate, NightShiftTrigger, NightShiftWindow
from cemaf.scheduler.triggers import IntervalTrigger


class TestNightShiftWindow:
    def test_contains_within_same_day_window(self) -> None:
        window = NightShiftWindow(start_hour=1, end_hour=5, timezone_name="UTC")

        assert window.contains(datetime(2026, 6, 10, 2, 0, tzinfo=UTC)) is True
        assert window.contains(datetime(2026, 6, 10, 5, 0, tzinfo=UTC)) is False

    def test_contains_within_overnight_window(self) -> None:
        window = NightShiftWindow(start_hour=22, end_hour=2, timezone_name="UTC")

        assert window.contains(datetime(2026, 6, 10, 23, 30, tzinfo=UTC)) is True
        assert window.contains(datetime(2026, 6, 11, 1, 30, tzinfo=UTC)) is True
        assert window.contains(datetime(2026, 6, 10, 12, 0, tzinfo=UTC)) is False


class TestNightShiftGate:
    @pytest.mark.asyncio
    async def test_denies_outside_window(self) -> None:
        gate = NightShiftGate(
            window=NightShiftWindow(start_hour=1, end_hour=5, timezone_name="UTC"),
            now_provider=lambda: datetime(2026, 6, 10, 12, 0, tzinfo=UTC),
        )

        result = await gate.evaluate()

        assert result.passed is False
        assert "Outside nightshift window" in result.reason


class TestNightShiftTrigger:
    def test_should_run_requires_window_and_base_trigger(self) -> None:
        base_trigger = IntervalTrigger(hours=1)
        window = NightShiftWindow(start_hour=1, end_hour=5, timezone_name="UTC")
        trigger = NightShiftTrigger(base_trigger=base_trigger, window=window)

        inside_window = datetime(2026, 6, 10, 2, 0, tzinfo=UTC)
        outside_window = datetime(2026, 6, 10, 8, 0, tzinfo=UTC)

        assert trigger.should_run(inside_window) is True
        assert trigger.should_run(outside_window) is False

    def test_mark_run_propagates_to_base_trigger(self) -> None:
        base_trigger = IntervalTrigger(hours=1)
        window = NightShiftWindow(start_hour=0, end_hour=23, end_minute=59, timezone_name="UTC")
        trigger = NightShiftTrigger(base_trigger=base_trigger, window=window)
        now = datetime(2026, 6, 10, 2, 0, tzinfo=UTC)

        trigger.mark_run(now)

        assert base_trigger.next_run(now) == now + timedelta(hours=1)

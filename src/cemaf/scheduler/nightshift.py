"""Nightshift scheduling primitives for quiet-hours background work."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo

from cemaf.core.utils import utc_now
from cemaf.scheduler.gates import GateResult
from cemaf.scheduler.protocols import Trigger


@dataclass(frozen=True)
class NightShiftWindow:
    """A local-time window for low-priority background work."""

    start_hour: int = 1
    end_hour: int = 5
    timezone_name: str = "UTC"
    start_minute: int = 0
    end_minute: int = 0

    def __post_init__(self) -> None:
        for label, value, upper in (
            ("start_hour", self.start_hour, 23),
            ("end_hour", self.end_hour, 23),
            ("start_minute", self.start_minute, 59),
            ("end_minute", self.end_minute, 59),
        ):
            if value < 0 or value > upper:
                raise ValueError(f"{label} must be between 0 and {upper}")

    @property
    def tzinfo(self) -> ZoneInfo:
        """Resolve the configured IANA timezone."""
        return ZoneInfo(self.timezone_name)

    @property
    def start_time(self) -> time:
        """Window start in local wall-clock time."""
        return time(self.start_hour, self.start_minute)

    @property
    def end_time(self) -> time:
        """Window end in local wall-clock time."""
        return time(self.end_hour, self.end_minute)

    def describe(self) -> str:
        """Human-readable label for logs and operator messages."""
        return f"{self.start_time.strftime('%H:%M')}-{self.end_time.strftime('%H:%M')} {self.timezone_name}"

    def contains(self, when: datetime) -> bool:
        """Check whether a datetime falls inside the configured local window."""
        local = self._normalize(when).astimezone(self.tzinfo)
        current = local.timetz().replace(tzinfo=None)
        start = self.start_time
        end = self.end_time

        if start == end:
            return True
        if start < end:
            return start <= current < end
        return current >= start or current < end

    def _normalize(self, when: datetime) -> datetime:
        if when.tzinfo is None:
            return when.replace(tzinfo=UTC)
        return when


class NightShiftGate:
    """Execution gate that only opens within a nightshift window."""

    def __init__(
        self,
        *,
        window: NightShiftWindow,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self._window = window
        self._now = now_provider or utc_now

    @property
    def name(self) -> str:
        """Gate identifier."""
        return "nightshift_gate"

    async def evaluate(self) -> GateResult:
        """Allow execution only within the configured window."""
        now = self._now()
        if self._window.contains(now):
            return GateResult.allow(gate_name=self.name)
        return GateResult.deny(
            gate_name=self.name,
            reason=f"Outside nightshift window {self._window.describe()}",
        )


class NightShiftTrigger:
    """Wrap another trigger and only fire it inside a nightshift window."""

    def __init__(
        self,
        *,
        base_trigger: Trigger,
        window: NightShiftWindow,
        name: str | None = None,
        max_next_run_attempts: int = 1440,
    ) -> None:
        if max_next_run_attempts <= 0:
            raise ValueError("max_next_run_attempts must be positive")
        self._base = base_trigger
        self._window = window
        self._name = name or f"nightshift:{base_trigger.name}"
        self._max_attempts = max_next_run_attempts

    @property
    def name(self) -> str:
        """Trigger identifier."""
        return self._name

    @property
    def base_trigger(self) -> Trigger:
        """Underlying cadence trigger."""
        return self._base

    @property
    def window(self) -> NightShiftWindow:
        """Configured local window."""
        return self._window

    def next_run(self, after: datetime) -> datetime | None:
        """Find the next base-trigger fire that also lands inside the window."""
        candidate = self._base.next_run(after)
        attempts = 0
        while candidate is not None and attempts < self._max_attempts:
            if self._window.contains(candidate):
                return candidate
            candidate = self._base.next_run(candidate)
            attempts += 1
        return None

    def should_run(self, now: datetime) -> bool:
        """Only fire when both cadence and local window allow execution."""
        return self._window.contains(now) and self._base.should_run(now)

    def mark_run(self, at: datetime | None = None) -> None:
        """Propagate mark_run to stateful wrapped triggers when supported."""
        mark_run = getattr(self._base, "mark_run", None)
        if mark_run is None:
            return
        if at is None:
            mark_run()
            return
        mark_run(at)

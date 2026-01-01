"""
Trigger implementations.

Provides cron, interval, and one-time triggers.
"""

from datetime import datetime, timedelta


class CronTrigger:
    """
    Cron expression-based trigger.

    Supports standard 5-field cron expressions:
    minute hour day_of_month month day_of_week

    Note: This is a simplified implementation. For production use,
    consider using croniter library.
    """

    def __init__(self, expression: str, name: str | None = None) -> None:
        """
        Initialize cron trigger.

        Args:
            expression: Cron expression (e.g., "0 9 * * *" for daily 9am).
            name: Trigger name.
        """
        self._expression = expression
        self._name = name or f"cron:{expression}"
        self._fields = self._parse_expression(expression)

    @property
    def name(self) -> str:
        return self._name

    @property
    def expression(self) -> str:
        return self._expression

    def next_run(self, after: datetime) -> datetime | None:
        """
        Calculate next run time.

        Simple implementation - checks each minute for next 24 hours.
        For production, use a proper cron library.
        """
        current = after.replace(second=0, microsecond=0) + timedelta(minutes=1)
        end = after + timedelta(days=1)

        while current <= end:
            if self._matches(current):
                return current
            current += timedelta(minutes=1)

        return None

    def should_run(self, now: datetime) -> bool:
        """Check if should run at this time."""
        return self._matches(now)

    def _parse_expression(self, expression: str) -> tuple[set[int], ...]:
        """Parse cron expression into field sets."""
        parts = expression.strip().split()
        if len(parts) != 5:
            raise ValueError(f"Invalid cron expression: expected 5 fields, got {len(parts)}")

        ranges = [
            (0, 59),  # minute
            (0, 23),  # hour
            (1, 31),  # day of month
            (1, 12),  # month
            (0, 6),  # day of week (0=Sunday)
        ]

        fields = []
        for part, (min_val, max_val) in zip(parts, ranges, strict=False):
            fields.append(self._parse_field(part, min_val, max_val))

        return tuple(fields)

    def _parse_field(
        self,
        field: str,
        min_val: int,
        max_val: int,
    ) -> set[int]:
        """Parse a single cron field."""
        if field == "*":
            return set(range(min_val, max_val + 1))

        values: set[int] = set()

        for part in field.split(","):
            if "/" in part:
                range_part, step = part.split("/")
                step_val = int(step)
                if range_part == "*":
                    values.update(range(min_val, max_val + 1, step_val))
                else:
                    start, end = self._parse_range(range_part, min_val, max_val)
                    values.update(range(start, end + 1, step_val))
            elif "-" in part:
                start, end = self._parse_range(part, min_val, max_val)
                values.update(range(start, end + 1))
            else:
                values.add(int(part))

        return values

    def _parse_range(
        self,
        part: str,
        min_val: int,
        max_val: int,
    ) -> tuple[int, int]:
        """Parse a range (e.g., '1-5')."""
        if "-" in part:
            start, end = part.split("-")
            return int(start), int(end)
        val = int(part)
        return val, val

    def _matches(self, dt: datetime) -> bool:
        """Check if datetime matches the cron expression."""
        minute, hour, dom, month, dow = self._fields

        return (
            dt.minute in minute
            and dt.hour in hour
            and dt.day in dom
            and dt.month in month
            and dt.weekday() in self._convert_dow(dow)
        )

    def _convert_dow(self, dow: set[int]) -> set[int]:
        """Convert cron dow (0=Sun) to Python weekday (0=Mon)."""
        # Cron: 0=Sun, 1=Mon, ... 6=Sat
        # Python: 0=Mon, ... 6=Sun
        converted = set()
        for d in dow:
            if d == 0:
                converted.add(6)  # Sunday
            else:
                converted.add(d - 1)
        return converted


class IntervalTrigger:
    """
    Run at fixed intervals.
    """

    def __init__(
        self,
        seconds: int = 0,
        minutes: int = 0,
        hours: int = 0,
        name: str | None = None,
    ) -> None:
        """
        Initialize interval trigger.

        Args:
            seconds: Interval in seconds.
            minutes: Interval in minutes.
            hours: Interval in hours.
            name: Trigger name.
        """
        self._interval = timedelta(
            seconds=seconds,
            minutes=minutes,
            hours=hours,
        )

        if self._interval.total_seconds() <= 0:
            raise ValueError("Interval must be positive")

        self._name = name or f"interval:{self._interval}"
        self._last_run: datetime | None = None

    @property
    def name(self) -> str:
        return self._name

    @property
    def interval(self) -> timedelta:
        return self._interval

    def next_run(self, after: datetime) -> datetime | None:
        """Calculate next run time."""
        if self._last_run is None:
            return after
        return self._last_run + self._interval

    def should_run(self, now: datetime) -> bool:
        """Check if should run now."""
        if self._last_run is None:
            return True
        return now >= self._last_run + self._interval

    def mark_run(self, at: datetime | None = None) -> None:
        """Mark that the job has run."""
        self._last_run = at or datetime.now()


class OnceTrigger:
    """
    Run once at a specific time.
    """

    def __init__(
        self,
        run_at: datetime,
        name: str | None = None,
    ) -> None:
        """
        Initialize once trigger.

        Args:
            run_at: When to run.
            name: Trigger name.
        """
        self._run_at = run_at
        self._name = name or f"once:{run_at.isoformat()}"
        self._has_run = False

    @property
    def name(self) -> str:
        return self._name

    @property
    def run_at(self) -> datetime:
        return self._run_at

    def next_run(self, after: datetime) -> datetime | None:
        """Return run time if not yet run."""
        if self._has_run:
            return None
        if after >= self._run_at:
            return None
        return self._run_at

    def should_run(self, now: datetime) -> bool:
        """Check if should run now."""
        if self._has_run:
            return False
        return now >= self._run_at

    def mark_run(self) -> None:
        """Mark as run."""
        self._has_run = True


class ImmediateTrigger:
    """
    Run immediately (once).

    Useful for manual job execution or testing.
    """

    def __init__(self, name: str = "immediate") -> None:
        """Initialize immediate trigger."""
        self._name = name
        self._has_run = False

    @property
    def name(self) -> str:
        return self._name

    def next_run(self, after: datetime) -> datetime | None:
        """Return immediately if not run."""
        if self._has_run:
            return None
        return after

    def should_run(self, now: datetime) -> bool:
        """Always run if not yet run."""
        return not self._has_run

    def mark_run(self) -> None:
        """Mark as run."""
        self._has_run = True

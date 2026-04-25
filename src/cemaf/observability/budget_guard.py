"""Budget Guard - Enforces cost and token limits across DAG runs."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class AlertLevel(StrEnum):
    """Budget alert severity levels."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
    HALT = "halt"


@dataclass(frozen=True)
class BudgetAlert:
    """Immutable record of a budget threshold crossing."""

    level: AlertLevel
    utilization: float
    message: str


class BudgetGuard:
    """Enforces cost and token limits across a DAG run."""

    def __init__(
        self,
        *,
        max_cost_usd: float = 1.0,
        max_total_tokens: int = 500_000,
        warning_threshold: float = 0.7,
        critical_threshold: float = 0.9,
    ) -> None:
        """Initialize with cost/token limits and alert thresholds."""
        self._max_cost_usd = max_cost_usd
        self._max_total_tokens = max_total_tokens
        self._warning_threshold = warning_threshold
        self._critical_threshold = critical_threshold
        self._accumulated_cost_usd: float = 0.0
        self._accumulated_tokens: int = 0
        self._alerts: list[BudgetAlert] = []

    @property
    def accumulated_cost_usd(self) -> float:
        """Total cost accumulated so far."""
        return self._accumulated_cost_usd

    @property
    def accumulated_tokens(self) -> int:
        """Total tokens consumed so far."""
        return self._accumulated_tokens

    @property
    def cost_utilization(self) -> float:
        """Cost utilization as fraction (0.0 - 1.0)."""
        if self._max_cost_usd <= 0:
            return 1.0
        return min(self._accumulated_cost_usd / self._max_cost_usd, 1.0)

    @property
    def token_utilization(self) -> float:
        """Token utilization as fraction (0.0 - 1.0)."""
        if self._max_total_tokens <= 0:
            return 1.0
        return min(self._accumulated_tokens / self._max_total_tokens, 1.0)

    @property
    def alerts(self) -> tuple[BudgetAlert, ...]:
        """All alerts generated during this run."""
        return tuple(self._alerts)

    def record_usage(
        self,
        *,
        cost_usd: float = 0.0,
        tokens: int = 0,
    ) -> BudgetAlert | None:
        """Record token/cost usage and return alert if threshold crossed."""
        self._accumulated_cost_usd += cost_usd
        self._accumulated_tokens += tokens
        return self.check_budget()

    def check_budget(self) -> BudgetAlert | None:
        """Check current budget status and return highest-severity alert if any."""
        utilization = max(self.cost_utilization, self.token_utilization)

        if utilization >= 1.0:
            alert = BudgetAlert(
                level=AlertLevel.HALT,
                utilization=utilization,
                message=self._build_message(label="HALT", utilization=utilization),
            )
        elif utilization >= self._critical_threshold:
            alert = BudgetAlert(
                level=AlertLevel.CRITICAL,
                utilization=utilization,
                message=self._build_message(label="CRITICAL", utilization=utilization),
            )
        elif utilization >= self._warning_threshold:
            alert = BudgetAlert(
                level=AlertLevel.WARNING,
                utilization=utilization,
                message=self._build_message(label="WARNING", utilization=utilization),
            )
        else:
            return None

        self._alerts.append(alert)
        return alert

    def should_halt(self) -> bool:
        """Return True if budget is exhausted and execution should stop."""
        return self.cost_utilization >= 1.0 or self.token_utilization >= 1.0

    def to_dict(self) -> dict[str, Any]:
        """Serialize budget guard state."""
        return {
            "max_cost_usd": self._max_cost_usd,
            "max_total_tokens": self._max_total_tokens,
            "accumulated_cost_usd": self._accumulated_cost_usd,
            "accumulated_tokens": self._accumulated_tokens,
            "cost_utilization": self.cost_utilization,
            "token_utilization": self.token_utilization,
            "halted": self.should_halt(),
            "alert_count": len(self._alerts),
        }

    def _build_message(self, *, label: str, utilization: float) -> str:
        """Build descriptive alert message."""
        return (
            f"{label}: Budget at {utilization:.0%} "
            f"(cost=${self._accumulated_cost_usd:.4f}/{self._max_cost_usd:.2f}, "
            f"tokens={self._accumulated_tokens}/{self._max_total_tokens})"
        )

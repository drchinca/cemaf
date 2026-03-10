"""Quality police -- rolling quality monitor with anomaly detection and halt logic."""

from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Any

from cemaf.events.protocols import Event, EventBus, EventType
from cemaf.observability import get_logger

logger = get_logger("evals.police")


class AlertLevel(str, Enum):
    """Quality alert severity levels."""

    WARN = "warn"
    CRITICAL = "critical"
    HALT = "halt"


@dataclass(frozen=True)
class QualityAlert:
    """A quality degradation alert."""

    level: AlertLevel
    score: float
    rolling_mean: float
    message: str
    node_id: str | None = None


@dataclass(frozen=True)
class QualityPoliceConfig:
    """Configuration for quality monitoring thresholds."""

    window_size: int = 20
    warn_threshold: float = 0.7
    critical_threshold: float = 0.5
    halt_threshold: float = 0.3
    anomaly_drop: float = 0.3


class QualityPolice:
    """Monitors eval scores over a rolling window, detects anomalies, can halt execution."""

    def __init__(self, *, config: QualityPoliceConfig | None = None) -> None:
        self._config = config or QualityPoliceConfig()
        self._scores: deque[float] = deque(maxlen=self._config.window_size)
        self._alerts: list[QualityAlert] = []
        self._halted: bool = False
        self._event_bus: EventBus | None = None

    def record_score(self, *, score: float, node_id: str | None = None) -> QualityAlert | None:
        """Record an eval score and check thresholds."""
        mean_before = self.rolling_mean
        self._scores.append(score)
        mean_after = self.rolling_mean

        # Check anomaly: single score drops significantly below rolling mean
        if len(self._scores) > 1 and mean_before - score > self._config.anomaly_drop:
            alert = QualityAlert(
                level=AlertLevel.CRITICAL,
                score=score,
                rolling_mean=mean_before,
                message=(
                    f"Anomaly: score {score:.2f} dropped"
                    f" {mean_before - score:.2f} below mean {mean_before:.2f}"
                ),
                node_id=node_id,
            )
            self._alerts.append(alert)
            self._emit_alert(alert=alert)
            logger.warning("Quality anomaly detected: %s", alert.message)
            return alert

        # Check threshold levels on rolling mean
        if mean_after < self._config.halt_threshold:
            self._halted = True
            alert = QualityAlert(
                level=AlertLevel.HALT,
                score=score,
                rolling_mean=mean_after,
                message=f"Below halt threshold: mean={mean_after:.2f} < {self._config.halt_threshold}",
                node_id=node_id,
            )
            self._alerts.append(alert)
            self._emit_alert(alert=alert)
            logger.error("Quality halt triggered: %s", alert.message)
            return alert

        if mean_after < self._config.critical_threshold:
            alert = QualityAlert(
                level=AlertLevel.CRITICAL,
                score=score,
                rolling_mean=mean_after,
                message=f"Below critical: mean={mean_after:.2f} < {self._config.critical_threshold}",
                node_id=node_id,
            )
            self._alerts.append(alert)
            self._emit_alert(alert=alert)
            logger.warning("Quality critical: %s", alert.message)
            return alert

        if mean_after < self._config.warn_threshold:
            alert = QualityAlert(
                level=AlertLevel.WARN,
                score=score,
                rolling_mean=mean_after,
                message=f"Below warn threshold: mean={mean_after:.2f} < {self._config.warn_threshold}",
                node_id=node_id,
            )
            self._alerts.append(alert)
            self._emit_alert(alert=alert)
            return alert

        return None

    def should_halt(self) -> bool:
        """Check if execution should be halted due to quality degradation."""
        return self._halted

    @property
    def rolling_mean(self) -> float:
        """Current rolling mean score."""
        if not self._scores:
            return 1.0
        return sum(self._scores) / len(self._scores)

    @property
    def alerts(self) -> tuple[QualityAlert, ...]:
        """All recorded alerts."""
        return tuple(self._alerts)

    def subscribe(self, *, event_bus: EventBus) -> None:
        """Subscribe to EVAL_COMPLETED events to auto-record scores."""
        self._event_bus = event_bus
        event_bus.subscribe(
            event_type=EventType.EVAL_COMPLETED,
            handler=self._handle_eval_completed,
        )

    async def _handle_eval_completed(self, event: Event) -> None:
        """Extract score from eval event and record it."""
        score = event.payload.get("overall_score")
        node_id = event.payload.get("node_id")
        if score is not None:
            self.record_score(score=float(score), node_id=node_id)

    def _emit_alert(self, *, alert: QualityAlert) -> None:
        """Emit quality alert event if bus is configured."""
        if self._event_bus is None:
            return
        import asyncio

        try:
            loop = asyncio.get_running_loop()
            event = Event.create(
                type=EventType.QUALITY_ALERT,
                payload={
                    "level": alert.level.value,
                    "score": alert.score,
                    "rolling_mean": alert.rolling_mean,
                    "message": alert.message,
                    "node_id": alert.node_id,
                },
                source="quality_police",
            )
            task = loop.create_task(self._event_bus.publish(event=event))
            task.add_done_callback(lambda t: t.result() if not t.cancelled() and not t.exception() else None)
        except RuntimeError:
            pass  # no event loop running

    def reset(self) -> None:
        """Reset all state for a new run."""
        self._scores.clear()
        self._alerts.clear()
        self._halted = False

    def to_dict(self) -> dict[str, Any]:
        """Serialize state for logging."""
        return {
            "rolling_mean": self.rolling_mean,
            "scores_count": len(self._scores),
            "halted": self._halted,
            "alerts_count": len(self._alerts),
            "config": {
                "window_size": self._config.window_size,
                "warn_threshold": self._config.warn_threshold,
                "critical_threshold": self._config.critical_threshold,
                "halt_threshold": self._config.halt_threshold,
            },
        }

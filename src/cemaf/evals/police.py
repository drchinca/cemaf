"""Quality police — rolling quality monitor with trend detection and predictive halting."""

from collections import deque
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from cemaf.events.protocols import Event, EventBus, EventType
from cemaf.observability import get_logger

logger = get_logger("evals.police")


class AlertLevel(StrEnum):
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
class TrendAnalysis:
    """Result of linear trend analysis over the score window."""

    slope: float  # Score change per step (negative = degrading)
    intercept: float
    current_mean: float
    projected_steps_to_halt: int | None  # Steps until halt threshold, None if improving
    confidence: float  # R-squared of the fit (0-1)

    @property
    def is_degrading(self) -> bool:
        return self.slope < -0.001  # Meaningful negative trend


@dataclass(frozen=True)
class QualityPoliceConfig:
    """Configuration for quality monitoring thresholds."""

    window_size: int = 20
    warn_threshold: float = 0.7
    critical_threshold: float = 0.5
    halt_threshold: float = 0.3
    anomaly_drop: float = 0.3
    # Trend-based predictive halting
    predictive_halt_enabled: bool = True
    predictive_halt_horizon: int = 5  # Halt if projected to cross threshold within N steps
    min_samples_for_trend: int = 4  # Need at least this many scores for trend analysis


class QualityPolice:
    """Monitors eval scores with trend detection and predictive halting."""

    def __init__(self, *, config: QualityPoliceConfig | None = None) -> None:
        self._config = config or QualityPoliceConfig()
        self._scores: deque[float] = deque(maxlen=self._config.window_size)
        self._alerts: list[QualityAlert] = []
        self._halted: bool = False
        self._event_bus: EventBus | None = None
        self._last_trend: TrendAnalysis | None = None

    def record_score(self, *, score: float, node_id: str | None = None) -> QualityAlert | None:
        """Record an eval score, check thresholds, and run trend analysis."""
        mean_before = self.rolling_mean
        self._scores.append(score)
        mean_after = self.rolling_mean

        # 1. Check anomaly: single score drops significantly below rolling mean
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

        # 2. Check hard threshold on rolling mean
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

        # 3. Predictive halt — trend-based
        if self._config.predictive_halt_enabled:
            trend = self.analyze_trend()
            self._last_trend = trend
            if (
                trend is not None
                and trend.is_degrading
                and trend.projected_steps_to_halt is not None
                and trend.projected_steps_to_halt <= self._config.predictive_halt_horizon
                and trend.confidence >= 0.5  # Only halt on reasonably confident trends
            ):
                self._halted = True
                alert = QualityAlert(
                    level=AlertLevel.HALT,
                    score=score,
                    rolling_mean=mean_after,
                    message=(
                        f"Predictive halt: trend slope={trend.slope:.4f}, "
                        f"projected to cross {self._config.halt_threshold} "
                        f"in {trend.projected_steps_to_halt} steps "
                        f"(confidence={trend.confidence:.2f})"
                    ),
                    node_id=node_id,
                )
                self._alerts.append(alert)
                self._emit_alert(alert=alert)
                logger.error("Predictive quality halt: %s", alert.message)
                return alert

        # 4. Standard threshold warnings
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

    def analyze_trend(self) -> TrendAnalysis | None:
        """Compute linear regression over the score window for trend detection."""
        n = len(self._scores)
        if n < self._config.min_samples_for_trend:
            return None

        scores = list(self._scores)
        # Simple linear regression: y = slope * x + intercept
        x_mean = (n - 1) / 2.0
        y_mean = sum(scores) / n

        numerator = 0.0
        denominator = 0.0
        for i, y in enumerate(scores):
            numerator += (i - x_mean) * (y - y_mean)
            denominator += (i - x_mean) ** 2

        if denominator == 0:
            return TrendAnalysis(
                slope=0.0,
                intercept=y_mean,
                current_mean=y_mean,
                projected_steps_to_halt=None,
                confidence=0.0,
            )

        slope = numerator / denominator
        intercept = y_mean - slope * x_mean

        # R-squared for confidence
        ss_res = sum((y - (slope * i + intercept)) ** 2 for i, y in enumerate(scores))
        ss_tot = sum((y - y_mean) ** 2 for y in scores)
        r_squared = 1.0 - (ss_res / ss_tot) if ss_tot > 0 else 0.0

        # Project: at what future step does the line cross halt_threshold?
        projected_steps: int | None = None
        if slope < 0:
            current_projected = slope * (n - 1) + intercept  # Current end of line
            if current_projected > self._config.halt_threshold:
                # Steps from current position to threshold
                steps_to_threshold = (current_projected - self._config.halt_threshold) / abs(slope)
                projected_steps = max(1, int(steps_to_threshold))

        return TrendAnalysis(
            slope=slope,
            intercept=intercept,
            current_mean=y_mean,
            projected_steps_to_halt=projected_steps,
            confidence=max(0.0, min(1.0, r_squared)),
        )

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
    def last_trend(self) -> TrendAnalysis | None:
        """Most recent trend analysis."""
        return self._last_trend

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

            def _on_alert_done(t: asyncio.Task[None]) -> None:
                if not t.cancelled() and t.exception():
                    logger.error("Failed to publish quality alert: %s", t.exception())

            task.add_done_callback(_on_alert_done)
        except RuntimeError:
            logger.warning("No event loop — quality alert not published")

    def reset(self) -> None:
        """Reset all state for a new run."""
        self._scores.clear()
        self._alerts.clear()
        self._halted = False
        self._last_trend = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize state for logging."""
        trend_data = None
        if self._last_trend:
            trend_data = {
                "slope": self._last_trend.slope,
                "projected_steps_to_halt": self._last_trend.projected_steps_to_halt,
                "confidence": self._last_trend.confidence,
                "is_degrading": self._last_trend.is_degrading,
            }
        return {
            "rolling_mean": self.rolling_mean,
            "scores_count": len(self._scores),
            "halted": self._halted,
            "alerts_count": len(self._alerts),
            "trend": trend_data,
            "config": {
                "window_size": self._config.window_size,
                "warn_threshold": self._config.warn_threshold,
                "critical_threshold": self._config.critical_threshold,
                "halt_threshold": self._config.halt_threshold,
                "predictive_halt_enabled": self._config.predictive_halt_enabled,
                "predictive_halt_horizon": self._config.predictive_halt_horizon,
            },
        }

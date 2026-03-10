"""Tests for QualityPolice rolling quality monitor."""

import pytest

from cemaf.evals.police import AlertLevel, QualityPolice, QualityPoliceConfig
from cemaf.events.bus import InMemoryEventBus
from cemaf.events.protocols import Event, EventType


class TestQualityPoliceInitialState:
    def test_initial_state_not_halted(self) -> None:
        police = QualityPolice()

        assert police.should_halt() is False
        assert police.rolling_mean == 1.0
        assert police.alerts == ()

    def test_good_scores_no_alerts(self) -> None:
        police = QualityPolice()

        for score in [0.9, 0.85, 0.95, 0.88, 0.92]:
            alert = police.record_score(score=score)
            assert alert is None

        assert police.should_halt() is False
        assert police.alerts == ()
        assert police.rolling_mean == pytest.approx(0.9, abs=0.01)


class TestQualityPoliceThresholds:
    def test_warn_threshold_triggers_alert(self) -> None:
        config = QualityPoliceConfig(warn_threshold=0.7, anomaly_drop=1.0)
        police = QualityPolice(config=config)

        # Feed scores that average below warn but above critical
        for _ in range(3):
            alert = police.record_score(score=0.6)

        assert alert is not None
        assert alert.level == AlertLevel.WARN
        assert alert.rolling_mean < 0.7
        assert police.should_halt() is False
        assert len(police.alerts) > 0

    def test_critical_threshold_triggers_alert(self) -> None:
        config = QualityPoliceConfig(critical_threshold=0.5, anomaly_drop=1.0)
        police = QualityPolice(config=config)

        for _ in range(3):
            alert = police.record_score(score=0.4)

        assert alert is not None
        assert alert.level == AlertLevel.CRITICAL
        assert alert.rolling_mean < 0.5
        assert police.should_halt() is False

    def test_halt_threshold_sets_halted(self) -> None:
        config = QualityPoliceConfig(halt_threshold=0.3, anomaly_drop=1.0)
        police = QualityPolice(config=config)

        for _ in range(3):
            alert = police.record_score(score=0.2)

        assert alert is not None
        assert alert.level == AlertLevel.HALT
        assert police.should_halt() is True


class TestQualityPoliceAnomalyDetection:
    def test_anomaly_detection_sudden_drop(self) -> None:
        config = QualityPoliceConfig(anomaly_drop=0.3)
        police = QualityPolice(config=config)

        # Build up a good baseline
        for _ in range(5):
            police.record_score(score=0.9)

        # Sudden drop should trigger anomaly
        alert = police.record_score(score=0.3, node_id="bad-node")

        assert alert is not None
        assert alert.level == AlertLevel.CRITICAL
        assert alert.node_id == "bad-node"
        assert "Anomaly" in alert.message


class TestQualityPoliceWindow:
    def test_rolling_window_bounded(self) -> None:
        config = QualityPoliceConfig(window_size=5)
        police = QualityPolice(config=config)

        # Fill with low scores
        for _ in range(5):
            police.record_score(score=0.2)

        # Now fill with high scores -- old low scores should drop out
        for _ in range(5):
            police.record_score(score=0.95)

        assert police.rolling_mean == pytest.approx(0.95, abs=0.01)


class TestQualityPoliceReset:
    def test_reset_clears_state(self) -> None:
        config = QualityPoliceConfig(anomaly_drop=1.0)
        police = QualityPolice(config=config)

        # Accumulate some state
        for _ in range(3):
            police.record_score(score=0.1)

        assert police.should_halt() is True
        assert len(police.alerts) > 0

        police.reset()

        assert police.should_halt() is False
        assert police.rolling_mean == 1.0
        assert police.alerts == ()


class TestQualityPoliceEventIntegration:
    @pytest.mark.asyncio
    async def test_subscribe_records_scores_from_events(self) -> None:
        bus = InMemoryEventBus()
        police = QualityPolice()
        police.subscribe(event_bus=bus)

        # Publish eval completed events with scores
        for score in [0.9, 0.85, 0.8]:
            event = Event.create(
                type=EventType.EVAL_COMPLETED,
                payload={"overall_score": score, "node_id": "test-node"},
                source="test",
            )
            await bus.publish(event=event)

        expected_mean = (0.9 + 0.85 + 0.8) / 3
        assert police.rolling_mean == pytest.approx(expected_mean, abs=0.001)


class TestQualityPoliceSerialization:
    def test_to_dict_serialization(self) -> None:
        config = QualityPoliceConfig(
            window_size=10,
            warn_threshold=0.7,
            critical_threshold=0.5,
            halt_threshold=0.3,
        )
        police = QualityPolice(config=config)
        police.record_score(score=0.8)
        police.record_score(score=0.75)

        result = police.to_dict()

        assert result["rolling_mean"] == pytest.approx(0.775, abs=0.001)
        assert result["scores_count"] == 2
        assert result["halted"] is False
        assert result["alerts_count"] == 0
        assert result["config"]["window_size"] == 10
        assert result["config"]["warn_threshold"] == 0.7
        assert result["config"]["critical_threshold"] == 0.5
        assert result["config"]["halt_threshold"] == 0.3

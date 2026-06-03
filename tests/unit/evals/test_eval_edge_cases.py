"""Edge case tests for online eval, hierarchy, and police modules."""

from typing import Any

import pytest

from cemaf.evals.hierarchy import HierarchicalJudge, HierarchicalJudgeConfig
from cemaf.evals.online import EvalMode, NodeEvalBinding, OnlineEvalPipeline
from cemaf.evals.police import AlertLevel, QualityPolice, QualityPoliceConfig
from cemaf.evals.protocols import EvalMetric, EvalResult
from cemaf.events.bus import InMemoryEventBus
from cemaf.events.protocols import Event, EventType
from tests.unit.evals.conftest import FailingEvaluator, FakeEvaluator


def _task_completed_event(
    *,
    node_id: str = "node-a",
    output: Any = "hello world",
    correlation_id: str = "corr-1",
) -> Event:
    return Event.create(
        type=EventType.TASK_COMPLETED,
        payload={"node_id": node_id, "output": output},
        source="test",
        correlation_id=correlation_id,
    )


# ===========================================================================
# Online Pipeline Edge Cases
# ===========================================================================


class TestOnlineMultipleBindings:
    @pytest.mark.asyncio
    async def test_multiple_bindings_match_same_node(self) -> None:
        bus = InMemoryEventBus()
        binding_a = NodeEvalBinding(
            node_pattern="node-a",
            evaluators=(FakeEvaluator(score=0.9),),
            mode=EvalMode.OBSERVE,
        )
        binding_b = NodeEvalBinding(
            node_pattern="node-a",
            evaluators=(FakeEvaluator(score=0.3, passed=False),),
            mode=EvalMode.OBSERVE,
        )
        pipeline = OnlineEvalPipeline(
            bindings=(binding_a, binding_b),
            event_bus=bus,
        )
        pipeline.subscribe()

        await bus.publish(event=_task_completed_event(node_id="node-a"))
        await pipeline.flush()

        assert len(pipeline.results) == 2
        scores = sorted(r["overall_score"] for r in pipeline.results)
        assert scores[0] == pytest.approx(0.3)
        assert scores[1] == pytest.approx(0.9)

    @pytest.mark.asyncio
    async def test_specific_and_wildcard_both_fire(self) -> None:
        bus = InMemoryEventBus()
        specific = NodeEvalBinding(
            node_pattern="node-a",
            evaluators=(FakeEvaluator(score=0.8),),
            mode=EvalMode.OBSERVE,
        )
        wildcard = NodeEvalBinding(
            node_pattern="*",
            evaluators=(FakeEvaluator(score=0.6),),
            mode=EvalMode.OBSERVE,
        )
        pipeline = OnlineEvalPipeline(
            bindings=(specific, wildcard),
            event_bus=bus,
        )
        pipeline.subscribe()

        await bus.publish(event=_task_completed_event(node_id="node-a"))
        await pipeline.flush()

        assert len(pipeline.results) == 2


class TestOnlineErrorHandling:
    @pytest.mark.asyncio
    async def test_evaluator_error_emits_eval_failed(self) -> None:
        bus = InMemoryEventBus()
        failed_events: list[Event] = []

        async def capture_failed(event: Event) -> None:
            failed_events.append(event)

        bus.subscribe(event_type=EventType.EVAL_FAILED, handler=capture_failed)

        binding = NodeEvalBinding(
            node_pattern="node-a",
            evaluators=(FailingEvaluator(error_message="evaluator exploded"),),
            mode=EvalMode.OBSERVE,
        )
        pipeline = OnlineEvalPipeline(
            bindings=(binding,),
            event_bus=bus,
        )
        pipeline.subscribe()

        await bus.publish(event=_task_completed_event(node_id="node-a"))
        await pipeline.flush()

        assert len(failed_events) == 1
        assert failed_events[0].payload["node_id"] == "node-a"
        assert "evaluator exploded" in failed_events[0].payload["error"]
        assert len(pipeline.results) == 0


class TestOnlineGatePassingEval:
    @pytest.mark.asyncio
    async def test_gate_mode_passing_eval_no_quality_alert(self) -> None:
        bus = InMemoryEventBus()
        alerts: list[Event] = []

        async def capture_alert(event: Event) -> None:
            alerts.append(event)

        bus.subscribe(event_type=EventType.QUALITY_ALERT, handler=capture_alert)

        binding = NodeEvalBinding(
            node_pattern="node-a",
            evaluators=(FakeEvaluator(score=0.9, passed=True),),
            mode=EvalMode.GATE,
        )
        pipeline = OnlineEvalPipeline(
            bindings=(binding,),
            event_bus=bus,
        )
        pipeline.subscribe()

        await bus.publish(event=_task_completed_event(node_id="node-a"))

        assert len(alerts) == 0
        assert len(pipeline.results) == 1
        assert pipeline.results[0]["overall_passed"] is True


class TestOnlineOutputCoercion:
    @pytest.mark.asyncio
    async def test_dict_output_coerced_to_str(self) -> None:
        bus = InMemoryEventBus()
        binding = NodeEvalBinding(
            node_pattern="*",
            evaluators=(FakeEvaluator(score=0.7),),
            mode=EvalMode.OBSERVE,
        )
        pipeline = OnlineEvalPipeline(
            bindings=(binding,),
            event_bus=bus,
        )
        pipeline.subscribe()

        await bus.publish(
            event=_task_completed_event(
                node_id="node-a",
                output={"key": "value"},
            )
        )
        await pipeline.flush()

        assert len(pipeline.results) == 1

    @pytest.mark.asyncio
    async def test_empty_string_output_is_processed(self) -> None:
        bus = InMemoryEventBus()
        binding = NodeEvalBinding(
            node_pattern="*",
            evaluators=(FakeEvaluator(score=0.5),),
            mode=EvalMode.OBSERVE,
        )
        pipeline = OnlineEvalPipeline(
            bindings=(binding,),
            event_bus=bus,
        )
        pipeline.subscribe()

        await bus.publish(
            event=_task_completed_event(
                node_id="node-a",
                output="",
            )
        )
        await pipeline.flush()

        assert len(pipeline.results) == 1
        assert pipeline.results[0]["node_id"] == "node-a"


# ===========================================================================
# Hierarchy Edge Cases
# ===========================================================================


class TestHierarchyThresholdBoundaries:
    @pytest.mark.asyncio
    async def test_score_exactly_at_tier1_threshold_passes(self) -> None:
        judge = HierarchicalJudge(
            tier1_evaluators=(FakeEvaluator(score=0.5, passed=True),),
            config=HierarchicalJudgeConfig(tier1_pass_threshold=0.5),
        )
        result = await judge.evaluate(output="test")

        assert result.passed is True
        assert result.metadata["tiers_run"] == [1]

    @pytest.mark.asyncio
    async def test_score_just_below_tier1_threshold_fails(self) -> None:
        judge = HierarchicalJudge(
            tier1_evaluators=(FakeEvaluator(score=0.49, passed=False),),
            config=HierarchicalJudgeConfig(tier1_pass_threshold=0.5),
        )
        result = await judge.evaluate(output="test")

        assert result.passed is False
        assert result.metadata["tiers_run"] == [1]


class TestHierarchyEmptyTier1:
    @pytest.mark.asyncio
    async def test_empty_tier1_evaluators(self) -> None:
        judge = HierarchicalJudge(
            tier1_evaluators=(),
            config=HierarchicalJudgeConfig(tier1_pass_threshold=0.5),
        )
        result = await judge.evaluate(output="test")

        # CompositeEvaluator with no evaluators produces score 0.0 (mean of empty)
        # which is below 0.5 threshold -> tier 1 fails
        assert result.passed is False
        assert result.metadata["tiers_run"] == [1]


class TestHierarchyNonDefaultConfig:
    @pytest.mark.asyncio
    async def test_threshold_zero_always_passes(self) -> None:
        judge = HierarchicalJudge(
            tier1_evaluators=(FakeEvaluator(score=0.01, passed=True),),
            config=HierarchicalJudgeConfig(tier1_pass_threshold=0.0),
        )
        result = await judge.evaluate(output="test")

        assert result.passed is True

    @pytest.mark.asyncio
    async def test_threshold_one_never_passes(self) -> None:
        judge = HierarchicalJudge(
            tier1_evaluators=(FakeEvaluator(score=0.99, passed=False),),
            config=HierarchicalJudgeConfig(tier1_pass_threshold=1.0),
        )
        result = await judge.evaluate(output="test")

        assert result.passed is False


class TestHierarchyAmbiguityRangeEdges:
    @pytest.mark.asyncio
    async def test_tier2_score_at_lower_bound_triggers_tier3(self) -> None:
        judge = HierarchicalJudge(
            tier1_evaluators=(FakeEvaluator(score=0.8, passed=True),),
            tier2_evaluator=FakeEvaluator(score=0.4, passed=True),
            tier3_evaluator=FakeEvaluator(score=0.75, passed=True),
            config=HierarchicalJudgeConfig(
                tier3_ambiguity_range=(0.4, 0.7),
                tier3_sample_rate=0.0,
            ),
        )
        result = await judge.evaluate(output="test", expected="test")

        assert result.metadata["tiers_run"] == [1, 2, 3]
        assert result.score == pytest.approx(0.75)

    @pytest.mark.asyncio
    async def test_tier2_score_at_upper_bound_triggers_tier3(self) -> None:
        judge = HierarchicalJudge(
            tier1_evaluators=(FakeEvaluator(score=0.8, passed=True),),
            tier2_evaluator=FakeEvaluator(score=0.7, passed=True),
            tier3_evaluator=FakeEvaluator(score=0.85, passed=True),
            config=HierarchicalJudgeConfig(
                tier3_ambiguity_range=(0.4, 0.7),
                tier3_sample_rate=0.0,
            ),
        )
        result = await judge.evaluate(output="test", expected="test")

        assert result.metadata["tiers_run"] == [1, 2, 3]
        assert result.score == pytest.approx(0.85)

    @pytest.mark.asyncio
    async def test_tier2_score_just_above_upper_bound_skips_tier3(self) -> None:
        judge = HierarchicalJudge(
            tier1_evaluators=(FakeEvaluator(score=0.8, passed=True),),
            tier2_evaluator=FakeEvaluator(score=0.71, passed=True),
            tier3_evaluator=FakeEvaluator(score=0.99, passed=True),
            config=HierarchicalJudgeConfig(
                tier3_ambiguity_range=(0.4, 0.7),
                tier3_sample_rate=0.0,
            ),
        )
        result = await judge.evaluate(output="test", expected="test")

        assert result.metadata["tiers_run"] == [1, 2]
        assert result.score == pytest.approx(0.71)


class TestHierarchySampleRateAlwaysEscalates:
    @pytest.mark.asyncio
    async def test_sample_rate_1_always_escalates_to_tier3(self) -> None:
        judge = HierarchicalJudge(
            tier1_evaluators=(FakeEvaluator(score=0.8, passed=True),),
            tier2_evaluator=FakeEvaluator(score=0.9, passed=True),
            tier3_evaluator=FakeEvaluator(score=0.95, passed=True),
            config=HierarchicalJudgeConfig(
                tier3_ambiguity_range=(0.4, 0.7),
                tier3_sample_rate=1.0,
            ),
        )

        # Run multiple times to confirm determinism at rate=1.0
        for _ in range(5):
            result = await judge.evaluate(output="test", expected="test")
            assert result.metadata["tiers_run"] == [1, 2, 3]
            assert result.score == pytest.approx(0.95)


# ===========================================================================
# Police Edge Cases
# ===========================================================================


class TestPoliceScoreValidation:
    def test_negative_score_accepted(self) -> None:
        police = QualityPolice(
            config=QualityPoliceConfig(anomaly_drop=10.0),
        )
        police.record_score(score=-0.5)

        # No bounds checking in current impl -- negative scores are stored
        assert police.rolling_mean == pytest.approx(-0.5)

    def test_score_above_one_accepted(self) -> None:
        police = QualityPolice(
            config=QualityPoliceConfig(anomaly_drop=10.0),
        )
        police.record_score(score=1.5)

        assert police.rolling_mean == pytest.approx(1.5)

    def test_negative_score_triggers_anomaly_when_baseline_high(self) -> None:
        police = QualityPolice(
            config=QualityPoliceConfig(anomaly_drop=0.3),
        )
        for _ in range(3):
            police.record_score(score=0.9)

        alert = police.record_score(score=-0.1)

        assert alert is not None
        assert alert.level == AlertLevel.CRITICAL
        assert "Anomaly" in alert.message


class TestPoliceWindowSizeOne:
    def test_window_size_one_no_anomaly(self) -> None:
        config = QualityPoliceConfig(
            window_size=1,
            anomaly_drop=0.3,
            halt_threshold=0.0,
            critical_threshold=0.0,
            warn_threshold=0.0,
        )
        police = QualityPolice(config=config)

        # First score: len == 1, anomaly check requires len > 1
        alert = police.record_score(score=0.1)
        assert alert is None

        # Second score replaces the first (window=1), still len == 1
        alert = police.record_score(score=0.9)
        assert alert is None


class TestPoliceThresholdOrdering:
    def test_backwards_thresholds_warn_below_critical(self) -> None:
        # warn=0.3, critical=0.5, halt=0.7 -- inverted
        config = QualityPoliceConfig(
            warn_threshold=0.3,
            critical_threshold=0.5,
            halt_threshold=0.7,
            anomaly_drop=10.0,
        )
        police = QualityPolice(config=config)

        # Score 0.6 -> mean=0.6, below halt(0.7) -> HALT
        alert = police.record_score(score=0.6)

        assert alert is not None
        assert alert.level == AlertLevel.HALT
        assert police.should_halt() is True


class TestPoliceMultipleAnomalies:
    def test_successive_anomalies(self) -> None:
        config = QualityPoliceConfig(
            window_size=10,
            anomaly_drop=0.3,
            halt_threshold=0.0,
            critical_threshold=0.0,
            warn_threshold=0.0,
        )
        police = QualityPolice(config=config)

        # Build baseline
        for _ in range(5):
            police.record_score(score=0.9)

        # Two anomalous drops in succession
        alert1 = police.record_score(score=0.1)
        assert alert1 is not None
        assert alert1.level == AlertLevel.CRITICAL
        assert "Anomaly" in alert1.message

        # Mean is now lowered (~0.767), but 0.1 still below mean by > 0.3
        alert2 = police.record_score(score=0.1)

        assert alert2 is not None
        assert "Anomaly" in alert2.message

        assert len(police.alerts) >= 2


class TestPoliceToDictConfig:
    def test_to_dict_includes_correct_config(self) -> None:
        config = QualityPoliceConfig(
            window_size=50,
            warn_threshold=0.8,
            critical_threshold=0.6,
            halt_threshold=0.4,
        )
        police = QualityPolice(config=config)

        result = police.to_dict()

        assert result["config"]["window_size"] == 50
        assert result["config"]["warn_threshold"] == pytest.approx(0.8)
        assert result["config"]["critical_threshold"] == pytest.approx(0.6)
        assert result["config"]["halt_threshold"] == pytest.approx(0.4)
        assert result["halted"] is False
        assert result["scores_count"] == 0
        assert result["alerts_count"] == 0


class TestPoliceAnomalyPriority:
    def test_anomaly_returns_before_threshold_check(self) -> None:
        # Configure so both anomaly AND halt would fire
        config = QualityPoliceConfig(
            window_size=10,
            anomaly_drop=0.3,
            halt_threshold=0.3,
        )
        police = QualityPolice(config=config)

        for _ in range(5):
            police.record_score(score=0.9)

        # Score 0.1: anomaly fires (0.9 - 0.1 = 0.8 > 0.3)
        # But mean after would be ~0.77, above halt=0.3
        # Anomaly check returns early, so we get CRITICAL not HALT
        alert = police.record_score(score=0.1)

        assert alert is not None
        assert alert.level == AlertLevel.CRITICAL
        assert "Anomaly" in alert.message
        # Anomaly returns before threshold checks, so halt is NOT set
        assert police.should_halt() is False


# ===========================================================================
# EvalResult Factories
# ===========================================================================


class TestEvalResultFactories:
    @pytest.mark.asyncio
    async def test_passed_result_factory(self) -> None:
        result = EvalResult.passed_result(
            metric=EvalMetric.EXACT_MATCH,
            score=0.95,
            reason="exact match",
        )

        assert result.passed is True
        assert result.score == pytest.approx(0.95)
        assert result.metric == EvalMetric.EXACT_MATCH
        assert result.reason == "exact match"

    @pytest.mark.asyncio
    async def test_passed_result_factory_defaults(self) -> None:
        result = EvalResult.passed_result(metric=EvalMetric.CUSTOM)

        assert result.passed is True
        assert result.score == pytest.approx(1.0)
        assert result.reason == ""

    @pytest.mark.asyncio
    async def test_failed_result_factory(self) -> None:
        result = EvalResult.failed_result(metric=EvalMetric.RELEVANCE)

        assert result.passed is False
        assert result.score == pytest.approx(0.0)
        assert result.reason == ""
        assert result.expected is None
        assert result.actual is None

    @pytest.mark.asyncio
    async def test_failed_result_factory_all_params(self) -> None:
        result = EvalResult.failed_result(
            metric=EvalMetric.FACTUALITY,
            score=0.2,
            reason="hallucinated",
            expected="Paris is the capital of France",
            actual="Paris is the capital of Germany",
        )

        assert result.passed is False
        assert result.score == pytest.approx(0.2)
        assert result.metric == EvalMetric.FACTUALITY
        assert result.reason == "hallucinated"
        assert result.expected == "Paris is the capital of France"
        assert result.actual == "Paris is the capital of Germany"

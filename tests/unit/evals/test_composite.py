"""Tests for composite evaluators, aggregation strategies, and eval suites."""

import pytest

from cemaf.evals.composite import (
    AggregationStrategy,
    CompositeEvalResult,
    CompositeEvaluator,
    EvalCase,
    EvalSuite,
    EvalSuiteResult,
)
from cemaf.evals.evaluators import (
    ContainsEvaluator,
    ExactMatchEvaluator,
    LengthEvaluator,
)
from cemaf.evals.protocols import EvalConfig, EvalMetric, EvalResult


class TestAggregationStrategy:
    def test_mean_typical_scores(self):
        result = AggregationStrategy.mean(scores=[0.8, 0.6, 1.0])
        assert result == pytest.approx(0.8)

    def test_mean_empty_list(self):
        result = AggregationStrategy.mean(scores=[])
        assert result == 0.0

    def test_mean_single_score(self):
        result = AggregationStrategy.mean(scores=[0.7])
        assert result == pytest.approx(0.7)

    def test_min_returns_lowest(self):
        result = AggregationStrategy.min(scores=[0.9, 0.3, 0.7])
        assert result == pytest.approx(0.3)

    def test_min_empty_list(self):
        result = AggregationStrategy.min(scores=[])
        assert result == 0.0

    def test_max_returns_highest(self):
        result = AggregationStrategy.max(scores=[0.2, 0.9, 0.5])
        assert result == pytest.approx(0.9)

    def test_max_empty_list(self):
        result = AggregationStrategy.max(scores=[])
        assert result == 0.0

    def test_weighted_typical(self):
        result = AggregationStrategy.weighted(
            scores=[1.0, 0.0],
            weights=[3.0, 1.0],
        )
        assert result == pytest.approx(0.75)

    def test_weighted_empty_scores(self):
        result = AggregationStrategy.weighted(scores=[], weights=[])
        assert result == 0.0

    def test_weighted_zero_total_weight(self):
        result = AggregationStrategy.weighted(
            scores=[0.5, 0.8],
            weights=[0.0, 0.0],
        )
        assert result == 0.0

    def test_weighted_unequal_lengths(self):
        result = AggregationStrategy.weighted(
            scores=[1.0, 0.5, 0.8],
            weights=[1.0, 2.0],
        )
        # zip(strict=False) truncates to shortest
        expected = (1.0 * 1.0 + 0.5 * 2.0) / (1.0 + 2.0)
        assert result == pytest.approx(expected)

    def test_weighted_empty_weights_only(self):
        result = AggregationStrategy.weighted(scores=[0.5], weights=[])
        assert result == 0.0


class TestCompositeEvaluator:
    @pytest.mark.asyncio
    async def test_mean_aggregation_default(self):
        evaluator = CompositeEvaluator(
            evaluators=[
                ExactMatchEvaluator(),
                LengthEvaluator(min_length=1, max_length=100),
            ],
        )

        result = await evaluator.evaluate(output="hello", expected="hello")

        assert result.overall_score == pytest.approx(1.0)
        assert result.overall_passed is True
        assert len(result.results) == 2

    @pytest.mark.asyncio
    async def test_min_aggregation_most_strict(self):
        evaluator = CompositeEvaluator(
            evaluators=[
                ExactMatchEvaluator(),
                LengthEvaluator(min_length=100),
            ],
            aggregation="min",
        )

        result = await evaluator.evaluate(output="hello", expected="hello")

        # ExactMatch=1.0, Length<1.0 (too short) => min picks the low score
        assert result.overall_score < 1.0
        assert len(result.failed_metrics) >= 1

    @pytest.mark.asyncio
    async def test_max_aggregation_most_lenient(self):
        evaluator = CompositeEvaluator(
            evaluators=[
                ExactMatchEvaluator(),
                LengthEvaluator(min_length=100),
            ],
            aggregation="max",
        )

        result = await evaluator.evaluate(output="hello", expected="hello")

        # ExactMatch=1.0, Length<1.0 => max picks 1.0
        assert result.overall_score == pytest.approx(1.0)
        assert result.overall_passed is True

    @pytest.mark.asyncio
    async def test_weighted_aggregation(self):
        evaluator = CompositeEvaluator(
            evaluators=[
                ExactMatchEvaluator(),
                LengthEvaluator(min_length=100),
            ],
            aggregation="weighted",
            weights=[3.0, 1.0],
        )

        result = await evaluator.evaluate(output="hello", expected="hello")

        # ExactMatch=1.0 (weight 3), Length=5/100=0.05 (weight 1)
        # weighted = (1.0*3 + 0.05*1) / 4 = 0.7625
        assert result.overall_score > 0.5
        assert result.overall_score < 1.0

    @pytest.mark.asyncio
    async def test_fail_fast_stops_on_first_failure(self):
        config = EvalConfig(fail_fast=True, pass_threshold=0.5)
        evaluator = CompositeEvaluator(
            evaluators=[
                ExactMatchEvaluator(),  # will fail (mismatch)
                LengthEvaluator(min_length=1),  # would pass but should not run
            ],
            config=config,
        )

        result = await evaluator.evaluate(output="hello", expected="world")

        # Only the first evaluator ran, second was skipped
        assert len(result.results) == 1
        assert result.results[0].metric == EvalMetric.EXACT_MATCH
        assert not result.results[0].passed

    @pytest.mark.asyncio
    async def test_require_all_pass_true_all_pass(self):
        evaluator = CompositeEvaluator(
            evaluators=[
                ExactMatchEvaluator(),
                LengthEvaluator(min_length=1, max_length=100),
            ],
            require_all_pass=True,
        )

        result = await evaluator.evaluate(output="hello", expected="hello")

        assert result.overall_passed is True

    @pytest.mark.asyncio
    async def test_require_all_pass_true_one_fails(self):
        evaluator = CompositeEvaluator(
            evaluators=[
                ExactMatchEvaluator(),
                LengthEvaluator(min_length=100),
            ],
            require_all_pass=True,
        )

        result = await evaluator.evaluate(output="hello", expected="hello")

        assert result.overall_passed is False

    @pytest.mark.asyncio
    async def test_empty_evaluators_list(self):
        evaluator = CompositeEvaluator(evaluators=[])

        result = await evaluator.evaluate(output="hello")

        assert result.overall_score == 0.0
        assert len(result.results) == 0
        assert len(result.failed_metrics) == 0

    @pytest.mark.asyncio
    async def test_mixed_pass_fail_evaluators(self):
        evaluator = CompositeEvaluator(
            evaluators=[
                ExactMatchEvaluator(),
                ContainsEvaluator(),
                LengthEvaluator(min_length=100),
            ],
        )

        result = await evaluator.evaluate(output="hello world", expected="hello")

        # ExactMatch fails (hello world != hello), Contains passes, Length fails
        assert len(result.results) == 3
        assert len(result.failed_metrics) >= 1
        assert result.overall_score > 0.0
        assert result.overall_score < 1.0


class TestCompositeEvalResult:
    def _make_result(self, *, score: float, passed: bool, metric: EvalMetric) -> EvalResult:
        return EvalResult(
            metric=metric,
            score=score,
            passed=passed,
            reason="test",
        )

    def test_all_passed_true_when_all_pass(self):
        result = CompositeEvalResult(
            results=(
                self._make_result(score=1.0, passed=True, metric=EvalMetric.EXACT_MATCH),
                self._make_result(score=0.9, passed=True, metric=EvalMetric.LENGTH),
            ),
            overall_score=0.95,
            overall_passed=True,
            failed_metrics=(),
        )

        assert result.all_passed is True

    def test_all_passed_false_when_any_fails(self):
        result = CompositeEvalResult(
            results=(
                self._make_result(score=1.0, passed=True, metric=EvalMetric.EXACT_MATCH),
                self._make_result(score=0.2, passed=False, metric=EvalMetric.LENGTH),
            ),
            overall_score=0.6,
            overall_passed=False,
            failed_metrics=(EvalMetric.LENGTH,),
        )

        assert result.all_passed is False

    def test_pass_rate_all_pass(self):
        result = CompositeEvalResult(
            results=(
                self._make_result(score=1.0, passed=True, metric=EvalMetric.EXACT_MATCH),
                self._make_result(score=0.8, passed=True, metric=EvalMetric.LENGTH),
            ),
            overall_score=0.9,
            overall_passed=True,
            failed_metrics=(),
        )

        assert result.pass_rate == pytest.approx(1.0)

    def test_pass_rate_half_pass(self):
        result = CompositeEvalResult(
            results=(
                self._make_result(score=1.0, passed=True, metric=EvalMetric.EXACT_MATCH),
                self._make_result(score=0.1, passed=False, metric=EvalMetric.LENGTH),
            ),
            overall_score=0.55,
            overall_passed=True,
            failed_metrics=(EvalMetric.LENGTH,),
        )

        assert result.pass_rate == pytest.approx(0.5)

    def test_pass_rate_empty_results(self):
        result = CompositeEvalResult(
            results=(),
            overall_score=0.0,
            overall_passed=False,
            failed_metrics=(),
        )

        assert result.pass_rate == 0.0

    def test_get_result_found(self):
        exact_result = self._make_result(score=1.0, passed=True, metric=EvalMetric.EXACT_MATCH)
        result = CompositeEvalResult(
            results=(exact_result,),
            overall_score=1.0,
            overall_passed=True,
            failed_metrics=(),
        )

        found = result.get_result(metric=EvalMetric.EXACT_MATCH)

        assert found is exact_result

    def test_get_result_not_found(self):
        result = CompositeEvalResult(
            results=(self._make_result(score=1.0, passed=True, metric=EvalMetric.EXACT_MATCH),),
            overall_score=1.0,
            overall_passed=True,
            failed_metrics=(),
        )

        found = result.get_result(metric=EvalMetric.LENGTH)

        assert found is None

    def test_to_dict_serialization(self):
        result = CompositeEvalResult(
            results=(
                self._make_result(score=1.0, passed=True, metric=EvalMetric.EXACT_MATCH),
                self._make_result(score=0.3, passed=False, metric=EvalMetric.LENGTH),
            ),
            overall_score=0.65,
            overall_passed=True,
            failed_metrics=(EvalMetric.LENGTH,),
        )

        d = result.to_dict()

        assert d["overall_score"] == pytest.approx(0.65)
        assert d["overall_passed"] is True
        assert d["pass_rate"] == pytest.approx(0.5)
        assert d["failed_metrics"] == ["length"]
        assert len(d["results"]) == 2
        assert d["results"][0]["metric"] == "exact_match"
        assert d["results"][1]["passed"] is False


class TestEvalSuite:
    @pytest.mark.asyncio
    async def test_add_case_and_run(self):
        suite = EvalSuite(
            name="basic",
            evaluators=[ExactMatchEvaluator()],
        )
        suite.add_case(
            EvalCase(
                name="greeting",
                output="hello",
                expected="hello",
            )
        )

        result = await suite.run()

        assert result.suite_name == "basic"
        assert result.total_cases == 1
        assert result.passed_cases == 1
        assert result.failed_cases == 0
        assert result.overall_pass_rate == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_add_cases_bulk(self):
        suite = EvalSuite(
            name="bulk",
            evaluators=[ExactMatchEvaluator()],
        )
        suite.add_cases(
            [
                EvalCase(name="case1", output="a", expected="a"),
                EvalCase(name="case2", output="b", expected="b"),
                EvalCase(name="case3", output="c", expected="x"),
            ]
        )

        result = await suite.run()

        assert result.total_cases == 3
        assert result.passed_cases == 2
        assert result.failed_cases == 1
        assert result.overall_pass_rate == pytest.approx(2.0 / 3.0)

    @pytest.mark.asyncio
    async def test_filter_tags(self):
        suite = EvalSuite(
            name="tagged",
            evaluators=[ExactMatchEvaluator()],
        )
        suite.add_cases(
            [
                EvalCase(name="fast1", output="a", expected="a", tags=("fast",)),
                EvalCase(name="slow1", output="b", expected="b", tags=("slow",)),
                EvalCase(name="fast2", output="c", expected="c", tags=("fast",)),
            ]
        )

        result = await suite.run(filter_tags=["fast"])

        assert result.total_cases == 2
        assert result.passed_cases == 2

    @pytest.mark.asyncio
    async def test_filter_tags_no_match(self):
        suite = EvalSuite(
            name="tagged",
            evaluators=[ExactMatchEvaluator()],
        )
        suite.add_case(
            EvalCase(
                name="case1",
                output="a",
                expected="a",
                tags=("fast",),
            )
        )

        result = await suite.run(filter_tags=["nonexistent"])

        assert result.total_cases == 0
        assert result.overall_pass_rate == 0.0

    @pytest.mark.asyncio
    async def test_empty_suite(self):
        suite = EvalSuite(
            name="empty",
            evaluators=[ExactMatchEvaluator()],
        )

        result = await suite.run()

        assert result.total_cases == 0
        assert result.passed_cases == 0
        assert result.failed_cases == 0
        assert result.overall_pass_rate == 0.0

    @pytest.mark.asyncio
    async def test_suite_with_multiple_evaluators(self):
        suite = EvalSuite(
            name="multi",
            evaluators=[
                ExactMatchEvaluator(),
                LengthEvaluator(min_length=1, max_length=10),
            ],
        )
        suite.add_case(
            EvalCase(
                name="match_and_length",
                output="hello",
                expected="hello",
            )
        )

        result = await suite.run()

        assert result.total_cases == 1
        assert result.passed_cases == 1
        # Each case result is a CompositeEvalResult with 2 inner results
        _, case_result = result.case_results[0]
        assert len(case_result.results) == 2

    def test_suite_name_property(self):
        suite = EvalSuite(
            name="my_suite",
            evaluators=[],
        )

        assert suite.name == "my_suite"

    @pytest.mark.asyncio
    async def test_suite_duration_is_positive(self):
        suite = EvalSuite(
            name="timing",
            evaluators=[ExactMatchEvaluator()],
        )
        suite.add_case(EvalCase(name="c", output="a", expected="a"))

        result = await suite.run()

        assert result.duration_ms >= 0.0


class TestEvalSuiteResult:
    @pytest.mark.asyncio
    async def test_to_dict_serialization(self):
        suite = EvalSuite(
            name="serialize_test",
            evaluators=[ExactMatchEvaluator()],
        )
        suite.add_cases(
            [
                EvalCase(name="pass_case", output="yes", expected="yes"),
                EvalCase(name="fail_case", output="no", expected="yes"),
            ]
        )

        result = await suite.run()
        d = result.to_dict()

        assert d["suite_name"] == "serialize_test"
        assert d["total_cases"] == 2
        assert d["passed_cases"] == 1
        assert d["failed_cases"] == 1
        assert d["overall_pass_rate"] == pytest.approx(0.5)
        assert "pass_case" in d["cases"]
        assert "fail_case" in d["cases"]
        assert isinstance(d["cases"]["pass_case"], dict)
        assert d["cases"]["pass_case"]["overall_passed"] is True

    def test_to_dict_empty_suite_result(self):
        result = EvalSuiteResult(
            suite_name="empty",
            case_results=(),
            overall_pass_rate=0.0,
            total_cases=0,
            passed_cases=0,
            failed_cases=0,
            duration_ms=0.0,
        )

        d = result.to_dict()

        assert d["suite_name"] == "empty"
        assert d["cases"] == {}
        assert d["total_cases"] == 0

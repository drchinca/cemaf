"""Tests for algorithm exclusion metadata in selection algorithms."""

from cemaf.context.algorithm import (
    GreedySelectionAlgorithm,
    KnapsackSelectionAlgorithm,
)
from cemaf.context.budget import TokenBudget
from cemaf.context.source import ContextSource
from cemaf.core.enums import ExclusionReason


def _make_source(key: str, tokens: int, priority: int) -> ContextSource:
    """Create a test ContextSource."""
    return ContextSource(
        key=key,
        content=f"content for {key}",
        token_count=tokens,
        priority=priority,
    )


def _budget(available: int) -> TokenBudget:
    """Create a budget with exact available_tokens (no output reserve)."""
    return TokenBudget(max_tokens=available, reserved_for_output=0)


class TestGreedyExclusionDetails:
    """Tests for Greedy algorithm exclusion metadata."""

    def test_no_exclusions_when_all_fit(self) -> None:
        sources = [
            _make_source(key="a", tokens=100, priority=10),
            _make_source(key="b", tokens=100, priority=5),
        ]
        result = GreedySelectionAlgorithm().select_sources(sources=sources, budget=_budget(available=500))
        assert result.metadata["excluded_count"] == 0
        assert result.metadata["excluded_details"] == []
        assert len(result.selected_sources) == 2

    def test_excluded_sources_have_budget_exceeded_reason(self) -> None:
        sources = [
            _make_source(key="a", tokens=80, priority=10),
            _make_source(key="b", tokens=80, priority=5),
            _make_source(key="c", tokens=80, priority=1),
        ]
        result = GreedySelectionAlgorithm().select_sources(sources=sources, budget=_budget(available=150))
        assert result.metadata["excluded_count"] == 2
        details = result.metadata["excluded_details"]
        assert len(details) == 2
        for detail in details:
            assert detail["reason"] == ExclusionReason.BUDGET_EXCEEDED.value
            assert "source_id" in detail
            assert "token_count" in detail
            assert "priority" in detail

    def test_excluded_details_contain_correct_source_info(self) -> None:
        sources = [
            _make_source(key="high", tokens=90, priority=10),
            _make_source(key="low", tokens=90, priority=1),
        ]
        result = GreedySelectionAlgorithm().select_sources(sources=sources, budget=_budget(available=100))
        assert len(result.selected_sources) == 1
        assert result.selected_sources[0].key == "high"
        details = result.metadata["excluded_details"]
        assert len(details) == 1
        assert details[0]["source_id"] == "low"
        assert details[0]["token_count"] == 90
        assert details[0]["priority"] == 1


class TestKnapsackExclusionDetails:
    """Tests for Knapsack algorithm exclusion metadata."""

    def test_no_exclusions_when_all_fit(self) -> None:
        sources = [
            _make_source(key="a", tokens=50, priority=10),
            _make_source(key="b", tokens=50, priority=5),
        ]
        result = KnapsackSelectionAlgorithm().select_sources(sources=sources, budget=_budget(available=200))
        assert result.metadata["excluded_count"] == 0
        assert result.metadata.get("excluded_details", []) == []

    def test_excluded_sources_have_low_priority_reason(self) -> None:
        sources = [
            _make_source(key="high", tokens=80, priority=10),
            _make_source(key="medium", tokens=80, priority=5),
            _make_source(key="low", tokens=80, priority=1),
        ]
        result = KnapsackSelectionAlgorithm().select_sources(sources=sources, budget=_budget(available=160))
        assert result.metadata["excluded_count"] >= 1
        details = result.metadata["excluded_details"]
        assert len(details) >= 1
        for detail in details:
            assert detail["reason"] == ExclusionReason.LOW_PRIORITY.value

    def test_knapsack_selects_optimal_combination(self) -> None:
        sources = [
            _make_source(key="big_low", tokens=100, priority=5),
            _make_source(key="small_high1", tokens=60, priority=8),
            _make_source(key="small_high2", tokens=60, priority=7),
        ]
        result = KnapsackSelectionAlgorithm().select_sources(sources=sources, budget=_budget(available=120))
        selected_keys = {s.key for s in result.selected_sources}
        # Knapsack should pick the two smaller high-priority items (8+7=15 > 5)
        assert "small_high1" in selected_keys
        assert "small_high2" in selected_keys
        assert "big_low" not in selected_keys

    def test_empty_sources(self) -> None:
        result = KnapsackSelectionAlgorithm().select_sources(sources=[], budget=_budget(available=100))
        assert result.total_tokens == 0
        assert len(result.selected_sources) == 0

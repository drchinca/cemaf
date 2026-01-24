"""
TDD Tests for Recovery Error Type Fallback Matching.

Tests verify recovery strategy fallback chain:
1. Exact exception_type match
2. Pattern matching on error message
3. Default strategy as safety net
"""

from cemaf.context.context import Context
from cemaf.core.recovery import AutoHealManager, RecoveryStrategy
from cemaf.core.result import Result


class CountingRecovery(RecoveryStrategy):
    """Recovery strategy that tracks how many times it was called."""

    def __init__(self, name: str):
        self.name = name
        self.call_count = 0

    def recover(self, error_result: Result, context: Context) -> Result[Context]:
        """Increment counter and return success."""
        self.call_count += 1
        return Result.ok(context.set(f"recovered_by_{self.name}", True))


def test_exact_exception_type_match():
    """
    GIVEN: Registered strategy for 'TimeoutError'
    WHEN: Error result has exception_type='TimeoutError'
    THEN: Should use exact match strategy
    """
    manager = AutoHealManager()
    strategy = CountingRecovery("exact")
    manager.register("TimeoutError", strategy)

    error_result = Result.fail("Request timed out", metadata={"exception_type": "TimeoutError"})
    context = Context(data={})

    result = manager.heal(error_result, context)

    assert result.success, "Should successfully heal with exact match"
    assert strategy.call_count == 1, "Should call exact match strategy"


def test_pattern_matching_fallback():
    """
    GIVEN: Pattern strategy registered for "Timeout.*"
    WHEN: Error result has error="TimeoutException: API took 30s"
    AND: No exact exception_type match
    THEN: Should use pattern matching strategy
    """
    manager = AutoHealManager()
    pattern_strategy = CountingRecovery("pattern")
    manager.register_pattern(r"Timeout.*", pattern_strategy)

    error_result = Result.fail("TimeoutException: API took 30s", metadata={})
    context = Context(data={})

    result = manager.heal(error_result, context)

    assert result.success, "Should successfully heal with pattern match"
    assert pattern_strategy.call_count == 1, "Should call pattern strategy"


def test_default_strategy_fallback():
    """
    GIVEN: Default strategy registered
    WHEN: Error has no exception_type and no pattern match
    THEN: Should use default strategy as safety net
    """
    manager = AutoHealManager()
    default_strategy = CountingRecovery("default")
    manager.set_default_strategy(default_strategy)

    error_result = Result.fail("Unknown error", metadata={})
    context = Context(data={})

    result = manager.heal(error_result, context)

    assert result.success, "Should successfully heal with default strategy"
    assert default_strategy.call_count == 1, "Should call default strategy"


def test_fallback_chain_priority():
    """
    GIVEN: Exact strategy, pattern strategy, and default strategy registered
    WHEN: Error has exact exception_type match
    THEN: Should prefer exact match (not pattern or default)
    """
    manager = AutoHealManager()
    exact_strategy = CountingRecovery("exact")
    pattern_strategy = CountingRecovery("pattern")
    default_strategy = CountingRecovery("default")

    manager.register("TimeoutError", exact_strategy)
    manager.register_pattern(r".*", pattern_strategy)  # Matches everything
    manager.set_default_strategy(default_strategy)

    error_result = Result.fail("Request timed out", metadata={"exception_type": "TimeoutError"})
    context = Context(data={})

    result = manager.heal(error_result, context)

    assert result.success
    assert exact_strategy.call_count == 1, "Should use exact match"
    assert pattern_strategy.call_count == 0, "Should not use pattern"
    assert default_strategy.call_count == 0, "Should not use default"


def test_pattern_chain_priority():
    """
    GIVEN: Pattern strategy and default strategy registered
    WHEN: Error has no exception_type but matches pattern
    THEN: Should prefer pattern match (not default)
    """
    manager = AutoHealManager()
    pattern_strategy = CountingRecovery("pattern")
    default_strategy = CountingRecovery("default")

    manager.register_pattern(r"Timeout.*", pattern_strategy)
    manager.set_default_strategy(default_strategy)

    error_result = Result.fail("TimeoutException: API took 30s", metadata={})
    context = Context(data={})

    result = manager.heal(error_result, context)

    assert result.success
    assert pattern_strategy.call_count == 1, "Should use pattern match"
    assert default_strategy.call_count == 0, "Should not use default"


def test_no_recovery_available():
    """
    GIVEN: No strategies registered
    WHEN: Error has no exception_type
    THEN: Should fail gracefully
    """
    manager = AutoHealManager()

    error_result = Result.fail("Unknown error", metadata={})
    context = Context(data={})

    result = manager.heal(error_result, context)

    assert not result.success, "Should fail when no recovery available"


def test_multiple_patterns_first_match_wins():
    """
    GIVEN: Multiple pattern strategies registered
    WHEN: Error matches multiple patterns
    THEN: Should use first matching pattern (order matters)
    """
    manager = AutoHealManager()
    strategy1 = CountingRecovery("pattern1")
    strategy2 = CountingRecovery("pattern2")

    manager.register_pattern(r"Timeout.*", strategy1)
    manager.register_pattern(r".*Error", strategy2)

    error_result = Result.fail("TimeoutError: API took 30s", metadata={})
    context = Context(data={})

    result = manager.heal(error_result, context)

    assert result.success
    assert strategy1.call_count == 1, "First pattern should match"
    assert strategy2.call_count == 0, "Should not try second pattern"

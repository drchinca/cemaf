"""
Tests for the Auto-Heal Manager and autonomous recovery.
"""

from cemaf.context.context import Context
from cemaf.core.recovery import AutoHealManager, RecoveryStrategy
from cemaf.core.result import Result


class MockSummarizeStrategy(RecoveryStrategy):
    """Mock strategy that 'summarizes' context."""

    def recover(self, error_result: Result, context: Context) -> Result[Context]:
        # Simulate summarization by setting a flag
        new_ctx = context.set("summarized", True)
        return Result.ok(new_ctx)


def test_auto_heal_manager_registration():
    """Test registering and retrieving strategies."""
    manager = AutoHealManager()
    strategy = MockSummarizeStrategy()

    manager.register("TokenLimitExceeded", strategy)
    assert manager.get_strategy("TokenLimitExceeded") == strategy
    assert manager.get_strategy("UnknownError") is None


def test_auto_heal_successful_recovery():
    """Test that AutoHealManager can successfully recover from an error."""
    manager = AutoHealManager()
    strategy = MockSummarizeStrategy()
    manager.register("TokenLimitExceeded", strategy)

    error_result = Result.fail("Context too large", metadata={"exception_type": "TokenLimitExceeded"})
    context = Context(data={"raw_data": "very long text..."})

    recovery_result = manager.heal(error_result, context)

    assert recovery_result.success
    assert recovery_result.data.get("summarized") is True
    assert recovery_result.data.get("raw_data") == "very long text..."


def test_auto_heal_no_strategy():
    """Test behavior when no strategy is available for an error."""
    manager = AutoHealManager()
    error_result = Result.fail("Unknown error", metadata={"exception_type": "MysteryError"})
    context = Context()

    recovery_result = manager.heal(error_result, context)

    assert not recovery_result.success
    assert recovery_result.error == "No recovery strategy for MysteryError"

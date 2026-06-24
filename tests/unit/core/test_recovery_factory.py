"""Tests for recovery composition helpers."""

from cemaf.core.recovery import AutoHealManager, create_auto_heal_manager


def test_create_auto_heal_manager_returns_empty_manager() -> None:
    manager = create_auto_heal_manager()

    assert isinstance(manager, AutoHealManager)
    assert manager.get_strategy("TimeoutError") is None

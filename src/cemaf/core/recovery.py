"""
Autonomous recovery and self-healing for CEMAF infrastructure errors.
"""

import re
from abc import ABC, abstractmethod
from typing import Any

from cemaf.context.context import Context
from cemaf.core.result import Result


class RecoveryStrategy(ABC):
    """Base class for all context recovery strategies."""

    @abstractmethod
    def recover(self, error_result: Result[Any], context: Context) -> Result[Context]:
        """
        Attempt to recover from an error by modifying the context.

        Args:
            error_result: The failed result that triggered recovery
            context: The context at the time of failure

        Returns:
            Result[Context]: Success with new context if recovered, failure otherwise
        """
        pass


class AutoHealManager:
    """
    Manages autonomous recovery from infrastructure errors.
    Implements fallback chain: exact match → pattern match → default strategy.
    """

    def __init__(self) -> None:
        self._strategies: dict[str, RecoveryStrategy] = {}
        self._pattern_strategies: list[tuple[str, RecoveryStrategy]] = []
        self._default_strategy: RecoveryStrategy | None = None

    def register(self, error_type: str, strategy: RecoveryStrategy) -> None:
        """Register a recovery strategy for a specific error type (exact match)."""
        self._strategies[error_type] = strategy

    def register_pattern(self, pattern: str, strategy: RecoveryStrategy) -> None:
        """
        Register a recovery strategy for error messages matching a regex pattern.

        Args:
            pattern: Regex pattern to match against error message
            strategy: Recovery strategy to use if pattern matches
        """
        self._pattern_strategies.append((pattern, strategy))

    def set_default_strategy(self, strategy: RecoveryStrategy) -> None:
        """Set the default recovery strategy as a safety net."""
        self._default_strategy = strategy

    def get_strategy(self, error_type: str) -> RecoveryStrategy | None:
        """Get the recovery strategy for an error type (exact match only)."""
        return self._strategies.get(error_type)

    def heal(self, error_result: Result[Any], context: Context) -> Result[Context]:
        """
        Attempt to heal a failure using registered strategies.

        Implements fallback chain:
        1. Try exact exception_type match
        2. Try pattern matching on error message
        3. Try default strategy as safety net
        4. Return failure if none available

        Args:
            error_result: The failed result
            context: The current context

        Returns:
            Result[Context]: Recovered context or failure if no strategy available
        """
        # Step 1: Try exact exception_type match
        error_type = error_result.metadata.get("exception_type")
        if error_type:
            strategy = self.get_strategy(error_type)
            if strategy:
                return strategy.recover(error_result, context)

        # Step 2: Try pattern matching on error message
        if error_result.error:
            for pattern, strategy in self._pattern_strategies:
                if re.match(pattern, error_result.error):
                    return strategy.recover(error_result, context)

        # Step 3: Try default strategy
        if self._default_strategy:
            return self._default_strategy.recover(error_result, context)

        # Step 4: No recovery available
        return Result.fail("No recovery strategy available")

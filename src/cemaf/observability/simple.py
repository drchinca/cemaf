"""
Simple implementations of observability interfaces.

For development/testing - swap with real implementations in production.
"""

import logging
import sys
from typing import Any

from cemaf.core.types import JSON
from cemaf.observability.protocols import Span


class SimpleLogger:
    """Simple stdout logger with structured output."""

    def __init__(
        self,
        name: str = "cemaf",
        level: int = logging.INFO,
        context: JSON | None = None,
    ) -> None:
        self._name = name
        self._level = level
        self._context = context or {}

        # Configure Python logger
        self._logger = logging.getLogger(name)
        self._logger.setLevel(level)

        if not self._logger.handlers:
            handler = logging.StreamHandler(sys.stdout)
            handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
            self._logger.addHandler(handler)

    def _format_kwargs(self, kwargs: dict[str, Any]) -> str:
        """Format kwargs for logging."""
        if not kwargs and not self._context:
            return ""
        all_context = {**self._context, **kwargs}
        pairs = [f"{k}={v}" for k, v in all_context.items()]
        return f" | {', '.join(pairs)}"

    def debug(self, message: str, **kwargs: Any) -> None:
        """Log debug message."""
        self._logger.debug(f"{message}{self._format_kwargs(kwargs)}")

    def info(self, message: str, **kwargs: Any) -> None:
        """Log info message."""
        self._logger.info(f"{message}{self._format_kwargs(kwargs)}")

    def warning(self, message: str, **kwargs: Any) -> None:
        """Log warning message."""
        self._logger.warning(f"{message}{self._format_kwargs(kwargs)}")

    def error(self, message: str, **kwargs: Any) -> None:
        """Log error message."""
        self._logger.error(f"{message}{self._format_kwargs(kwargs)}")

    def with_context(self, **kwargs: Any) -> SimpleLogger:
        """Return logger with additional context."""
        new_context = {**self._context, **kwargs}
        return SimpleLogger(self._name, self._level, new_context)


class NoOpSpan:
    """No-operation span for testing/development."""

    def set_attribute(self, key: str, value: Any) -> None:
        """No-op."""
        pass

    def add_event(self, name: str, attributes: JSON | None = None) -> None:
        """No-op."""
        pass

    def set_status(self, status: str, description: str | None = None) -> None:
        """No-op."""
        pass

    def end(self) -> None:
        """No-op."""
        pass


class NoOpTracer:
    """No-operation tracer for testing/development."""

    def start_span(self, name: str, attributes: JSON | None = None) -> Span:
        """Return no-op span."""
        return NoOpSpan()

    def get_current_span(self) -> Span | None:
        """Return None."""
        return None


class NoOpMetrics:
    """No-operation metrics for testing/development."""

    def counter(self, name: str, value: int = 1, tags: JSON | None = None) -> None:
        """No-op."""
        pass

    def gauge(self, name: str, value: float, tags: JSON | None = None) -> None:
        """No-op."""
        pass

    def histogram(self, name: str, value: float, tags: JSON | None = None) -> None:
        """No-op."""
        pass

    def timing(self, name: str, value_ms: float, tags: JSON | None = None) -> None:
        """No-op."""
        pass

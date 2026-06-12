"""Structured JSON logger for production observability."""

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any, TextIO

from cemaf.core.types import JSON


class StructuredLogger:
    """JSON-lines logger satisfying the Logger protocol."""

    def __init__(
        self,
        *,
        name: str = "cemaf",
        level: int = logging.INFO,
        context: dict[str, Any] | None = None,
        stream: TextIO | None = None,
    ) -> None:
        self._name = name
        self._level = level
        self._context: dict[str, Any] = context or {}
        self._stream = stream if stream is not None else sys.stdout

    def _emit(self, level: int, level_name: str, message: str, args: tuple[Any, ...], kwargs: JSON) -> None:
        """Format and write a single JSON line to stdout."""
        if level < self._level:
            return

        formatted = message % args if args else message

        record: dict[str, Any] = {
            "timestamp": datetime.now(tz=UTC).isoformat(),
            "level": level_name,
            "logger": self._name,
            "message": formatted,
        }

        if self._context:
            record.update(self._context)
        if kwargs:
            record.update(kwargs)

        self._stream.write(json.dumps(obj=record, default=str) + "\n")
        self._stream.flush()

    def debug(self, message: str, *args: Any, **kwargs: Any) -> None:
        """Log debug-level JSON line with lazy % formatting."""
        self._emit(level=logging.DEBUG, level_name="DEBUG", message=message, args=args, kwargs=kwargs)

    def info(self, message: str, *args: Any, **kwargs: Any) -> None:
        """Log info-level JSON line with lazy % formatting."""
        self._emit(level=logging.INFO, level_name="INFO", message=message, args=args, kwargs=kwargs)

    def warning(self, message: str, *args: Any, **kwargs: Any) -> None:
        """Log warning-level JSON line with lazy % formatting."""
        self._emit(level=logging.WARNING, level_name="WARNING", message=message, args=args, kwargs=kwargs)

    def error(self, message: str, *args: Any, **kwargs: Any) -> None:
        """Log error-level JSON line with lazy % formatting."""
        self._emit(level=logging.ERROR, level_name="ERROR", message=message, args=args, kwargs=kwargs)

    def with_context(self, **kwargs: Any) -> StructuredLogger:
        """Return new logger with merged context fields."""
        merged = {**self._context, **kwargs}
        return StructuredLogger(
            name=self._name,
            level=self._level,
            context=merged,
            stream=self._stream,
        )

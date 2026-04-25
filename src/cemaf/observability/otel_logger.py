"""Dual-emit Logger: stdout JSON + OpenTelemetry Logs SDK."""

import json
import sys
from datetime import UTC, datetime
from typing import Any


class OTelLogger:
    """
    Logger that writes JSON lines to stdout and, when an OTel logger is
    provided, also emits structured log records to the OTel Logs SDK.

    Calling with_context() returns a new OTelLogger with merged fields —
    the original is not mutated (value-object pattern).
    """

    def __init__(
        self,
        name: str,
        otel_logger: Any | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        self._name = name
        self._otel_logger = otel_logger
        self._context: dict[str, Any] = context or {}

    def _emit(self, level: str, message: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> None:
        formatted = message % args if args else message

        record: dict[str, Any] = {
            "timestamp": datetime.now(tz=UTC).isoformat(),
            "level": level,
            "logger": self._name,
            "message": formatted,
        }
        if self._context:
            record.update(self._context)
        if kwargs:
            record.update(kwargs)

        sys.stdout.write(json.dumps(record, default=str) + "\n")
        sys.stdout.flush()

        if self._otel_logger is not None:
            self._emit_otel(level=level, body=formatted, attributes=record)

    def _emit_otel(self, level: str, body: str, attributes: dict[str, Any]) -> None:
        """Best-effort OTel log record emission; silently skips on API errors."""
        try:
            from opentelemetry import trace
            from opentelemetry._logs import SeverityNumber

            severity_map = {
                "DEBUG": SeverityNumber.DEBUG,
                "INFO": SeverityNumber.INFO,
                "WARNING": SeverityNumber.WARN,
                "ERROR": SeverityNumber.ERROR,
            }
            severity = severity_map.get(level, SeverityNumber.INFO)

            # Attach current span context if available
            span_ctx = trace.get_current_span().get_span_context()
            self._otel_logger.emit(
                self._otel_logger.create_log_record(
                    body=body,
                    severity_number=severity,
                    attributes={k: str(v) for k, v in attributes.items()},
                    trace_id=span_ctx.trace_id if span_ctx and span_ctx.is_valid else None,
                    span_id=span_ctx.span_id if span_ctx and span_ctx.is_valid else None,
                )
            )
        except Exception:
            pass

    def debug(self, message: str, *args: Any, **kwargs: Any) -> None:
        self._emit("DEBUG", message, args, kwargs)

    def info(self, message: str, *args: Any, **kwargs: Any) -> None:
        self._emit("INFO", message, args, kwargs)

    def warning(self, message: str, *args: Any, **kwargs: Any) -> None:
        self._emit("WARNING", message, args, kwargs)

    def error(self, message: str, *args: Any, **kwargs: Any) -> None:
        self._emit("ERROR", message, args, kwargs)

    def with_context(self, **kwargs: Any) -> OTelLogger:
        return OTelLogger(
            name=self._name,
            otel_logger=self._otel_logger,
            context={**self._context, **kwargs},
        )

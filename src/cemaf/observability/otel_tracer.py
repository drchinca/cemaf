"""
OpenTelemetry Tracer and Span implementations.

Wraps opentelemetry-sdk Tracer. Flattens CEMAF JSON attributes to
OTel scalars. CEMAF semantic conventions:
  cemaf.dag.name, cemaf.node.id, cemaf.node.type,
  cemaf.run.id, cemaf.agent.id
"""

from typing import Any

from cemaf.core.types import JSON


def _require_otel() -> None:
    try:
        import opentelemetry  # noqa: F401
    except ImportError as exc:
        raise ImportError(
            "opentelemetry-sdk is required for OTelTracer. "
            "Install with: uv add opentelemetry-sdk opentelemetry-exporter-otlp-proto-grpc"
        ) from exc


def _flatten_value(value: Any) -> Any:
    """Convert dict/list to JSON string so OTel accepts the attribute."""
    if isinstance(value, (str, int, float, bool)):
        return value
    import json

    try:
        return json.dumps(value, default=str)
    except Exception:
        return str(value)


def _flatten_attributes(attributes: JSON | None) -> dict[str, Any]:
    if not attributes:
        return {}
    return {k: _flatten_value(v) for k, v in attributes.items()}


class OTelSpan:
    """Wraps an opentelemetry.trace.Span, satisfying the CEMAF Span protocol."""

    def __init__(self, span: Any, scope: Any | None = None) -> None:
        self._span = span
        self._scope = scope
        self._ended = False

    def set_attribute(self, key: str, value: Any) -> None:
        self._span.set_attribute(key, _flatten_value(value))

    def add_event(self, name: str, attributes: JSON | None = None) -> None:
        self._span.add_event(name, attributes=_flatten_attributes(attributes))

    def set_status(self, status: str, description: str | None = None) -> None:
        from opentelemetry.trace import StatusCode

        if status.upper() == "OK":
            code = StatusCode.OK
        elif status.upper() == "ERROR":
            code = StatusCode.ERROR
        else:
            code = StatusCode.UNSET
        self._span.set_status(code, description=description or "")

    def end(self) -> None:
        if self._ended:
            return
        self._ended = True
        if self._scope is not None:
            self._scope.__exit__(None, None, None)
        else:
            self._span.end()

    @property
    def _inner(self) -> Any:
        """Access the raw OTel span for advanced use (e.g. context propagation)."""
        return self._span


class OTelTracer:
    """Wraps an opentelemetry.trace.Tracer, satisfying the CEMAF Tracer protocol."""

    def __init__(self, tracer: Any) -> None:
        _require_otel()
        self._tracer = tracer

    def start_span(self, name: str, attributes: JSON | None = None) -> OTelSpan:
        flat = _flatten_attributes(attributes)
        scope = self._tracer.start_as_current_span(name, attributes=flat)
        span = scope.__enter__()
        return OTelSpan(span, scope=scope)

    def get_current_span(self) -> OTelSpan | None:
        from opentelemetry import trace

        span = trace.get_current_span()
        if span is None or not span.is_recording():
            return None
        return OTelSpan(span)

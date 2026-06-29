"""Local OTLP-JSON file span exporter.

Writes finished spans to a local newline-delimited JSON file using the OTel
SDK's standard ``SpanExporter`` contract. Each line is a single OTLP
``ExportTraceServiceRequest`` envelope serialized via the official
``opentelemetry-proto`` definitions, so the output is importable by any
OTLP-aware viewer (Jaeger, Tempo, Honeycomb, etc.) without a collector.

Use for local-first / freemium runs where a gRPC collector is not available.

Typical wiring::

    from cemaf.observability.otlp_file_exporter import configure_otel_to_file

    configure_otel_to_file(
        service_name="meridian-library",
        output_path=Path("/path/to/runs/<run_id>.otlp.jsonl"),
    )
"""

from __future__ import annotations

import os
import threading
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from opentelemetry.sdk.trace import ReadableSpan
    from opentelemetry.sdk.trace.export import SpanExportResult


# Duck-typed against opentelemetry.sdk.trace.export.SpanExporter: matches
# ``export()``, ``force_flush()``, and ``shutdown()`` signatures. Inheritance is
# avoided so the module imports cleanly without the optional 'otel' extra; the
# __init__ helper-error path below surfaces the missing-extra hint when the
# user actually tries to instantiate without it.
class OTLPFileSpanExporter:
    """``SpanExporter`` that writes OTLP-encoded span batches to a JSONL file.

    Each ``export()`` call appends one line containing a single OTLP
    ``ExportTraceServiceRequest`` (one ResourceSpans envelope) serialized to
    JSON. Atomic per-line writes guarded by a process-local lock; safe under
    ``BatchSpanProcessor`` which calls ``export()`` from a worker thread.
    """

    def __init__(self, output_path: Path) -> None:
        try:
            from opentelemetry.exporter.otlp.proto.common.trace_encoder import (
                encode_spans,
            )
            from opentelemetry.sdk.trace.export import (
                SpanExportResult,
            )
        except ImportError as exc:
            raise ImportError(
                "OTLPFileSpanExporter requires the 'otel' extra. Install with: pip install 'cemaf[otel]'."
            ) from exc

        self._encode_spans = encode_spans
        self._SpanExportResult = SpanExportResult
        self._output_path = Path(output_path)
        self._output_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        # Touch the file so consumers can `tail -f` it from a fresh run.
        self._output_path.touch(exist_ok=True)
        self._closed = False

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        if self._closed:
            return self._SpanExportResult.FAILURE
        try:
            from google.protobuf.json_format import MessageToJson  # type: ignore[import-untyped]
        except ImportError:
            return self._SpanExportResult.FAILURE
        try:
            envelope = self._encode_spans(spans)
            # Standard OTLP/JSON uses camelCase field names (the proto JSON
            # default). preserving_proto_field_name=False keeps it spec-aligned
            # so the file imports into any OTLP-aware viewer untransformed.
            json_line = MessageToJson(
                envelope,
                indent=0,
                preserving_proto_field_name=False,
                sort_keys=True,
            )
            # MessageToJson(indent=0) still inserts newlines — collapse to one
            # physical line so each JSONL row is one ExportTraceServiceRequest.
            collapsed = " ".join(json_line.split())
            with (
                self._lock,
                self._output_path.open(
                    mode="a",
                    encoding="utf-8",
                ) as handle,
            ):
                handle.write(collapsed + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            return self._SpanExportResult.SUCCESS
        except Exception:  # noqa: BLE001
            return self._SpanExportResult.FAILURE

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        # File writes are flushed+fsynced on each export() call. Nothing to do.
        return True

    def shutdown(self) -> None:
        self._closed = True


def configure_otel_to_file(
    service_name: str,
    output_path: Path,
    *,
    environment: str = "local",
    sampling_ratio: float = 1.0,
    scope_name: str = "cemaf.observability",
) -> None:
    """Configure the global OTel TracerProvider to write OTLP-JSON to a file.

    Sibling of ``configure_otel`` — same shape, same defaults, but writes to a
    local JSONL file via :class:`OTLPFileSpanExporter` instead of an OTLP gRPC
    collector. Idempotent across calls only within one process (mirrors the
    SDK's TracerProvider semantics).

    Args:
        service_name: Identifies this process in traces (service.name).
        output_path: JSONL file to write OTLP envelopes into. Parent dir is
            created. Appended to.
        environment: deployment.environment resource attribute.
        sampling_ratio: Fraction of traces to sample locally (0.0-1.0).
        scope_name: Default tracer scope name used by callers of get_tracer().

    Raises:
        ImportError: if the 'otel' extra is not installed.
    """
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased
    except ImportError as exc:
        raise ImportError(
            "configure_otel_to_file requires the 'otel' extra. Install with: pip install 'cemaf[otel]'."
        ) from exc

    import importlib.metadata

    try:
        version = importlib.metadata.version("cemaf")
    except importlib.metadata.PackageNotFoundError:
        version = "unknown"

    resource = Resource.create(
        {
            "service.name": service_name,
            "service.version": version,
            "deployment.environment": environment,
        }
    )

    sampler = ParentBased(root=TraceIdRatioBased(sampling_ratio))
    tracer_provider = TracerProvider(resource=resource, sampler=sampler)
    # OTLPFileSpanExporter is duck-typed against SpanExporter (matches
    # export()/force_flush()/shutdown()); BatchSpanProcessor only needs
    # structural conformance at runtime. Cast to Any so the cast holds whether
    # opentelemetry stubs are present (strict-mode mypy with full deps) or
    # absent (pre-commit hook with bare types-only deps).
    exporter = cast(Any, OTLPFileSpanExporter(output_path=output_path))
    tracer_provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(tracer_provider)
    # Pre-acquire the named tracer so callers using get_tracer(scope_name) get
    # one wired to this provider on the first call.
    trace.get_tracer(scope_name, version)


__all__ = ["OTLPFileSpanExporter", "configure_otel_to_file"]

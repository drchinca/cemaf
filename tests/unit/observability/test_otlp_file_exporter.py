"""Tests for OTLPFileSpanExporter — strict OTLP-JSON to a local file.

Proves that spans flushed through ``BatchSpanProcessor + OTLPFileSpanExporter``
produce a JSONL file whose every line is a valid OTLP
``ExportTraceServiceRequest`` (one ResourceSpans envelope per line) carrying
span name, attributes, events, and status. The output is the same shape an
OTLP-aware viewer (Jaeger / Tempo / Honeycomb) consumes — no collector needed.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

try:
    _OTEL_PRESENT = importlib.util.find_spec("opentelemetry.sdk") is not None
except ModuleNotFoundError:
    _OTEL_PRESENT = False


pytestmark = pytest.mark.skipif(not _OTEL_PRESENT, reason="otel extra not installed")


@pytest.fixture
def _isolated_tracer_provider() -> object:
    """Drain any prior global TracerProvider so this test owns the next one."""
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider

    prev = trace.get_tracer_provider()
    if isinstance(prev, TracerProvider):
        prev.shutdown()
    # Reset the OTel SDK's "already set" guard so the next
    # trace.set_tracer_provider() call attaches our provider instead of
    # falling back to the previous one with a warning.
    trace._TRACER_PROVIDER = None  # noqa: SLF001
    # _TRACER_PROVIDER_SET_ONCE is the latch that makes set_tracer_provider a
    # no-op after the first call across the whole process. Resetting both is
    # the only way to give each test a clean global slate.
    from opentelemetry.util._once import Once

    trace._TRACER_PROVIDER_SET_ONCE = Once()  # noqa: SLF001
    yield
    after = trace.get_tracer_provider()
    if isinstance(after, TracerProvider):
        after.shutdown()


def _shutdown(provider: object) -> None:
    """Drain the BatchSpanProcessor — spans aren't flushed until shutdown()."""
    if hasattr(provider, "shutdown"):
        provider.shutdown()


def test_exporter_writes_one_jsonl_line_per_batch(tmp_path: Path) -> None:
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor

    from cemaf.observability.otlp_file_exporter import OTLPFileSpanExporter

    output = tmp_path / "trace.otlp.jsonl"
    provider = TracerProvider(resource=Resource.create({"service.name": "test"}))
    provider.add_span_processor(
        SimpleSpanProcessor(
            OTLPFileSpanExporter(output_path=output),
        )
    )
    tracer = provider.get_tracer("test")

    with tracer.start_as_current_span("cemaf.ingest.run") as root:
        root.set_attribute("cemaf.ingest.run.id", "ingest-test-0001")
        with tracer.start_as_current_span("cemaf.ingest.book") as book:
            book.set_attribute("cemaf.ingest.book.hash", "abc123")
            book.add_event("chunker.fallback_to_ch0", {"reason": "no_heading"})

    _shutdown(provider)

    lines = [line for line in output.read_text().splitlines() if line.strip()]
    assert lines, "exporter wrote nothing"

    # Each line is a single OTLP ExportTraceServiceRequest envelope.
    all_span_names: list[str] = []
    for line in lines:
        envelope = json.loads(line)
        assert "resourceSpans" in envelope, envelope
        for rs in envelope["resourceSpans"]:
            assert any(
                kv["key"] == "service.name" and kv["value"]["stringValue"] == "test"
                for kv in rs["resource"]["attributes"]
            ), "service.name resource attribute missing"
            for ss in rs["scopeSpans"]:
                for span in ss["spans"]:
                    all_span_names.append(span["name"])

    assert "cemaf.ingest.run" in all_span_names
    assert "cemaf.ingest.book" in all_span_names


def test_exporter_preserves_attributes_and_events(tmp_path: Path) -> None:
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor

    from cemaf.observability.otlp_file_exporter import OTLPFileSpanExporter

    output = tmp_path / "trace.otlp.jsonl"
    provider = TracerProvider(resource=Resource.create({"service.name": "test"}))
    provider.add_span_processor(
        SimpleSpanProcessor(
            OTLPFileSpanExporter(output_path=output),
        )
    )
    tracer = provider.get_tracer("test")

    with tracer.start_as_current_span("op") as span:
        span.set_attribute("cemaf.ingest.book.hash", "deadbeef")
        span.set_attribute("cemaf.ingest.chunk.count", 42)
        span.add_event("bm25.commit", {"chunks_added": 42, "atomic_swap": True})

    _shutdown(provider)

    envelope = json.loads(output.read_text().splitlines()[0])
    span_proto = envelope["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
    attrs = {kv["key"]: kv["value"] for kv in span_proto["attributes"]}
    assert attrs["cemaf.ingest.book.hash"] == {"stringValue": "deadbeef"}
    assert attrs["cemaf.ingest.chunk.count"]["intValue"] == "42"

    events = span_proto["events"]
    assert len(events) == 1
    assert events[0]["name"] == "bm25.commit"
    event_attrs = {kv["key"]: kv["value"] for kv in events[0]["attributes"]}
    assert event_attrs["chunks_added"]["intValue"] == "42"
    assert event_attrs["atomic_swap"]["boolValue"] is True


def test_exporter_records_error_status(tmp_path: Path) -> None:
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.trace import Status, StatusCode

    from cemaf.observability.otlp_file_exporter import OTLPFileSpanExporter

    output = tmp_path / "trace.otlp.jsonl"
    provider = TracerProvider(resource=Resource.create({"service.name": "test"}))
    provider.add_span_processor(
        SimpleSpanProcessor(
            OTLPFileSpanExporter(output_path=output),
        )
    )
    tracer = provider.get_tracer("test")

    with tracer.start_as_current_span("op") as span:
        span.set_status(Status(StatusCode.ERROR, "boom"))

    _shutdown(provider)

    envelope = json.loads(output.read_text().splitlines()[0])
    span_proto = envelope["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
    # OTLP error code = STATUS_CODE_ERROR (2).
    assert span_proto["status"]["code"] == "STATUS_CODE_ERROR"
    assert span_proto["status"]["message"] == "boom"


def test_configure_otel_to_file_writes_through_global_tracer(
    tmp_path: Path,
    _isolated_tracer_provider: object,
) -> None:
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider

    from cemaf.observability.otlp_file_exporter import configure_otel_to_file

    output = tmp_path / "trace.otlp.jsonl"
    configure_otel_to_file(
        service_name="cemaf-otlp-file-test",
        output_path=output,
        environment="test",
        sampling_ratio=1.0,
    )
    provider = trace.get_tracer_provider()
    assert isinstance(provider, TracerProvider)

    tracer = trace.get_tracer("cemaf.observability")
    with tracer.start_as_current_span("cemaf.ingest.run") as root:
        root.set_attribute("cemaf.ingest.run.id", "ingest-via-config")

    provider.shutdown()  # drain BatchSpanProcessor

    assert output.exists()
    content = output.read_text().strip()
    assert content, "configure_otel_to_file produced empty trace file"
    envelope = json.loads(content.splitlines()[-1])
    span_proto = envelope["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
    assert span_proto["name"] == "cemaf.ingest.run"
    attrs = {kv["key"]: kv["value"] for kv in span_proto["attributes"]}
    assert attrs["cemaf.ingest.run.id"] == {"stringValue": "ingest-via-config"}


def test_exporter_error_message_points_at_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    """When OTel is absent the ImportError names the 'otel' extra (DX)."""
    import builtins

    from cemaf.observability.otlp_file_exporter import OTLPFileSpanExporter

    real_import = builtins.__import__

    def _blocked(name: str, *args: object, **kwargs: object) -> object:
        if name.startswith("opentelemetry"):
            raise ImportError(f"blocked {name}")
        return real_import(name, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(builtins, "__import__", _blocked)
    with pytest.raises(ImportError, match=r"cemaf\[otel\]"):
        OTLPFileSpanExporter(output_path=Path("/tmp/x.jsonl"))

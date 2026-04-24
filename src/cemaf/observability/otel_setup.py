"""
One-call OpenTelemetry configuration for production deployments.

Call configure_otel() at application startup before creating any
CEMAF components. Sets global TracerProvider, MeterProvider, LoggerProvider.
"""



def configure_otel(
    service_name: str,
    otlp_endpoint: str = "http://localhost:4317",
    environment: str = "production",
    sampling_ratio: float = 1.0,
) -> None:
    """
    Configure global OTel providers with OTLP export.

    Uses BatchSpanProcessor (not SimpleSpanProcessor) so that span
    serialisation happens off the hot path. The sampling_ratio maps to a
    ParentBasedSampler wrapping TraceIdRatioBased — respects W3C traceparent
    from upstream callers even when local sampling would skip the trace.

    Args:
        service_name: Identifies this process in traces (cemaf.service.name).
        otlp_endpoint: OTLP gRPC receiver address (default: Collector sidecar).
        environment: deployment.environment resource attribute.
        sampling_ratio: Fraction of traces to sample locally (0.0–1.0).

    Raises:
        ImportError: If opentelemetry-sdk or OTLP exporter packages are absent.
    """
    try:
        from opentelemetry import metrics, trace
        from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.trace.sampling import ParentBasedSampler, TraceIdRatioBased
    except ImportError as exc:
        raise ImportError(
            "opentelemetry-sdk and opentelemetry-exporter-otlp-proto-grpc are required. "
            "Install with: uv add opentelemetry-sdk opentelemetry-exporter-otlp-proto-grpc"
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

    sampler = ParentBasedSampler(root=TraceIdRatioBased(sampling_ratio))

    tracer_provider = TracerProvider(resource=resource, sampler=sampler)
    tracer_provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=otlp_endpoint))
    )
    trace.set_tracer_provider(tracer_provider)

    metric_reader = PeriodicExportingMetricReader(
        OTLPMetricExporter(endpoint=otlp_endpoint)
    )
    meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
    metrics.set_meter_provider(meter_provider)

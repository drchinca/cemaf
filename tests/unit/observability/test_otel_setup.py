"""Tests for configure_otel — proves the 'otel' extra makes export setup work.

configure_otel imports opentelemetry-sdk + the OTLP exporter; before the `otel`
optional-extra existed, `pip install cemaf[all]` shipped it import-broken. These
tests skip cleanly when the extra is absent (CI without [otel]) and assert real
provider wiring when present.
"""

from __future__ import annotations

import importlib.util

import pytest

from cemaf.observability.otel_setup import configure_otel

# find_spec on a dotted path raises if the parent package is absent entirely
_OTEL_PRESENT = (
    importlib.util.find_spec("opentelemetry") is not None
    and importlib.util.find_spec("opentelemetry.sdk") is not None
)


@pytest.mark.skipif(not _OTEL_PRESENT, reason="otel extra not installed")
def test_configure_otel_sets_global_providers() -> None:
    from opentelemetry import metrics, trace
    from opentelemetry.sdk.trace import TracerProvider

    configure_otel(
        service_name="cemaf-test",
        otlp_endpoint="http://localhost:4317",
        environment="test",
        sampling_ratio=1.0,
    )

    # Real SDK providers are now installed (not the no-op API defaults).
    assert isinstance(trace.get_tracer_provider(), TracerProvider)
    assert metrics.get_meter_provider() is not None
    # A tracer from the configured provider is usable.
    tracer = trace.get_tracer("cemaf-test")
    with tracer.start_as_current_span("smoke") as span:
        assert span is not None

    # Shut down the provider so its background exporter thread doesn't outlive the
    # test trying to reach a non-existent collector at localhost:4317.
    provider = trace.get_tracer_provider()
    if isinstance(provider, TracerProvider):
        provider.shutdown()


def test_configure_otel_error_message_points_at_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    """When OTel is absent, the ImportError names the 'otel' extra (DX)."""
    import builtins

    real_import = builtins.__import__

    def _blocked(name: str, *args: object, **kwargs: object) -> object:
        if name.startswith("opentelemetry"):
            raise ImportError(f"blocked {name}")
        return real_import(name, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(builtins, "__import__", _blocked)
    with pytest.raises(ImportError, match=r"cemaf\[otel\]"):
        configure_otel(service_name="x")

"""Tests for observability factory functions."""

from pathlib import Path

import pytest

from cemaf.observability.budget_guard import BudgetGuard
from cemaf.observability.factories import (
    create_budget_guard,
    create_logger,
    create_logger_from_config,
    create_metrics_collector,
    create_metrics_collector_from_config,
    create_run_logger,
    create_run_logger_from_config,
    create_tracer,
    create_tracer_from_config,
    logger_registry,
    metrics_collector_registry,
    run_logger_registry,
    tracer_registry,
)
from cemaf.observability.run_logger import FileRunLogger, NoOpRunLogger, RunRecord
from cemaf.observability.simple import NoOpMetrics, NoOpTracer
from cemaf.observability.structured import StructuredLogger


class TestCreateRunLogger:
    def test_file_backend_returns_file_run_logger(self, tmp_path: Path) -> None:
        logger = create_run_logger(backend="file", root=tmp_path)

        assert isinstance(logger, FileRunLogger)
        assert logger.get_run_dir("run-123").parent == tmp_path

    def test_file_backend_requires_root(self) -> None:
        with pytest.raises(ValueError, match="root is required"):
            create_run_logger(backend="file")

    def test_file_backend_returns_noop_when_disabled(self, tmp_path: Path) -> None:
        logger = create_run_logger(backend="file", enable_recording=False, root=tmp_path)

        assert isinstance(logger, NoOpRunLogger)


class TestCreateRunLoggerFromConfig:
    def test_file_backend_uses_env_root(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("CEMAF_OBSERVABILITY_RUN_LOGGER_BACKEND", "file")
        monkeypatch.setenv("CEMAF_OBSERVABILITY_RUN_LOGGER_ROOT", str(tmp_path))

        logger = create_run_logger_from_config()

        assert isinstance(logger, FileRunLogger)
        assert logger.get_run_dir("run-456").parent == tmp_path


def test_create_budget_guard_uses_explicit_thresholds() -> None:
    guard = create_budget_guard(max_total_tokens=123, warning_threshold=0.5, critical_threshold=0.8)

    assert isinstance(guard, BudgetGuard)
    alert = guard.record_usage(tokens=70)
    assert alert is not None
    assert alert.level.value == "warning"


def test_create_logger_supports_structured_backend() -> None:
    logger = create_logger(backend="structured", level="INFO")

    assert isinstance(logger, StructuredLogger)


def test_create_tracer_supports_noop_backend() -> None:
    tracer = create_tracer()

    assert isinstance(tracer, NoOpTracer)


def test_create_metrics_collector_supports_noop_backend() -> None:
    metrics = create_metrics_collector()

    assert isinstance(metrics, NoOpMetrics)


def test_register_custom_logger_backend() -> None:
    captured: dict[str, object] = {}

    class CustomLogger:
        def debug(self, message: str, *args: object, **kwargs: object) -> None:
            pass

        def info(self, message: str, *args: object, **kwargs: object) -> None:
            pass

        def warning(self, message: str, *args: object, **kwargs: object) -> None:
            pass

        def error(self, message: str, *args: object, **kwargs: object) -> None:
            pass

        def with_context(self, **kwargs: object) -> CustomLogger:
            return self

    def factory(**kwargs: object) -> CustomLogger:
        captured.update(kwargs)
        return CustomLogger()

    logger_registry.register(backend="unit-custom-logger", factory=factory)

    logger = create_logger(backend="unit-custom-logger", level="DEBUG", tenant_id="tenant-1")

    assert isinstance(logger, CustomLogger)
    assert captured["level"] == "DEBUG"
    assert captured["tenant_id"] == "tenant-1"


def test_create_registered_logger_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class EnvLogger:
        def debug(self, message: str, *args: object, **kwargs: object) -> None:
            pass

        def info(self, message: str, *args: object, **kwargs: object) -> None:
            pass

        def warning(self, message: str, *args: object, **kwargs: object) -> None:
            pass

        def error(self, message: str, *args: object, **kwargs: object) -> None:
            pass

        def with_context(self, **kwargs: object) -> EnvLogger:
            return self

    def factory(**kwargs: object) -> EnvLogger:
        captured.update(kwargs)
        return EnvLogger()

    logger_registry.register(backend="env-custom-logger", factory=factory)
    monkeypatch.setenv("CEMAF_OBSERVABILITY_LOGGER_BACKEND", "env-custom-logger")
    monkeypatch.setenv("CEMAF_OBSERVABILITY_LOG_LEVEL", "ERROR")

    logger = create_logger_from_config()

    assert isinstance(logger, EnvLogger)
    assert captured["level"] == "ERROR"


def test_register_custom_tracer_backend() -> None:
    class CustomTracer:
        def start_span(self, name: str, attributes: object | None = None) -> object:
            return object()

        def get_current_span(self) -> object | None:
            return None

    tracer = CustomTracer()
    tracer_registry.register(backend="unit-custom-tracer", factory=lambda **_: tracer)

    assert create_tracer(backend="unit-custom-tracer") is tracer


def test_create_registered_tracer_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    class EnvTracer:
        def start_span(self, name: str, attributes: object | None = None) -> object:
            return object()

        def get_current_span(self) -> object | None:
            return None

    tracer = EnvTracer()
    tracer_registry.register(backend="env-custom-tracer", factory=lambda **_: tracer)
    monkeypatch.setenv("CEMAF_OBSERVABILITY_TRACER_BACKEND", "env-custom-tracer")

    assert create_tracer_from_config() is tracer


def test_register_custom_metrics_backend() -> None:
    captured: dict[str, object] = {}

    class CustomMetrics:
        def counter(self, name: str, value: int = 1, tags: object | None = None) -> None:
            pass

        def gauge(self, name: str, value: float, tags: object | None = None) -> None:
            pass

        def histogram(self, name: str, value: float, tags: object | None = None) -> None:
            pass

        def timing(self, name: str, value_ms: float, tags: object | None = None) -> None:
            pass

    def factory(**kwargs: object) -> CustomMetrics:
        captured.update(kwargs)
        return CustomMetrics()

    metrics_collector_registry.register(backend="unit-custom-metrics", factory=factory)

    metrics = create_metrics_collector(backend="unit-custom-metrics", prefix="custom")

    assert isinstance(metrics, CustomMetrics)
    assert captured["prefix"] == "custom"


def test_create_registered_metrics_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class EnvMetrics:
        def counter(self, name: str, value: int = 1, tags: object | None = None) -> None:
            pass

        def gauge(self, name: str, value: float, tags: object | None = None) -> None:
            pass

        def histogram(self, name: str, value: float, tags: object | None = None) -> None:
            pass

        def timing(self, name: str, value_ms: float, tags: object | None = None) -> None:
            pass

    def factory(**kwargs: object) -> EnvMetrics:
        captured.update(kwargs)
        return EnvMetrics()

    metrics_collector_registry.register(backend="env-custom-metrics", factory=factory)
    monkeypatch.setenv("CEMAF_OBSERVABILITY_METRICS_BACKEND", "env-custom-metrics")
    monkeypatch.setenv("CEMAF_OBSERVABILITY_METRICS_PREFIX", "envprefix")

    metrics = create_metrics_collector_from_config()

    assert isinstance(metrics, EnvMetrics)
    assert captured["prefix"] == "envprefix"


def test_register_custom_run_logger_backend() -> None:
    captured: dict[str, object] = {}

    class CustomRunLogger:
        def start_run(self, run_id: str, **kwargs: object) -> None:
            pass

        def end_run(self, **kwargs: object) -> RunRecord | None:
            return None

        def get_current_record(self) -> RunRecord | None:
            return None

    def factory(**kwargs: object) -> CustomRunLogger:
        captured.update(kwargs)
        return CustomRunLogger()

    run_logger_registry.register(backend="unit-custom-run-logger", factory=factory)

    logger = create_run_logger(
        backend="unit-custom-run-logger",
        enable_recording=False,
        root="/tmp/cemaf-runs",
    )

    assert isinstance(logger, CustomRunLogger)
    assert captured["enable_recording"] is False
    assert captured["root"] == "/tmp/cemaf-runs"


def test_create_registered_run_logger_from_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    class EnvRunLogger:
        def start_run(self, run_id: str, **kwargs: object) -> None:
            pass

        def end_run(self, **kwargs: object) -> RunRecord | None:
            return None

        def get_current_record(self) -> RunRecord | None:
            return None

    def factory(**kwargs: object) -> EnvRunLogger:
        captured.update(kwargs)
        return EnvRunLogger()

    run_logger_registry.register(backend="env-custom-run-logger", factory=factory)
    monkeypatch.setenv("CEMAF_OBSERVABILITY_RUN_LOGGER_BACKEND", "env-custom-run-logger")
    monkeypatch.setenv("CEMAF_OBSERVABILITY_ENABLE_RUN_RECORDING", "false")
    monkeypatch.setenv("CEMAF_OBSERVABILITY_RUN_LOGGER_ROOT", str(tmp_path))

    logger = create_run_logger_from_config()

    assert isinstance(logger, EnvRunLogger)
    assert captured["enable_recording"] is False
    assert captured["root"] == str(tmp_path)


def test_unknown_observability_backends_name_registries() -> None:
    with pytest.raises(ValueError, match="logger_registry.register"):
        create_logger(backend="missing-logger")
    with pytest.raises(ValueError, match="tracer_registry.register"):
        create_tracer(backend="missing-tracer")
    with pytest.raises(ValueError, match="metrics_collector_registry.register"):
        create_metrics_collector(backend="missing-metrics")
    with pytest.raises(ValueError, match="run_logger_registry.register"):
        create_run_logger(backend="missing-run-logger")

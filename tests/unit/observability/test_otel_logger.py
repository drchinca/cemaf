"""Tests for OpenTelemetry logger diagnostics."""

import json

from cemaf.observability.otel_logger import OTelLogger


class _FailingOTelLogger:
    def create_log_record(self, **kwargs: object) -> object:
        raise RuntimeError("otel unavailable")

    def emit(self, record: object) -> None:
        raise AssertionError("emit should not run after create_log_record fails")


def test_otel_logger_reports_emit_failures_to_stderr(capsys) -> None:  # noqa: ANN001
    logger = OTelLogger(name="cemaf-test", otel_logger=_FailingOTelLogger())

    logger.info("hello %s", "world")

    captured = capsys.readouterr()
    stdout = json.loads(captured.out)
    stderr = json.loads(captured.err)

    assert stdout["message"] == "hello world"
    assert stderr["message"] == "OpenTelemetry log emit failed"
    assert stderr["error_type"] == "RuntimeError"
    assert stderr["error"] == "otel unavailable"
    assert isinstance(logger.last_otel_error, RuntimeError)

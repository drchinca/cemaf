"""Tests for observability factory functions."""

from pathlib import Path

import pytest

from cemaf.observability.budget_guard import BudgetGuard
from cemaf.observability.factories import (
    create_budget_guard,
    create_run_logger,
    create_run_logger_from_config,
)
from cemaf.observability.run_logger import FileRunLogger, NoOpRunLogger


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

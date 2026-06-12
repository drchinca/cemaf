"""Types for the failure-feedback iteration loop (SPEC-08 §2)."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import timedelta
from enum import StrEnum
from typing import Any

from cemaf.core.result import Result

UNKNOWN_SUMMARY_MAX_CHARS = 512


class FailureKind(StrEnum):
    TEST_FAILURE = "test_failure"
    LINT_FAILURE = "lint_failure"
    TYPE_FAILURE = "type_failure"
    BUILD_FAILURE = "build_failure"
    RUNTIME_ERROR = "runtime_error"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class FailureItem:
    file: str | None
    line: int | None
    rule: str | None
    message: str
    snippet: str | None = None


@dataclass(frozen=True, slots=True)
class FailureSignal:
    kind: FailureKind
    summary: str
    items: tuple[FailureItem, ...]
    raw_command: str
    exit_code: int
    truncated: bool = False
    metadata: Mapping[str, str] = field(default_factory=lambda: {})


@dataclass(frozen=True, slots=True)
class IterationLimits:
    max_attempts: int = 5
    max_total: timedelta = timedelta(minutes=10)
    max_cost_usd: float = 1.00


class IterationOutcome(StrEnum):
    SUCCESS = "success"
    EXHAUSTED = "exhausted"
    BUDGET_EXCEEDED = "budget_exceeded"
    HALTED = "halted"


@dataclass(frozen=True, slots=True)
class IterationReport:
    outcome: IterationOutcome
    attempts: int
    total_duration_ms: float
    total_cost_usd: float
    last_signal: FailureSignal | None
    final_result: Result[Any] | None


@dataclass(frozen=True, slots=True)
class HaltSignal:
    event: asyncio.Event

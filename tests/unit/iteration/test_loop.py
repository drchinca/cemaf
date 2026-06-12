"""IterationLoop tests — covers all 15 SPEC-08 §4 scenarios."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any

import pytest

from cemaf.core.result import Result
from cemaf.iteration.loop import IterationLoop
from cemaf.iteration.parsers import (
    MypyParser,
    PytestParser,
    RuffParser,
    ShellFallbackParser,
)
from cemaf.iteration.types import (
    FailureKind,
    FailureSignal,
    HaltSignal,
    IterationLimits,
    IterationOutcome,
)
from cemaf.sandbox.shell import ShellResult


def _shell(*, stdout: str = "", stderr: str = "", command: str = "cmd", exit_code: int = 1) -> ShellResult:
    return ShellResult(command=command, exit_code=exit_code, stdout=stdout, stderr=stderr)


def _ok(cost: float = 0.0) -> Result[Any]:
    return Result.ok(data="artefact", metadata={"cost_usd": cost})


def _scripted_attempt(
    *outcomes: Result[Any],
) -> Callable[[FailureSignal | None], Awaitable[Result[Any]]]:
    """Returns an attempt callable that yields outcomes in order, recording calls."""
    state: dict[str, Any] = {"calls": [], "i": 0}

    async def call(signal: FailureSignal | None) -> Result[Any]:
        state["calls"].append(signal)
        idx = state["i"]
        state["i"] += 1
        return outcomes[idx]

    call.state = state  # type: ignore[attr-defined]
    return call


def _scripted_verify(
    *results: ShellResult,
) -> Callable[[Result[Any]], Awaitable[ShellResult]]:
    state = {"i": 0}

    async def call(_: Result[Any]) -> ShellResult:
        idx = state["i"]
        state["i"] += 1
        return results[idx]

    return call


class TestIterationLoop:
    @pytest.mark.asyncio
    async def test_first_attempt_succeeds(self) -> None:
        attempt = _scripted_attempt(_ok())
        verify = _scripted_verify(ShellResult(command="pytest", exit_code=0))
        loop = IterationLoop(
            attempt=attempt,
            verify=verify,
            parsers=(),
            limits=IterationLimits(max_attempts=3, max_cost_usd=10.0),
        )
        report = await loop.run()
        assert report.outcome is IterationOutcome.SUCCESS
        assert report.attempts == 1
        assert attempt.state["calls"] == [None]  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_pytest_failure_feeds_back(self) -> None:
        attempt = _scripted_attempt(_ok(), _ok())
        verify = _scripted_verify(
            _shell(stdout="FAILED tests/x.py::test_a - assert 1 == 2", command="pytest"),
            ShellResult(command="pytest", exit_code=0),
        )
        loop = IterationLoop(
            attempt=attempt,
            verify=verify,
            parsers=(PytestParser(),),
            limits=IterationLimits(max_attempts=3, max_cost_usd=10.0),
        )
        report = await loop.run()
        assert report.outcome is IterationOutcome.SUCCESS
        # second call to attempt received the FailureSignal
        assert attempt.state["calls"][1].kind is FailureKind.TEST_FAILURE  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_ruff_failure_feeds_back(self) -> None:
        attempt = _scripted_attempt(_ok(), _ok())
        verify = _scripted_verify(
            _shell(stdout="src/foo.py:1:1: F401 unused\n", command="ruff check ."),
            ShellResult(command="ruff", exit_code=0),
        )
        loop = IterationLoop(
            attempt=attempt,
            verify=verify,
            parsers=(RuffParser(),),
            limits=IterationLimits(max_attempts=3, max_cost_usd=10.0),
        )
        report = await loop.run()
        assert report.outcome is IterationOutcome.SUCCESS
        signal = attempt.state["calls"][1]  # type: ignore[attr-defined]
        assert signal.kind is FailureKind.LINT_FAILURE
        assert signal.items[0].rule == "F401"

    @pytest.mark.asyncio
    async def test_mypy_failure_feeds_back(self) -> None:
        attempt = _scripted_attempt(_ok(), _ok())
        verify = _scripted_verify(
            _shell(stdout="src/foo.py:12: error: bad [assignment]", command="mypy src/"),
            ShellResult(command="mypy", exit_code=0),
        )
        loop = IterationLoop(
            attempt=attempt,
            verify=verify,
            parsers=(MypyParser(),),
            limits=IterationLimits(max_attempts=3, max_cost_usd=10.0),
        )
        report = await loop.run()
        signal = attempt.state["calls"][1]  # type: ignore[attr-defined]
        assert signal.items[0].file == "src/foo.py"
        assert signal.items[0].line == 12
        assert signal.kind is FailureKind.TYPE_FAILURE
        assert report.outcome is IterationOutcome.SUCCESS

    @pytest.mark.asyncio
    async def test_max_attempts_exhausted(self) -> None:
        attempt = _scripted_attempt(_ok(), _ok())
        verify = _scripted_verify(
            _shell(stdout="FAILED tests/a.py::test - boom", command="pytest"),
            _shell(stdout="FAILED tests/a.py::test - boom", command="pytest"),
        )
        loop = IterationLoop(
            attempt=attempt,
            verify=verify,
            parsers=(PytestParser(),),
            limits=IterationLimits(max_attempts=2, max_cost_usd=10.0),
        )
        report = await loop.run()
        assert report.outcome is IterationOutcome.EXHAUSTED
        assert report.attempts == 2
        assert report.last_signal is not None

    @pytest.mark.asyncio
    async def test_cost_budget_gates_before_next_attempt(self) -> None:
        attempt = _scripted_attempt(_ok(cost=0.06), _ok(cost=0.06))
        verify = _scripted_verify(
            _shell(stdout="FAILED tests/x.py::t - boom", command="pytest"),
            _shell(stdout="FAILED tests/x.py::t - boom", command="pytest"),
        )
        loop = IterationLoop(
            attempt=attempt,
            verify=verify,
            parsers=(PytestParser(),),
            limits=IterationLimits(max_attempts=5, max_cost_usd=0.10),
        )
        report = await loop.run()
        assert report.outcome is IterationOutcome.BUDGET_EXCEEDED
        assert report.attempts == 1
        assert report.total_cost_usd == pytest.approx(0.06)

    @pytest.mark.asyncio
    async def test_time_budget_exceeded(self) -> None:
        async def slow_attempt(_: FailureSignal | None) -> Result[Any]:
            await asyncio.sleep(0.05)
            return _ok()

        async def fail_verify(_: Result[Any]) -> ShellResult:
            return _shell(stdout="FAILED tests/x.py::t - boom", command="pytest")

        loop = IterationLoop(
            attempt=slow_attempt,
            verify=fail_verify,
            parsers=(PytestParser(),),
            limits=IterationLimits(max_attempts=10, max_cost_usd=10.0, max_total=timedelta(milliseconds=80)),
        )
        report = await loop.run()
        assert report.outcome is IterationOutcome.BUDGET_EXCEEDED
        assert report.attempts >= 1

    @pytest.mark.asyncio
    async def test_unknown_kind_when_no_parser_matches(self) -> None:
        attempt = _scripted_attempt(_ok())
        verify = _scripted_verify(_shell(stderr="weird crash", command="weird"))
        loop = IterationLoop(
            attempt=attempt,
            verify=verify,
            parsers=(PytestParser(),),  # won't match
            limits=IterationLimits(max_attempts=1, max_cost_usd=10.0),
        )
        report = await loop.run()
        assert report.outcome is IterationOutcome.EXHAUSTED
        assert report.last_signal is not None
        assert report.last_signal.kind is FailureKind.UNKNOWN
        assert "weird crash" in report.last_signal.summary

    @pytest.mark.asyncio
    async def test_truncation_marks_signal(self) -> None:
        attempt = _scripted_attempt(_ok(), _ok())
        many_fails = "\n".join(f"FAILED tests/x.py::t{i} - assert {i} == 0" for i in range(50))
        verify = _scripted_verify(
            _shell(stdout=many_fails, command="pytest"),
            ShellResult(command="pytest", exit_code=0),
        )
        loop = IterationLoop(
            attempt=attempt,
            verify=verify,
            parsers=(PytestParser(max_items=10),),
            limits=IterationLimits(max_attempts=2, max_cost_usd=10.0),
        )
        report = await loop.run()
        signal = attempt.state["calls"][1]  # type: ignore[attr-defined]
        assert signal.truncated is True
        assert len(signal.items) == 10
        assert report.outcome is IterationOutcome.SUCCESS

    @pytest.mark.asyncio
    async def test_halt_between_attempts(self) -> None:
        halt_event = asyncio.Event()
        calls: list[FailureSignal | None] = []

        async def attempt(signal: FailureSignal | None) -> Result[Any]:
            calls.append(signal)
            if len(calls) == 2:
                halt_event.set()  # halt before attempt 3
            return _ok()

        verify = _scripted_verify(
            _shell(stdout="FAILED tests/x.py::t - boom", command="pytest"),
            _shell(stdout="FAILED tests/x.py::t - boom", command="pytest"),
        )
        loop = IterationLoop(
            attempt=attempt,
            verify=verify,
            parsers=(PytestParser(),),
            limits=IterationLimits(max_attempts=10, max_cost_usd=10.0),
            halt=HaltSignal(event=halt_event),
        )
        report = await loop.run()
        assert report.outcome is IterationOutcome.HALTED
        assert report.attempts == 2

    @pytest.mark.asyncio
    async def test_specificity_wins_over_registration_order(self) -> None:
        attempt = _scripted_attempt(_ok())
        verify = _scripted_verify(
            _shell(stdout="FAILED tests/x.py::t - boom", command="pytest"),
        )
        loop = IterationLoop(
            attempt=attempt,
            verify=verify,
            parsers=(ShellFallbackParser(), PytestParser()),  # generic first
            limits=IterationLimits(max_attempts=1, max_cost_usd=10.0),
        )
        report = await loop.run()
        assert report.last_signal is not None
        assert report.last_signal.kind is FailureKind.TEST_FAILURE  # pytest, not UNKNOWN

    @pytest.mark.asyncio
    async def test_exception_passthrough(self) -> None:
        async def raising(_: FailureSignal | None) -> Result[Any]:
            raise ValueError("agent broke")

        loop = IterationLoop(
            attempt=raising,
            verify=_scripted_verify(),
            parsers=(),
            limits=IterationLimits(max_attempts=3, max_cost_usd=10.0),
        )
        with pytest.raises(ValueError, match="agent broke"):
            await loop.run()

    @pytest.mark.asyncio
    async def test_verifier_raise_becomes_unknown(self) -> None:
        attempt = _scripted_attempt(_ok(), _ok())

        state = {"i": 0}

        async def verify(_: Result[Any]) -> ShellResult:
            state["i"] += 1
            if state["i"] == 1:
                raise RuntimeError("infra hiccup")
            return ShellResult(command="pytest", exit_code=0)

        loop = IterationLoop(
            attempt=attempt,
            verify=verify,
            parsers=(PytestParser(),),
            limits=IterationLimits(max_attempts=3, max_cost_usd=10.0),
        )
        report = await loop.run()
        # second attempt should have received UNKNOWN signal from verify failure
        signal = attempt.state["calls"][1]  # type: ignore[attr-defined]
        assert signal.kind is FailureKind.UNKNOWN
        assert "infra hiccup" in signal.summary
        assert report.outcome is IterationOutcome.SUCCESS

    @pytest.mark.asyncio
    async def test_halt_set_before_attempt_zero(self) -> None:
        halt_event = asyncio.Event()
        halt_event.set()
        calls: list[FailureSignal | None] = []

        async def attempt(signal: FailureSignal | None) -> Result[Any]:
            calls.append(signal)
            return _ok()

        loop = IterationLoop(
            attempt=attempt,
            verify=_scripted_verify(),
            parsers=(),
            limits=IterationLimits(max_attempts=3, max_cost_usd=10.0),
            halt=HaltSignal(event=halt_event),
        )
        report = await loop.run()
        assert report.outcome is IterationOutcome.HALTED
        assert report.attempts == 0
        assert calls == []

    @pytest.mark.asyncio
    async def test_max_cost_zero_still_allows_attempt_zero(self) -> None:
        attempt = _scripted_attempt(_ok(cost=0.0))
        verify = _scripted_verify(ShellResult(command="pytest", exit_code=0))
        loop = IterationLoop(
            attempt=attempt,
            verify=verify,
            parsers=(),
            limits=IterationLimits(max_attempts=3, max_cost_usd=0.0),
        )
        report = await loop.run()
        assert report.outcome is IterationOutcome.SUCCESS
        assert report.attempts == 1

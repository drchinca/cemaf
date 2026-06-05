"""IterationLoop — drives attempt → verify → parse → re-attempt (SPEC-08 §2)."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any

from cemaf.core.result import Result
from cemaf.iteration.protocols import FailureParser
from cemaf.iteration.types import (
    UNKNOWN_SUMMARY_MAX_CHARS,
    FailureKind,
    FailureSignal,
    HaltSignal,
    IterationLimits,
    IterationOutcome,
    IterationReport,
)
from cemaf.sandbox.shell import ShellResult


class IterationLoop:
    def __init__(
        self,
        *,
        attempt: Callable[[FailureSignal | None], Awaitable[Result[Any]]],
        verify: Callable[[Result[Any]], Awaitable[ShellResult]],
        parsers: tuple[FailureParser, ...],
        limits: IterationLimits | None = None,
        halt: HaltSignal | None = None,
    ) -> None:
        self._attempt = attempt
        self._verify = verify
        self._parsers = parsers
        self._limits = limits or IterationLimits()
        self._halt = halt

    async def run(self) -> IterationReport:
        start_ns = time.perf_counter_ns()
        attempts = 0
        total_cost_usd = 0.0
        last_signal: FailureSignal | None = None
        final_result: Result[Any] | None = None

        if self._halt and self._halt.event.is_set():
            return self._report(
                outcome=IterationOutcome.HALTED,
                attempts=0,
                start_ns=start_ns,
                total_cost_usd=0.0,
                last_signal=None,
                final_result=None,
            )

        while attempts < self._limits.max_attempts:
            if attempts > 0:
                avg_cost = total_cost_usd / attempts
                if total_cost_usd + avg_cost > self._limits.max_cost_usd:
                    return self._report(
                        outcome=IterationOutcome.BUDGET_EXCEEDED,
                        attempts=attempts,
                        start_ns=start_ns,
                        total_cost_usd=total_cost_usd,
                        last_signal=last_signal,
                        final_result=final_result,
                    )
            elapsed_ms = (time.perf_counter_ns() - start_ns) / 1_000_000
            if elapsed_ms >= self._limits.max_total.total_seconds() * 1000:
                return self._report(
                    outcome=IterationOutcome.BUDGET_EXCEEDED,
                    attempts=attempts,
                    start_ns=start_ns,
                    total_cost_usd=total_cost_usd,
                    last_signal=last_signal,
                    final_result=final_result,
                )
            if self._halt and self._halt.event.is_set():
                return self._report(
                    outcome=IterationOutcome.HALTED,
                    attempts=attempts,
                    start_ns=start_ns,
                    total_cost_usd=total_cost_usd,
                    last_signal=last_signal,
                    final_result=final_result,
                )

            attempt_result = await self._attempt(last_signal)
            attempts += 1
            final_result = attempt_result
            total_cost_usd += float(attempt_result.metadata.get("cost_usd", 0.0))

            try:
                shell_result = await self._verify(attempt_result)
            except Exception as exc:
                last_signal = FailureSignal(
                    kind=FailureKind.UNKNOWN,
                    summary=f"verify raised {type(exc).__name__}: {exc}"[:UNKNOWN_SUMMARY_MAX_CHARS],
                    items=(),
                    raw_command="<verify>",
                    exit_code=-1,
                    truncated=False,
                    metadata={"verify_exception": type(exc).__name__},
                )
                continue

            if shell_result.success:
                return self._report(
                    outcome=IterationOutcome.SUCCESS,
                    attempts=attempts,
                    start_ns=start_ns,
                    total_cost_usd=total_cost_usd,
                    last_signal=last_signal,
                    final_result=final_result,
                )

            last_signal = self._dispatch(shell_result)

        return self._report(
            outcome=IterationOutcome.EXHAUSTED,
            attempts=attempts,
            start_ns=start_ns,
            total_cost_usd=total_cost_usd,
            last_signal=last_signal,
            final_result=final_result,
        )

    def _dispatch(self, result: ShellResult) -> FailureSignal:
        ranked = sorted(
            (p for p in self._parsers if p.matches(result)),
            key=lambda p: p.specificity,
            reverse=True,
        )
        for parser in ranked:
            signal = parser.parse(result)
            if signal is not None:
                return signal
        raw = (result.stderr or result.stdout or "").strip()
        summary = raw[:UNKNOWN_SUMMARY_MAX_CHARS] if raw else f"command exited {result.exit_code}"
        return FailureSignal(
            kind=FailureKind.UNKNOWN,
            summary=summary,
            items=(),
            raw_command=result.command,
            exit_code=result.exit_code,
            truncated=len(raw) > UNKNOWN_SUMMARY_MAX_CHARS,
            metadata={},
        )

    def _report(
        self,
        *,
        outcome: IterationOutcome,
        attempts: int,
        start_ns: int,
        total_cost_usd: float,
        last_signal: FailureSignal | None,
        final_result: Result[Any] | None,
    ) -> IterationReport:
        duration_ms = (time.perf_counter_ns() - start_ns) / 1_000_000
        return IterationReport(
            outcome=outcome,
            attempts=attempts,
            total_duration_ms=duration_ms,
            total_cost_usd=total_cost_usd,
            last_signal=last_signal,
            final_result=final_result,
        )

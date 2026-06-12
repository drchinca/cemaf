"""Failure-feedback iteration loop (SPEC-08).

Closes the test↔agent loop: a verifier produces a `ShellResult`; matched
parsers turn it into a structured `FailureSignal`; `IterationLoop` re-invokes
the agent with the signal as goal context until SUCCESS, EXHAUSTED,
BUDGET_EXCEEDED, or HALTED.
"""

from cemaf.iteration.loop import IterationLoop
from cemaf.iteration.parsers import (
    MypyParser,
    PytestParser,
    RuffParser,
    ShellFallbackParser,
)
from cemaf.iteration.protocols import FailureParser
from cemaf.iteration.types import (
    UNKNOWN_SUMMARY_MAX_CHARS,
    FailureItem,
    FailureKind,
    FailureSignal,
    HaltSignal,
    IterationLimits,
    IterationOutcome,
    IterationReport,
)

__all__ = [
    "FailureItem",
    "FailureKind",
    "FailureParser",
    "FailureSignal",
    "HaltSignal",
    "IterationLimits",
    "IterationLoop",
    "IterationOutcome",
    "IterationReport",
    "MypyParser",
    "PytestParser",
    "RuffParser",
    "ShellFallbackParser",
    "UNKNOWN_SUMMARY_MAX_CHARS",
]

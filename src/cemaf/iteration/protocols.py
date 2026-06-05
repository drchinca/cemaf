"""Protocols for the iteration loop (SPEC-08 §2)."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from cemaf.iteration.types import FailureSignal
from cemaf.sandbox.shell import ShellResult


@runtime_checkable
class FailureParser(Protocol):
    """Pure structured-failure extractor for one verifier tool."""

    @property
    def tool(self) -> str: ...

    @property
    def specificity(self) -> int: ...

    @property
    def max_items(self) -> int: ...

    def matches(self, result: ShellResult) -> bool: ...

    def parse(self, result: ShellResult) -> FailureSignal | None: ...

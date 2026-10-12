"""Sticky, message-keyed property assertions (SPEC-19 §2).

Adapted from the Antithesis Python SDK's `always`/`sometimes`/`reachable`/
`unreachable` assertion model — the accumulate-then-check idea, reimplemented
standalone with no hypervisor, no fault injection, no platform dependency.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum

from cemaf.core.types import JSON


class PropertyKind(StrEnum):
    ALWAYS = "always"
    SOMETIMES = "sometimes"
    REACHABLE = "reachable"
    UNREACHABLE = "unreachable"


@dataclass(frozen=True, slots=True)
class PropertyState:
    """Accumulated state for one message-keyed property."""

    kind: PropertyKind
    message: str
    hit_count: int
    all_conditions_true: bool
    any_condition_true: bool
    last_details: JSON

    def satisfied(self) -> bool:
        """Whether this property's pass condition holds given what was observed."""
        if self.kind is PropertyKind.ALWAYS:
            return self.hit_count > 0 and self.all_conditions_true
        if self.kind is PropertyKind.SOMETIMES:
            return self.hit_count > 0 and self.any_condition_true
        if self.kind is PropertyKind.REACHABLE:
            return self.hit_count > 0
        return self.hit_count == 0  # UNREACHABLE


class PropertyViolation(AssertionError):
    """Raised by assert_all_satisfied() naming every unsatisfied property."""

    def __init__(self, *, violations: tuple[PropertyState, ...]) -> None:
        self.violations = violations
        names = ", ".join(f"{v.kind.value}:{v.message!r}" for v in violations)
        super().__init__(f"{len(violations)} property violation(s): {names}")


@dataclass(slots=True)
class _Accumulator:
    hit_count: int = 0
    all_conditions_true: bool = True
    any_condition_true: bool = False
    last_details: JSON = field(default_factory=dict)


class PropertyTracker:
    """Accumulates property hits for one test/run.

    Constructed per test — directly, or via the `property_tracker` pytest
    fixture (conftest.py) — never as a module-level singleton.
    """

    def __init__(self) -> None:
        self._state: dict[tuple[PropertyKind, str], _Accumulator] = {}

    def _record(
        self, *, kind: PropertyKind, condition: bool, message: str, details: Mapping[str, object]
    ) -> None:
        key = (kind, message)
        acc = self._state.setdefault(key, _Accumulator())
        acc.hit_count += 1
        acc.all_conditions_true = acc.all_conditions_true and condition
        acc.any_condition_true = acc.any_condition_true or condition
        acc.last_details = dict(details)

    def always(self, condition: bool, *, message: str, details: Mapping[str, object] = {}) -> None:
        """Track that `condition` should be true every time this is called for `message`."""
        self._record(kind=PropertyKind.ALWAYS, condition=condition, message=message, details=details)

    def sometimes(self, condition: bool, *, message: str, details: Mapping[str, object] = {}) -> None:
        """Track that `condition` should be true at least once across all calls for `message`."""
        self._record(kind=PropertyKind.SOMETIMES, condition=condition, message=message, details=details)

    def reachable(self, *, message: str, details: Mapping[str, object] = {}) -> None:
        """Track that this call site is reached at least once."""
        self._record(kind=PropertyKind.REACHABLE, condition=True, message=message, details=details)

    def unreachable(self, *, message: str, details: Mapping[str, object] = {}) -> None:
        """Track that this call site is never reached."""
        self._record(kind=PropertyKind.UNREACHABLE, condition=False, message=message, details=details)

    def snapshot(self) -> tuple[PropertyState, ...]:
        """Every tracked property's current accumulated state, message-sorted."""
        return tuple(
            PropertyState(
                kind=kind,
                message=message,
                hit_count=acc.hit_count,
                all_conditions_true=acc.all_conditions_true,
                any_condition_true=acc.any_condition_true,
                last_details=dict(acc.last_details),
            )
            for (kind, message), acc in sorted(self._state.items(), key=lambda item: item[0][1])
        )

    def assert_all_satisfied(self) -> None:
        """Raise PropertyViolation naming every unsatisfied property; no-op if none."""
        violations = tuple(state for state in self.snapshot() if not state.satisfied())
        if violations:
            raise PropertyViolation(violations=violations)

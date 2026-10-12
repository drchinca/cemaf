"""Unit tests for the SPEC-19 sticky property assertion primitive.

Real PropertyTracker instances throughout — pure logic, nothing to mock.
"""

from __future__ import annotations

import pytest

from cemaf.properties import PropertyKind, PropertyTracker, PropertyViolation


class TestAlwaysProperty:
    def test_holds_when_every_condition_is_true(self) -> None:
        tracker = PropertyTracker()
        for _ in range(3):
            tracker.always(True, message="m")

        tracker.assert_all_satisfied()  # does not raise

    def test_fails_on_any_false_among_many_true(self) -> None:
        tracker = PropertyTracker()
        tracker.always(True, message="m")
        tracker.always(True, message="m")
        tracker.always(False, message="m")

        with pytest.raises(PropertyViolation) as exc_info:
            tracker.assert_all_satisfied()
        assert exc_info.value.violations[0].message == "m"
        assert exc_info.value.violations[0].kind is PropertyKind.ALWAYS

    def test_zero_calls_has_no_entry_and_is_not_reported(self) -> None:
        tracker = PropertyTracker()

        tracker.assert_all_satisfied()  # nothing recorded -> nothing to violate
        assert tracker.snapshot() == ()


class TestSometimesProperty:
    def test_holds_if_at_least_one_call_was_true(self) -> None:
        tracker = PropertyTracker()
        tracker.sometimes(False, message="m")
        tracker.sometimes(False, message="m")
        tracker.sometimes(True, message="m")

        tracker.assert_all_satisfied()

    def test_fails_if_called_but_never_true(self) -> None:
        tracker = PropertyTracker()
        for _ in range(3):
            tracker.sometimes(False, message="m")

        with pytest.raises(PropertyViolation) as exc_info:
            tracker.assert_all_satisfied()
        assert exc_info.value.violations[0].message == "m"
        assert exc_info.value.violations[0].kind is PropertyKind.SOMETIMES

    def test_never_called_has_no_entry_and_is_not_reported(self) -> None:
        tracker = PropertyTracker()

        tracker.assert_all_satisfied()
        assert tracker.snapshot() == ()


class TestReachableProperty:
    def test_holds_after_one_call(self) -> None:
        tracker = PropertyTracker()
        tracker.reachable(message="m")

        tracker.assert_all_satisfied()

    def test_fails_if_never_called(self) -> None:
        tracker = PropertyTracker()

        # A REACHABLE property that's simply never invoked has no entry —
        # same absent-key semantics as ALWAYS/SOMETIMES (Inv 8). Callers who
        # need "this must run" enforced even when the test forgets to call
        # it would need a static check, not this runtime primitive (§5).
        tracker.assert_all_satisfied()
        assert tracker.snapshot() == ()


class TestUnreachableProperty:
    def test_holds_when_never_called(self) -> None:
        tracker = PropertyTracker()

        tracker.assert_all_satisfied()

    def test_fails_if_ever_called(self) -> None:
        tracker = PropertyTracker()
        tracker.unreachable(message="m")

        with pytest.raises(PropertyViolation) as exc_info:
            tracker.assert_all_satisfied()
        assert exc_info.value.violations[0].message == "m"
        assert exc_info.value.violations[0].kind is PropertyKind.UNREACHABLE


class TestDistinctKindsUnderSameMessage:
    def test_tracked_independently(self) -> None:
        tracker = PropertyTracker()
        tracker.always(True, message="m")
        tracker.sometimes(False, message="m")

        with pytest.raises(PropertyViolation) as exc_info:
            tracker.assert_all_satisfied()

        assert len(exc_info.value.violations) == 1
        assert exc_info.value.violations[0].kind is PropertyKind.SOMETIMES


class TestViolationReport:
    def test_names_every_unsatisfied_property_not_just_the_first(self) -> None:
        tracker = PropertyTracker()
        tracker.always(False, message="a")
        tracker.sometimes(False, message="b")

        with pytest.raises(PropertyViolation) as exc_info:
            tracker.assert_all_satisfied()

        assert len(exc_info.value.violations) == 2
        messages = {v.message for v in exc_info.value.violations}
        assert messages == {"a", "b"}


class TestSnapshotImmutability:
    def test_later_calls_do_not_mutate_earlier_snapshot(self) -> None:
        tracker = PropertyTracker()
        tracker.always(True, message="m")
        first = tracker.snapshot()

        tracker.always(False, message="m")

        assert first[0].all_conditions_true is True
        assert tracker.snapshot()[0].all_conditions_true is False

    def test_details_are_captured_and_independent(self) -> None:
        tracker = PropertyTracker()
        details = {"k": "v"}
        tracker.always(True, message="m", details=details)
        details["k"] = "mutated"

        assert tracker.snapshot()[0].last_details == {"k": "v"}

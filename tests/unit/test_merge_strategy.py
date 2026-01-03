"""Tests for context merge strategies.

TDD tests for the MergeStrategy system that handles concurrent context
writes in parallel DAG execution.
"""

import pytest

from cemaf.context.context import Context
from cemaf.context.merge import (
    DeepMergeStrategy,
    LastWriteWinsStrategy,
    MergeConflict,
    MergeConflictError,
    MergeResult,
    MergeStrategy,
    RaiseOnConflictStrategy,
    ReducerMergeStrategy,
)


class TestMergeStrategyProtocol:
    """Tests for MergeStrategy protocol compliance."""

    def test_last_write_wins_is_merge_strategy(self) -> None:
        """LastWriteWinsStrategy implements MergeStrategy protocol."""
        strategy = LastWriteWinsStrategy()
        assert isinstance(strategy, MergeStrategy)

    def test_raise_on_conflict_is_merge_strategy(self) -> None:
        """RaiseOnConflictStrategy implements MergeStrategy protocol."""
        strategy = RaiseOnConflictStrategy()
        assert isinstance(strategy, MergeStrategy)

    def test_deep_merge_is_merge_strategy(self) -> None:
        """DeepMergeStrategy implements MergeStrategy protocol."""
        strategy = DeepMergeStrategy()
        assert isinstance(strategy, MergeStrategy)

    def test_reducer_is_merge_strategy(self) -> None:
        """ReducerMergeStrategy implements MergeStrategy protocol."""
        strategy = ReducerMergeStrategy()
        assert isinstance(strategy, MergeStrategy)


class TestLastWriteWinsStrategy:
    """Tests for LastWriteWinsStrategy - current default behavior."""

    def test_merge_disjoint_keys(self) -> None:
        """Disjoint keys are all preserved."""
        strategy = LastWriteWinsStrategy()
        base = Context(data={"original": "value"})
        branches = [
            Context(data={"original": "value", "branch1": "data1"}),
            Context(data={"original": "value", "branch2": "data2"}),
        ]

        result = strategy.merge(base, branches)

        assert result.success
        assert result.context.get("original") == "value"
        assert result.context.get("branch1") == "data1"
        assert result.context.get("branch2") == "data2"
        assert len(result.conflicts) == 0

    def test_merge_conflicting_keys_last_wins(self) -> None:
        """When branches write same key, last branch wins."""
        strategy = LastWriteWinsStrategy()
        base = Context()
        branches = [
            Context(data={"shared": "from_branch1"}),
            Context(data={"shared": "from_branch2"}),
            Context(data={"shared": "from_branch3"}),
        ]

        result = strategy.merge(base, branches)

        assert result.success
        assert result.context.get("shared") == "from_branch3"
        # Should report conflicts for tracking
        assert len(result.conflicts) == 1
        assert result.conflicts[0].key == "shared"

    def test_merge_nested_keys(self) -> None:
        """Nested keys at top level use last-write-wins."""
        strategy = LastWriteWinsStrategy()
        base = Context()
        branches = [
            Context(data={"user": {"name": "Alice", "age": 30}}),
            Context(data={"user": {"name": "Bob", "role": "admin"}}),
        ]

        result = strategy.merge(base, branches)

        assert result.success
        # Last branch completely overwrites at top level
        assert result.context.get("user") == {"name": "Bob", "role": "admin"}

    def test_merge_empty_branches(self) -> None:
        """Empty branches list returns base context."""
        strategy = LastWriteWinsStrategy()
        base = Context(data={"key": "value"})

        result = strategy.merge(base, [])

        assert result.success
        assert result.context.get("key") == "value"

    def test_merge_single_branch(self) -> None:
        """Single branch merges cleanly."""
        strategy = LastWriteWinsStrategy()
        base = Context(data={"original": "value"})
        branches = [Context(data={"original": "value", "new": "data"})]

        result = strategy.merge(base, branches)

        assert result.success
        assert result.context.get("original") == "value"
        assert result.context.get("new") == "data"


class TestRaiseOnConflictStrategy:
    """Tests for RaiseOnConflictStrategy - strict conflict detection."""

    def test_merge_disjoint_keys_succeeds(self) -> None:
        """Disjoint keys merge successfully."""
        strategy = RaiseOnConflictStrategy()
        base = Context(data={"original": "value"})
        branches = [
            Context(data={"original": "value", "branch1": "data1"}),
            Context(data={"original": "value", "branch2": "data2"}),
        ]

        result = strategy.merge(base, branches)

        assert result.success
        assert result.context.get("branch1") == "data1"
        assert result.context.get("branch2") == "data2"

    def test_merge_conflicting_keys_raises(self) -> None:
        """Conflicting keys raise MergeConflictError."""
        strategy = RaiseOnConflictStrategy()
        base = Context()
        branches = [
            Context(data={"shared": "from_branch1"}),
            Context(data={"shared": "from_branch2"}),
        ]

        with pytest.raises(MergeConflictError) as exc_info:
            strategy.merge(base, branches)

        assert "shared" in str(exc_info.value)
        assert len(exc_info.value.conflicts) == 1

    def test_merge_same_value_no_conflict(self) -> None:
        """Same value from multiple branches is not a conflict."""
        strategy = RaiseOnConflictStrategy()
        base = Context()
        branches = [
            Context(data={"shared": "same_value"}),
            Context(data={"shared": "same_value"}),
        ]

        result = strategy.merge(base, branches)

        assert result.success
        assert result.context.get("shared") == "same_value"
        assert len(result.conflicts) == 0

    def test_merge_nested_same_value_no_conflict(self) -> None:
        """Same nested value from multiple branches is not a conflict."""
        strategy = RaiseOnConflictStrategy()
        base = Context()
        branches = [
            Context(data={"user": {"name": "Alice"}}),
            Context(data={"user": {"name": "Alice"}}),
        ]

        result = strategy.merge(base, branches)

        assert result.success
        assert result.context.get("user.name") == "Alice"

    def test_merge_base_unchanged_keys_no_conflict(self) -> None:
        """Keys unchanged from base don't conflict with new writes."""
        strategy = RaiseOnConflictStrategy()
        base = Context(data={"existing": "value"})
        branches = [
            Context(data={"existing": "value", "new1": "data1"}),
            Context(data={"existing": "value", "new2": "data2"}),
        ]

        result = strategy.merge(base, branches)

        assert result.success
        assert result.context.get("existing") == "value"
        assert result.context.get("new1") == "data1"
        assert result.context.get("new2") == "data2"

    def test_multiple_conflicts_all_reported(self) -> None:
        """All conflicts are reported in the error."""
        strategy = RaiseOnConflictStrategy()
        base = Context()
        branches = [
            Context(data={"key1": "a", "key2": "x"}),
            Context(data={"key1": "b", "key2": "y"}),
        ]

        with pytest.raises(MergeConflictError) as exc_info:
            strategy.merge(base, branches)

        assert len(exc_info.value.conflicts) == 2
        conflict_keys = {c.key for c in exc_info.value.conflicts}
        assert conflict_keys == {"key1", "key2"}


class TestDeepMergeStrategy:
    """Tests for DeepMergeStrategy - recursive dictionary merging."""

    def test_merge_disjoint_nested_keys(self) -> None:
        """Disjoint nested keys are merged recursively."""
        strategy = DeepMergeStrategy()
        base = Context()
        branches = [
            Context(data={"user": {"name": "Alice"}}),
            Context(data={"user": {"age": 30}}),
        ]

        result = strategy.merge(base, branches)

        assert result.success
        assert result.context.get("user.name") == "Alice"
        assert result.context.get("user.age") == 30

    def test_merge_conflicting_leaf_values(self) -> None:
        """Conflicting leaf values use last-write-wins at leaf level."""
        strategy = DeepMergeStrategy()
        base = Context()
        branches = [
            Context(data={"user": {"name": "Alice", "role": "user"}}),
            Context(data={"user": {"name": "Bob", "age": 25}}),
        ]

        result = strategy.merge(base, branches)

        assert result.success
        # Last wins for conflicting leaf
        assert result.context.get("user.name") == "Bob"
        # Non-conflicting keys merged
        assert result.context.get("user.role") == "user"
        assert result.context.get("user.age") == 25
        # Conflict tracked
        assert len(result.conflicts) == 1
        assert result.conflicts[0].key == "user.name"

    def test_deep_merge_multiple_levels(self) -> None:
        """Deep merge works across multiple nesting levels."""
        strategy = DeepMergeStrategy()
        base = Context()
        branches = [
            Context(data={"a": {"b": {"c": 1}}}),
            Context(data={"a": {"b": {"d": 2}}}),
            Context(data={"a": {"e": 3}}),
        ]

        result = strategy.merge(base, branches)

        assert result.success
        assert result.context.get("a.b.c") == 1
        assert result.context.get("a.b.d") == 2
        assert result.context.get("a.e") == 3

    def test_deep_merge_list_replaced(self) -> None:
        """Lists are replaced, not merged (by default)."""
        strategy = DeepMergeStrategy()
        base = Context()
        branches = [
            Context(data={"items": [1, 2, 3]}),
            Context(data={"items": [4, 5]}),
        ]

        result = strategy.merge(base, branches)

        assert result.success
        assert result.context.get("items") == [4, 5]

    def test_deep_merge_type_mismatch(self) -> None:
        """Type mismatch uses last-write-wins."""
        strategy = DeepMergeStrategy()
        base = Context()
        branches = [
            Context(data={"key": {"nested": "dict"}}),
            Context(data={"key": "now_a_string"}),
        ]

        result = strategy.merge(base, branches)

        assert result.success
        assert result.context.get("key") == "now_a_string"


class TestReducerMergeStrategy:
    """Tests for ReducerMergeStrategy - custom per-key reducers."""

    def test_sum_reducer(self) -> None:
        """Sum reducer combines numeric values."""
        strategy = ReducerMergeStrategy(reducers={"count": lambda values: sum(values)})
        base = Context()
        branches = [
            Context(data={"count": 10}),
            Context(data={"count": 5}),
            Context(data={"count": 3}),
        ]

        result = strategy.merge(base, branches)

        assert result.success
        assert result.context.get("count") == 18

    def test_list_concat_reducer(self) -> None:
        """List concatenation reducer."""

        def concat_lists(values: list) -> list:
            result = []
            for v in values:
                if isinstance(v, list):
                    result.extend(v)
                else:
                    result.append(v)
            return result

        strategy = ReducerMergeStrategy(reducers={"items": concat_lists})
        base = Context()
        branches = [
            Context(data={"items": [1, 2]}),
            Context(data={"items": [3, 4]}),
        ]

        result = strategy.merge(base, branches)

        assert result.success
        assert result.context.get("items") == [1, 2, 3, 4]

    def test_custom_dict_merger(self) -> None:
        """Custom reducer for merging dictionaries."""

        def merge_dicts(values: list) -> dict:
            result = {}
            for v in values:
                if isinstance(v, dict):
                    result.update(v)
            return result

        strategy = ReducerMergeStrategy(reducers={"config": merge_dicts})
        base = Context()
        branches = [
            Context(data={"config": {"a": 1, "b": 2}}),
            Context(data={"config": {"c": 3, "b": 4}}),
        ]

        result = strategy.merge(base, branches)

        assert result.success
        assert result.context.get("config") == {"a": 1, "b": 4, "c": 3}

    def test_fallback_to_last_write_wins(self) -> None:
        """Keys without reducer use last-write-wins."""
        strategy = ReducerMergeStrategy(reducers={"count": lambda values: sum(values)})
        base = Context()
        branches = [
            Context(data={"count": 10, "name": "first"}),
            Context(data={"count": 5, "name": "second"}),
        ]

        result = strategy.merge(base, branches)

        assert result.success
        assert result.context.get("count") == 15
        assert result.context.get("name") == "second"

    def test_reducer_with_base_value(self) -> None:
        """Reducer includes base value when include_base=True."""
        strategy = ReducerMergeStrategy(
            reducers={"count": lambda values: sum(values)},
            include_base=True,
        )
        base = Context(data={"count": 100})
        branches = [
            Context(data={"count": 10}),
            Context(data={"count": 5}),
        ]

        result = strategy.merge(base, branches)

        assert result.success
        assert result.context.get("count") == 115

    def test_reducer_error_handling(self) -> None:
        """Reducer errors are caught and reported."""

        def bad_reducer(values: list) -> int:
            raise ValueError("Reducer failed")

        strategy = ReducerMergeStrategy(reducers={"key": bad_reducer})
        base = Context()
        branches = [
            Context(data={"key": 1}),
            Context(data={"key": 2}),
        ]

        result = strategy.merge(base, branches)

        # Should still succeed but with error tracked
        assert not result.success
        assert "Reducer failed" in result.error


class TestMergeResult:
    """Tests for MergeResult dataclass."""

    def test_success_result(self) -> None:
        """Success result has correct properties."""
        ctx = Context(data={"key": "value"})
        result = MergeResult(
            success=True,
            context=ctx,
            conflicts=[],
        )

        assert result.success
        assert result.context.get("key") == "value"
        assert len(result.conflicts) == 0
        assert result.error is None

    def test_result_with_conflicts(self) -> None:
        """Result can include conflicts even on success."""
        ctx = Context(data={"key": "last_value"})
        conflicts = [
            MergeConflict(
                key="key",
                values=["first", "second", "last_value"],
                branch_indices=[0, 1, 2],
            )
        ]
        result = MergeResult(
            success=True,
            context=ctx,
            conflicts=conflicts,
        )

        assert result.success
        assert len(result.conflicts) == 1
        assert result.conflicts[0].key == "key"

    def test_failure_result(self) -> None:
        """Failure result includes error message."""
        result = MergeResult(
            success=False,
            context=Context(),
            conflicts=[],
            error="Merge failed due to conflict",
        )

        assert not result.success
        assert result.error == "Merge failed due to conflict"


class TestMergeConflict:
    """Tests for MergeConflict dataclass."""

    def test_conflict_properties(self) -> None:
        """MergeConflict stores all conflict details."""
        conflict = MergeConflict(
            key="user.name",
            values=["Alice", "Bob"],
            branch_indices=[0, 1],
        )

        assert conflict.key == "user.name"
        assert conflict.values == ["Alice", "Bob"]
        assert conflict.branch_indices == [0, 1]

    def test_conflict_string_representation(self) -> None:
        """MergeConflict has useful string representation."""
        conflict = MergeConflict(
            key="shared_key",
            values=["val1", "val2"],
            branch_indices=[0, 2],
        )

        str_repr = str(conflict)
        assert "shared_key" in str_repr


class TestMergeConflictError:
    """Tests for MergeConflictError exception."""

    def test_error_contains_conflicts(self) -> None:
        """Error contains list of conflicts."""
        conflicts = [
            MergeConflict(key="key1", values=["a", "b"], branch_indices=[0, 1]),
            MergeConflict(key="key2", values=["x", "y"], branch_indices=[0, 1]),
        ]
        error = MergeConflictError(conflicts)

        assert len(error.conflicts) == 2
        assert "key1" in str(error)
        assert "key2" in str(error)

    def test_error_message(self) -> None:
        """Error has descriptive message."""
        conflicts = [
            MergeConflict(key="config", values=[1, 2], branch_indices=[0, 1]),
        ]
        error = MergeConflictError(conflicts)

        assert "conflict" in str(error).lower()
        assert "config" in str(error)

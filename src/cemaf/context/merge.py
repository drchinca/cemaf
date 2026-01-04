"""
cemaf.context.merge - Merge strategies for parallel context branches.

This module provides pluggable merge strategies for combining context
from parallel DAG execution branches. Solves the "merge conflict problem"
when multiple parallel nodes write to the same context keys.

Strategies:
- LastWriteWinsStrategy: Default behavior, later branches overwrite earlier
- RaiseOnConflictStrategy: Strict mode, raises error on any conflict
- DeepMergeStrategy: Recursively merges nested dictionaries
- ReducerMergeStrategy: Custom per-key reducer functions

Usage:
    from cemaf.context.merge import DeepMergeStrategy, MergeStrategy

    strategy = DeepMergeStrategy()
    result = strategy.merge(base_context, [branch1, branch2, branch3])

    if result.success:
        merged_context = result.context
    else:
        handle_error(result.error)
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from cemaf.context.context import Context


@dataclass(frozen=True)
class MergeConflict:
    """
    Represents a merge conflict where multiple branches wrote different
    values to the same key.

    Attributes:
        key: The context key that has conflicting values
        values: List of values from each branch that wrote to this key
        branch_indices: Indices of branches that wrote to this key
    """

    key: str
    values: list[Any]
    branch_indices: list[int]

    def __str__(self) -> str:
        return f"MergeConflict(key='{self.key}', values={self.values}, branches={self.branch_indices})"


class MergeConflictError(Exception):
    """
    Exception raised when merge conflicts are detected and the strategy
    does not allow automatic resolution.

    Attributes:
        conflicts: List of all conflicts detected during merge
    """

    def __init__(self, conflicts: list[MergeConflict]) -> None:
        self.conflicts = conflicts
        keys = [c.key for c in conflicts]
        super().__init__(
            f"Merge conflict detected for keys: {', '.join(keys)}. {len(conflicts)} conflict(s) found."
        )


@dataclass
class MergeResult:
    """
    Result of a merge operation.

    Attributes:
        success: Whether the merge completed successfully
        context: The merged context (may be partial on failure)
        conflicts: List of conflicts detected (even if resolved)
        error: Error message if merge failed
    """

    success: bool
    context: Context
    conflicts: list[MergeConflict] = field(default_factory=list)
    error: str | None = None


@runtime_checkable
class MergeStrategy(Protocol):
    """
    Protocol for context merge strategies.

    Implementations define how to combine context from multiple parallel
    execution branches back into a single context.
    """

    def merge(
        self,
        base: Context,
        branches: list[Context],
    ) -> MergeResult:
        """
        Merge multiple branch contexts into a single context.

        Args:
            base: The original context before parallel execution
            branches: List of contexts from each parallel branch

        Returns:
            MergeResult with the merged context and any conflicts

        Raises:
            MergeConflictError: If strategy doesn't allow conflicts and
                               conflicts are detected
        """
        ...


class LastWriteWinsStrategy:
    """
    Default merge strategy - later branches overwrite earlier ones.

    This is the simplest and most permissive strategy. When multiple
    branches write to the same key, the value from the last branch
    (by index) is used.

    Conflicts are tracked in the result for observability but don't
    cause failures.
    """

    def merge(
        self,
        base: Context,
        branches: list[Context],
    ) -> MergeResult:
        """Merge using last-write-wins semantics."""
        if not branches:
            return MergeResult(success=True, context=base, conflicts=[])

        # Track which keys each branch modifies (vs base)
        branch_changes: list[dict[str, Any]] = []
        for branch in branches:
            changes = self._get_changes_from_base(base, branch)
            branch_changes.append(changes)

        # Detect conflicts (same key written by multiple branches)
        conflicts = self._detect_conflicts(branch_changes)

        # Merge all branches sequentially (last wins)
        merged_data = dict(base.data)
        for branch in branches:
            merged_data.update(branch.data)

        return MergeResult(
            success=True,
            context=Context(data=merged_data),
            conflicts=conflicts,
        )

    def _get_changes_from_base(self, base: Context, branch: Context) -> dict[str, Any]:
        """Get keys that changed between base and branch."""
        changes = {}
        for key, value in branch.data.items():
            base_value = base.data.get(key)
            if base_value != value:
                changes[key] = value
        return changes

    def _detect_conflicts(self, branch_changes: list[dict[str, Any]]) -> list[MergeConflict]:
        """Detect keys written by multiple branches with different values."""
        # Map key -> [(branch_index, value), ...]
        key_writes: dict[str, list[tuple[int, Any]]] = {}

        for idx, changes in enumerate(branch_changes):
            for key, value in changes.items():
                if key not in key_writes:
                    key_writes[key] = []
                key_writes[key].append((idx, value))

        conflicts = []
        for key, writes in key_writes.items():
            if len(writes) > 1:
                # Check if all values are the same
                values = [w[1] for w in writes]
                if not self._all_equal(values):
                    conflicts.append(
                        MergeConflict(
                            key=key,
                            values=values,
                            branch_indices=[w[0] for w in writes],
                        )
                    )

        return conflicts

    def _all_equal(self, values: list[Any]) -> bool:
        """Check if all values in list are equal."""
        if not values:
            return True
        first = values[0]
        return all(v == first for v in values[1:])


class RaiseOnConflictStrategy:
    """
    Strict merge strategy - raises error on any conflict.

    Use this when parallel branches should write to disjoint keys.
    If two branches write different values to the same key, a
    MergeConflictError is raised.

    Same values from multiple branches are NOT considered conflicts.
    """

    def merge(
        self,
        base: Context,
        branches: list[Context],
    ) -> MergeResult:
        """Merge with strict conflict detection."""
        if not branches:
            return MergeResult(success=True, context=base, conflicts=[])

        # Track changes from base for each branch
        branch_changes: list[dict[str, Any]] = []
        for branch in branches:
            changes = self._get_changes_from_base(base, branch)
            branch_changes.append(changes)

        # Detect conflicts
        conflicts = self._detect_conflicts(branch_changes)

        # Raise if conflicts found
        if conflicts:
            raise MergeConflictError(conflicts)

        # No conflicts - safe to merge
        merged_data = dict(base.data)
        for branch in branches:
            merged_data.update(branch.data)

        return MergeResult(
            success=True,
            context=Context(data=merged_data),
            conflicts=[],
        )

    def _get_changes_from_base(self, base: Context, branch: Context) -> dict[str, Any]:
        """Get keys that changed between base and branch."""
        changes = {}
        for key, value in branch.data.items():
            base_value = base.data.get(key)
            if base_value != value:
                changes[key] = value
        return changes

    def _detect_conflicts(self, branch_changes: list[dict[str, Any]]) -> list[MergeConflict]:
        """Detect conflicting writes (different values to same key)."""
        key_writes: dict[str, list[tuple[int, Any]]] = {}

        for idx, changes in enumerate(branch_changes):
            for key, value in changes.items():
                if key not in key_writes:
                    key_writes[key] = []
                key_writes[key].append((idx, value))

        conflicts = []
        for key, writes in key_writes.items():
            if len(writes) > 1:
                values = [w[1] for w in writes]
                # Only conflict if values differ
                if not self._all_equal(values):
                    conflicts.append(
                        MergeConflict(
                            key=key,
                            values=values,
                            branch_indices=[w[0] for w in writes],
                        )
                    )

        return conflicts

    def _all_equal(self, values: list[Any]) -> bool:
        """Check if all values are equal."""
        if not values:
            return True
        first = values[0]
        return all(v == first for v in values[1:])


class DeepMergeStrategy:
    """
    Deep merge strategy - recursively merges nested dictionaries.

    When branches write to the same top-level key with dict values,
    this strategy recursively merges the nested dictionaries instead
    of overwriting.

    For conflicting leaf values (non-dict), last-write-wins is used.
    Lists and other types are replaced, not merged.
    """

    def merge(
        self,
        base: Context,
        branches: list[Context],
    ) -> MergeResult:
        """Merge with recursive dictionary merging."""
        if not branches:
            return MergeResult(success=True, context=base, conflicts=[])

        conflicts: list[MergeConflict] = []

        # Start with base data and track which branch wrote each value
        merged_data = dict(base.data)
        value_sources: dict[str, int] = {}  # Maps key path -> branch index that wrote it

        # Deep merge each branch
        for idx, branch in enumerate(branches):
            merged_data, branch_conflicts, new_sources = self._deep_merge_dicts(
                merged_data, branch.data, "", idx, base.data, value_sources
            )
            value_sources.update(new_sources)
            conflicts.extend(branch_conflicts)

        return MergeResult(
            success=True,
            context=Context(data=merged_data),
            conflicts=conflicts,
        )

    def _deep_merge_dicts(
        self,
        target: dict[str, Any],
        source: dict[str, Any],
        prefix: str,
        branch_idx: int,
        base_data: dict[str, Any],
        value_sources: dict[str, int],
    ) -> tuple[dict[str, Any], list[MergeConflict], dict[str, int]]:
        """
        Recursively merge source into target.

        Returns merged dict, list of conflicts detected, and source tracking dict.
        """
        result = dict(target)
        conflicts: list[MergeConflict] = []
        new_sources: dict[str, int] = {}

        for key, source_value in source.items():
            full_key = f"{prefix}.{key}" if prefix else key
            target_value = result.get(key)
            base_value = self._get_nested(base_data, full_key)

            # If source value equals base, skip (no change in this branch)
            if source_value == base_value:
                continue

            # If target doesn't have this key, just set it
            if key not in result:
                result[key] = source_value
                new_sources[full_key] = branch_idx
                continue

            # Both have the key - check for conflict
            if target_value == source_value:
                # Same value, no conflict
                continue

            # Check if target value came from base or was set by earlier branch
            if target_value == base_value:
                # Target has base value, source is new - no conflict
                result[key] = source_value
                new_sources[full_key] = branch_idx
                continue

            # Both are dicts - recurse
            if isinstance(target_value, dict) and isinstance(source_value, dict):
                merged_nested, nested_conflicts, nested_sources = self._deep_merge_dicts(
                    target_value, source_value, full_key, branch_idx, base_data, value_sources
                )
                result[key] = merged_nested
                conflicts.extend(nested_conflicts)
                new_sources.update(nested_sources)
            else:
                # Conflict at leaf level - last write wins but track conflict
                # Get the branch index that previously wrote this value
                prev_branch_idx = value_sources.get(full_key, -1)
                if prev_branch_idx >= 0:
                    # We know which branch wrote the target value
                    branch_indices = [prev_branch_idx, branch_idx]
                else:
                    # Target value might be from base or unknown source
                    branch_indices = [branch_idx]

                conflicts.append(
                    MergeConflict(
                        key=full_key,
                        values=[target_value, source_value],
                        branch_indices=branch_indices,
                    )
                )
                result[key] = source_value
                new_sources[full_key] = branch_idx

        return result, conflicts, new_sources

    def _get_nested(self, data: dict[str, Any], path: str) -> Any:
        """Get nested value using dot notation."""
        if not path:
            return data
        keys = path.split(".")
        current = data
        for key in keys:
            if not isinstance(current, dict) or key not in current:
                return None
            current = current[key]
        return current


class ReducerMergeStrategy:
    """
    Custom reducer merge strategy - apply user-defined reducers per key.

    Allows specifying custom merge functions for specific keys.
    Keys without reducers fall back to last-write-wins.

    Example:
        strategy = ReducerMergeStrategy(
            reducers={
                "count": lambda values: sum(values),
                "items": lambda values: [item for v in values for item in v],
            }
        )
    """

    def __init__(
        self,
        reducers: dict[str, Callable[[list[Any]], Any]] | None = None,
        include_base: bool = False,
    ) -> None:
        """
        Initialize with reducer functions.

        Args:
            reducers: Dict mapping key names to reducer functions.
                     Reducer receives list of values from all branches.
            include_base: If True, include base value in reducer input.
        """
        self._reducers = reducers or {}
        self._include_base = include_base

    def merge(
        self,
        base: Context,
        branches: list[Context],
    ) -> MergeResult:
        """Merge using custom reducers."""
        if not branches:
            return MergeResult(success=True, context=base, conflicts=[])

        # Collect all values per key from branches
        key_values: dict[str, list[tuple[int, Any]]] = {}

        for idx, branch in enumerate(branches):
            for key, value in branch.data.items():
                if key not in key_values:
                    key_values[key] = []
                key_values[key].append((idx, value))

        # Apply reducers or fallback
        merged_data = dict(base.data)
        conflicts: list[MergeConflict] = []
        errors: list[str] = []

        for key, writes in key_values.items():
            values = [w[1] for w in writes]
            indices = [w[0] for w in writes]

            if key in self._reducers:
                # Apply custom reducer
                try:
                    reducer_input = values
                    if self._include_base and key in base.data:
                        reducer_input = [base.data[key]] + values

                    reduced_value = self._reducers[key](reducer_input)
                    merged_data[key] = reduced_value
                except Exception as e:
                    errors.append(f"Reducer for '{key}' failed: {e}")
            else:
                # Fallback to last-write-wins
                merged_data[key] = values[-1]

                # Track conflicts for keys without reducers
                if len(writes) > 1 and not self._all_equal(values):
                    conflicts.append(MergeConflict(key=key, values=values, branch_indices=indices))

        if errors:
            return MergeResult(
                success=False,
                context=Context(data=merged_data),
                conflicts=conflicts,
                error="; ".join(errors),
            )

        return MergeResult(
            success=True,
            context=Context(data=merged_data),
            conflicts=conflicts,
        )

    def _all_equal(self, values: list[Any]) -> bool:
        """Check if all values are equal."""
        if not values:
            return True
        first = values[0]
        return all(v == first for v in values[1:])


# Convenience factory functions
def create_merge_strategy(
    strategy_type: str = "last_write_wins",
    **kwargs: Any,
) -> MergeStrategy:
    """
    Factory function to create merge strategies by name.

    Args:
        strategy_type: One of 'last_write_wins', 'raise_on_conflict',
                      'deep_merge', 'reducer'
        **kwargs: Additional arguments for the strategy

    Returns:
        Configured MergeStrategy instance
    """
    strategies = {
        "last_write_wins": LastWriteWinsStrategy,
        "raise_on_conflict": RaiseOnConflictStrategy,
        "deep_merge": DeepMergeStrategy,
        "reducer": ReducerMergeStrategy,
    }

    if strategy_type not in strategies:
        raise ValueError(f"Unknown strategy: {strategy_type}. Available: {list(strategies.keys())}")

    return strategies[strategy_type](**kwargs)


# Default strategy instance
DEFAULT_MERGE_STRATEGY = LastWriteWinsStrategy()

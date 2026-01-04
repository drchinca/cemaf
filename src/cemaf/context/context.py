"""
cemaf.context.context - Manages the flow and state of context within agentic workflows.

This module introduces an immutable Context object that encapsulates the dynamic state
and information available to agents and nodes during execution.

Note: Uses PEP 563 (from __future__ import annotations) to defer annotation evaluation
and avoid circular imports with cemaf.context.merge and cemaf.context.patch.
Type imports happen at runtime within methods that need them.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, Field

from cemaf.core.types import JSON


class Context(BaseModel):
    """
    An immutable context object for agentic workflows.

    Context holds key-value pairs representing the current state and information.
    Any 'modification' to the context returns a new Context instance.
    """

    model_config = {"frozen": True}

    data: JSON = Field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        """Retrieve a value from the context using dot notation for nested access."""
        keys = key.split(".")
        current_data = self.data
        for k in keys:
            if not isinstance(current_data, Mapping) or k not in current_data:
                return default
            current_data = current_data[k]
        return current_data

    def set(self, key: str, value: Any) -> Context:
        """
        Return a new Context with the specified key set to the new value.
        Supports dot notation for nested keys.
        """
        keys = key.split(".")
        new_data = dict(self.data)  # Start with a copy

        current_level = new_data
        for i, k in enumerate(keys):
            if i == len(keys) - 1:  # Last key
                current_level[k] = value
            else:
                if not isinstance(current_level, dict):
                    # If an intermediate key is not a dict, we can't set nested
                    raise ValueError(
                        f"Cannot set nested key '{key}': '{'.'.join(keys[: i + 1])}' is not a dictionary."
                    )
                if k not in current_level or not isinstance(current_level[k], dict):
                    current_level[k] = {}  # Create dict if it doesn't exist or is not a dict
                current_level = current_level[k]

        return Context(data=new_data)

    def merge(self, other: Context) -> Context:
        """
        Return a new Context by merging another Context into this one.
        Values from 'other' will overwrite values in 'self'.
        Performs a shallow merge for top-level keys.

        For more control over merge behavior (e.g., conflict detection),
        use merge_branches() with a MergeStrategy.
        """
        merged_data = {**self.data, **other.data}
        return Context(data=merged_data)

    def merge_branches(
        self,
        branches: list[Context],
        strategy: MergeStrategy | None = None,  # noqa: F821
    ) -> MergeResult:  # noqa: F821
        """
        Merge multiple branch contexts using a specified strategy.

        This is the preferred method for merging parallel execution branches
        as it provides conflict detection and custom merge strategies.

        Args:
            branches: List of contexts from parallel branches
            strategy: MergeStrategy to use. Defaults to LastWriteWinsStrategy.

        Returns:
            MergeResult with merged context and any conflicts detected

        Example:
            from cemaf.context.merge import DeepMergeStrategy

            result = base.merge_branches(
                [branch1, branch2],
                strategy=DeepMergeStrategy()
            )
            if result.success:
                merged = result.context
        """
        from cemaf.context.merge import DEFAULT_MERGE_STRATEGY

        merge_strategy = strategy or DEFAULT_MERGE_STRATEGY
        return merge_strategy.merge(self, branches)

    def to_dict(self) -> JSON:
        """Return the underlying data as a dictionary."""
        return self.data

    @classmethod
    def from_dict(cls, data: JSON) -> Context:
        """Create a Context instance from a dictionary."""
        return cls(data=data)

    def delete(self, key: str) -> Context:
        """
        Return a new Context with the specified key removed.
        Supports dot notation for nested keys.
        """
        keys = key.split(".")
        new_data = dict(self.data)

        if len(keys) == 1:
            new_data.pop(keys[0], None)
            return Context(data=new_data)

        # Navigate to parent of the key to delete
        current_level = new_data
        for k in keys[:-1]:
            if k not in current_level or not isinstance(current_level[k], dict):
                return self  # Key path doesn't exist, return unchanged
            if k == keys[-2]:
                # Make a copy of this level before modifying
                current_level[k] = dict(current_level[k])
            current_level = current_level[k]

        current_level.pop(keys[-1], None)
        return Context(data=new_data)

    def append(self, key: str, value: Any) -> Context:
        """
        Return a new Context with the value appended to the list at key.
        Creates the list if it doesn't exist.
        """
        existing = self.get(key, [])
        if not isinstance(existing, list):
            existing = [existing]
        return self.set(key, existing + [value])

    def deep_merge(self, key: str, value: dict[str, Any]) -> Context:
        """
        Return a new Context with the value deep-merged into the dict at key.
        Creates the dict if it doesn't exist.
        """
        existing = self.get(key, {})
        if not isinstance(existing, dict):
            existing = {}
        merged = self._deep_merge_dicts(dict(existing), value)
        return self.set(key, merged)

    @staticmethod
    def _deep_merge_dicts(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
        """Deep merge two dicts, with override taking precedence."""
        result = dict(base)
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = Context._deep_merge_dicts(result[key], value)
            else:
                result[key] = value
        return result

    def apply(self, patch: ContextPatch) -> Context:  # noqa: F821
        """
        Apply a ContextPatch and return a new Context.

        Args:
            patch: The patch to apply

        Returns:
            New Context with the patch applied
        """
        from cemaf.context.patch import PatchOperation

        if patch.operation == PatchOperation.SET:
            return self.set(patch.path, patch.value)
        elif patch.operation == PatchOperation.DELETE:
            return self.delete(patch.path)
        elif patch.operation == PatchOperation.MERGE:
            return self.deep_merge(patch.path, patch.value)
        elif patch.operation == PatchOperation.APPEND:
            return self.append(patch.path, patch.value)
        else:
            return self

    def diff(self, other: Context) -> tuple[ContextPatch, ...]:  # noqa: F821
        """
        Generate patches to transform self into other.

        Args:
            other: Target context

        Returns:
            Tuple of patches that, when applied to self, produce other
        """

        patches: list[ContextPatch] = []  # noqa: F821
        self._diff_recursive("", self.data, other.data, patches)
        return tuple(patches)

    def _diff_recursive(
        self,
        prefix: str,
        old: Any,
        new: Any,
        patches: list[ContextPatch],  # noqa: F821
    ) -> None:
        """Recursively generate patches for differences."""
        from cemaf.context.patch import ContextPatch, PatchOperation, PatchSource

        # If types differ or values are not dicts, just SET
        if (type(old) is not type(new) or not isinstance(old, dict)) and old != new:
            # Skip root-level type changes (Context.data must always be dict)
            # For nested paths, generate SET patch
            if prefix:
                patches.append(
                    ContextPatch(
                        path=prefix,
                        operation=PatchOperation.SET,
                        value=new,
                        source=PatchSource.SYSTEM,
                        reason="diff",
                    )
                )
            # If at root and types differ, this indicates an error condition
            # Context.data should always be dict, so this shouldn't happen in normal use
            return
        if type(old) is not type(new) or not isinstance(old, dict):
            return

        # Both are dicts - diff keys
        old_keys = set(old.keys())
        new_keys = set(new.keys())

        # Deleted keys
        for key in old_keys - new_keys:
            path = f"{prefix}.{key}" if prefix else key
            patches.append(
                ContextPatch(
                    path=path,
                    operation=PatchOperation.DELETE,
                    value=None,
                    source=PatchSource.SYSTEM,
                    reason="diff",
                )
            )

        # Added or modified keys
        for key in new_keys:
            path = f"{prefix}.{key}" if prefix else key
            if key not in old_keys:
                # New key
                patches.append(
                    ContextPatch(
                        path=path,
                        operation=PatchOperation.SET,
                        value=new[key],
                        source=PatchSource.SYSTEM,
                        reason="diff",
                    )
                )
            else:
                # Existing key - recurse
                self._diff_recursive(path, old[key], new[key], patches)

    def copy(self) -> Context:
        """Create a shallow copy of the context."""
        import copy

        return Context(data=copy.deepcopy(self.data))

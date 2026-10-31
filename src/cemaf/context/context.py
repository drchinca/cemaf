"""
cemaf.context.context - Manages the flow and state of context within agentic workflows.

This module introduces an immutable Context object that encapsulates the dynamic state
and information available to agents and nodes during execution.

Note: Uses PEP 563 (from __future__ import annotations) to defer annotation evaluation
and avoid circular imports with cemaf.context.merge and cemaf.context.patch.
Type imports happen at runtime within methods that need them.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, Field

from cemaf.context.patch import ContextPatch, PatchOperation
from cemaf.core.types import JSON


def _write_path(*, data: JSON, key: str, value: Any) -> JSON:
    """Return a deep copy of data with the dot-notation key set to value."""
    keys = key.split(".")
    new_data = copy.deepcopy(data)
    current_level: Any = new_data
    for i, k in enumerate(keys):
        if i == len(keys) - 1:
            current_level[k] = value
            break
        if not isinstance(current_level, dict):
            raise ValueError(
                f"Cannot set nested key '{key}': '{'.'.join(keys[: i + 1])}' is not a dictionary."
            )
        if k not in current_level or not isinstance(current_level[k], dict):
            current_level[k] = {}
        current_level = current_level[k]
    return new_data


def _remove_path(*, data: JSON, key: str) -> JSON:
    """Return a deep copy of data with the dot-notation key removed, if present."""
    keys = key.split(".")
    new_data = copy.deepcopy(data)
    parent: Any = new_data
    for k in keys[:-1]:
        if not isinstance(parent, dict) or k not in parent:
            return new_data
        parent = parent[k]
    if isinstance(parent, dict):
        parent.pop(keys[-1], None)
    return new_data


class Context(BaseModel):
    """
    An immutable context object for agentic workflows.

    Context holds key-value pairs representing the current state and information.
    Any 'modification' to the context returns a new Context instance.
    """

    model_config = {"frozen": True}

    data: JSON = Field(default_factory=dict)
    patch_history: tuple[ContextPatch, ...] = Field(default_factory=tuple)

    def state_hash(self) -> str:
        """
        Compute a deterministic SHA256 hash of the context state.
        Includes both data and patch history (provenance).
        """
        import hashlib
        import json

        # Sort keys for determinism
        data_json = json.dumps(self.data, sort_keys=True)
        # Include patch IDs in hash for provenance-aware caching
        patch_ids = ",".join(p.id for p in self.patch_history)

        state_str = f"{data_json}|{patch_ids}"
        return hashlib.sha256(state_str.encode()).hexdigest()

    def get_timeline(self) -> tuple[ContextPatch, ...]:
        """Return the full sequence of patches that created this context."""
        return self.patch_history

    def rollback_to(self, patch_id: str | None) -> Context:
        """
        Reconstruct the context state as it was after a specific patch was applied.
        If patch_id is None, returns an empty context.
        """
        if patch_id is None:
            return Context()

        new_history: list[ContextPatch] = []
        found = False
        for patch in self.patch_history:
            new_history.append(patch)
            if patch.id == patch_id:
                found = True
                break

        if not found:
            raise ValueError(f"Patch ID '{patch_id}' not found in history.")

        # Reconstruct state from scratch to ensure correctness
        ctx = Context()
        for p in new_history:
            ctx = ctx.apply(p)
        return ctx

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
        """Return a new Context with key set, recording a SET patch."""
        return self.apply(ContextPatch.set(path=key, value=value))

    def merge(self, other: Context) -> Context:
        """Return a new Context with other's top-level keys set, each recorded as a SET patch."""
        result = self
        for key, value in other.data.items():
            result = result.set(key, value)
        return result

    def merge_branches(
        self,
        branches: list[Context],
        strategy: MergeStrategy | None = None,  # type: ignore[name-defined]  # noqa: F821
    ) -> MergeResult:  # type: ignore[name-defined]  # noqa: F821
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
        """Return a deep copy of the underlying data, so callers cannot mutate this context."""
        return copy.deepcopy(self.data)

    def to_checkpoint_dict(self) -> JSON:
        """Serialize data and patch history for durable checkpoint storage."""
        return {
            "data": self.data,
            "patch_history": [patch.to_dict() for patch in self.patch_history],
        }

    @classmethod
    def from_dict(cls, data: JSON) -> Context:
        """Create a Context instance from a dictionary."""
        return cls(data=data)

    @classmethod
    def from_checkpoint_dict(cls, payload: JSON) -> Context:
        """Restore a Context from a checkpoint payload (data + patch history)."""
        if "patch_history" in payload:
            patches = tuple(ContextPatch.from_dict(item) for item in payload.get("patch_history", []))
            return cls(data=payload.get("data", {}), patch_history=patches)
        return cls(data=payload.get("data", payload))

    def delete(self, key: str) -> Context:
        """Return a new Context with key removed, recording a DELETE patch."""
        return self.apply(ContextPatch.delete(path=key))

    def append(self, key: str, value: Any) -> Context:
        """Return a new Context with value appended to the list at key, recording an APPEND patch."""
        return self.apply(ContextPatch(path=key, operation=PatchOperation.APPEND, value=value))

    def deep_merge(self, key: str, value: dict[str, Any]) -> Context:
        """Return a new Context with value deep-merged into the dict at key, recording a MERGE patch."""
        return self.apply(ContextPatch(path=key, operation=PatchOperation.MERGE, value=value))

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

    def apply(self, patch: ContextPatch) -> Context:
        """
        Apply a ContextPatch and return a new Context.

        Every state change goes through here, so patch_history always replays to the same state.

        Args:
            patch: The patch to apply

        Returns:
            New Context with the patch applied
        """
        new_history = self.patch_history + (patch,)

        if patch.operation == PatchOperation.SET:
            new_data = _write_path(data=self.data, key=patch.path, value=patch.value)
        elif patch.operation == PatchOperation.DELETE:
            new_data = _remove_path(data=self.data, key=patch.path)
        elif patch.operation == PatchOperation.MERGE:
            existing = self.get(patch.path, {})
            base = dict(existing) if isinstance(existing, dict) else {}
            merged = self._deep_merge_dicts(base, patch.value)
            new_data = _write_path(data=self.data, key=patch.path, value=merged)
        elif patch.operation == PatchOperation.APPEND:
            existing = self.get(patch.path, [])
            items = existing if isinstance(existing, list) else [existing]
            new_data = _write_path(data=self.data, key=patch.path, value=[*items, patch.value])
        else:
            new_data = copy.deepcopy(self.data)

        return Context(data=new_data, patch_history=new_history)

    def diff(self, other: Context) -> tuple[ContextPatch, ...]:
        """
        Generate patches to transform self into other.

        Args:
            other: Target context

        Returns:
            Tuple of patches that, when applied to self, produce other
        """

        patches: list[ContextPatch] = []
        self._diff_recursive("", self.data, other.data, patches)
        return tuple(patches)

    def _diff_recursive(
        self,
        prefix: str,
        old: Any,
        new: Any,
        patches: list[ContextPatch],
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

    def copy_context(self) -> Context:
        """Create a deep copy of the context."""
        import copy

        return Context(
            data=copy.deepcopy(self.data),
            patch_history=copy.deepcopy(self.patch_history),
        )

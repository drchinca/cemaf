"""
cemaf.context.context - Manages the flow and state of context within agentic workflows.

This module introduces an immutable Context object that encapsulates the dynamic state
and information available to agents and nodes during execution.
"""

from __future__ import annotations

from typing import Any, Mapping

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
        keys = key.split('.')
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
        keys = key.split('.')
        new_data = dict(self.data)  # Start with a copy

        current_level = new_data
        for i, k in enumerate(keys):
            if i == len(keys) - 1:  # Last key
                current_level[k] = value
            else:
                if not isinstance(current_level, dict):
                    # If an intermediate key is not a dict, we can't set nested
                    raise ValueError(f"Cannot set nested key '{key}': '{'.'.join(keys[:i+1])}' is not a dictionary.")
                if k not in current_level or not isinstance(current_level[k], dict):
                    current_level[k] = {} # Create dict if it doesn't exist or is not a dict
                current_level = current_level[k]
        
        return Context(data=new_data)

    def merge(self, other: Context) -> Context:
        """
        Return a new Context by merging another Context into this one.
        Values from 'other' will overwrite values in 'self'.
        Performs a shallow merge for top-level keys.
        """
        merged_data = {**self.data, **other.data}
        return Context(data=merged_data)

    def to_dict(self) -> JSON:
        """Return the underlying data as a dictionary."""
        return self.data
    
    @classmethod
    def from_dict(cls, data: JSON) -> Context:
        """Create a Context instance from a dictionary."""
        return cls(data=data)

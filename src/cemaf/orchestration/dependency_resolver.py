"""
Dependency Resolver - Regex-based context chaining for DAG execution.

Resolves placeholders like $$STEP_N_OUTPUT$$ from the Context,
enabling resilient context chaining between nodes.
"""

import copy
import logging
import re
from typing import Any, cast

from cemaf.context.context import Context

logger = logging.getLogger(__name__)


def resolve_dependencies(input_params: dict[str, Any], context: Context) -> dict[str, Any]:
    """
    Resolve $$STEP_N_OUTPUT$$ placeholders in input parameters using regex.

    Uses regex to find placeholders within strings, making context chaining
    resilient against extraneous LLM text.

    Args:
        input_params: Input parameters dictionary (may contain placeholders)
        context: CEMAF Context object containing resolved values

    Returns:
        Resolved input parameters with placeholders replaced

    Example:
        >>> context = Context(data={"STEP_1_OUTPUT": "blueprint_json"})
        >>> input_params = {"blueprint": "$$STEP_1_OUTPUT$$"}
        >>> resolved = resolve_dependencies(input_params, context)
        >>> assert resolved["blueprint"] == "blueprint_json"
    """
    resolved_input = copy.deepcopy(input_params)
    # Pattern to match $$STEP_1_OUTPUT$$, $$STEP_2_OUTPUT$$, etc.
    pattern = r"\$\$(STEP_\d+_OUTPUT)\$\$"

    def resolve(value: Any) -> Any:
        """Recursively resolve placeholders in a value."""
        if isinstance(value, str):
            matches = re.findall(pattern, value)
            if not matches:
                return value

            # If the value is EXACTLY one placeholder, return the raw object (could be dict/list)
            if re.fullmatch(pattern, value.strip()):
                ref_key = matches[0]
                resolved_value = context.get(ref_key, value)
                return resolved_value

            # If the placeholder is embedded in text, replace with string representation
            resolved_value = value
            for ref_key in matches:
                replacement = str(context.get(ref_key, f"$${ref_key}$$"))
                resolved_value = resolved_value.replace(f"$${ref_key}$$", replacement)
            return resolved_value

        elif isinstance(value, dict):
            return {k: resolve(v) for k, v in value.items()}
        elif isinstance(value, list):
            return [resolve(item) for item in value]
        return value

    return cast(dict[str, Any], resolve(resolved_input))


def resolve_node_input(node_input_mapping: dict[str, Any], context: Context) -> dict[str, Any]:
    """
    Resolve a node's input_mapping using context.

    This is a convenience wrapper that handles the common case of resolving
    node input mappings before execution.

    Args:
        node_input_mapping: Node's input_mapping dictionary
        context: Current execution context

    Returns:
        Resolved input mapping ready for node execution
    """
    return resolve_dependencies(node_input_mapping, context)

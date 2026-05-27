"""
Dependency Resolver - Regex-based context chaining for DAG execution.

Resolves $$key$$ and $$key.subkey$$ placeholders from the Context, enabling
typed context chaining between nodes. Any string wrapped in $$ markers is
treated as a context reference.

Supported patterns:
  $$STEP_1_OUTPUT$$         → context["STEP_1_OUTPUT"] (legacy CEMAF convention)
  $$scrape_result$$         → context["scrape_result"] (arbitrary output_key)
  $$scrape_result.posts$$   → context["scrape_result"]["posts"] (dot-path access)
"""

import copy
import logging
import re
from typing import Any, cast

from cemaf.context.context import Context

logger = logging.getLogger(__name__)

# Match any $$<identifier>[.identifier]*$$ pattern.
# Captures the inner path (e.g. "scrape_result.posts" or "STEP_1_OUTPUT").
_PLACEHOLDER = re.compile(r"\$\$([\w]+(?:\.[\w]+)*)\$\$")


def _resolve_path(context: Context, path: str, fallback: Any = None) -> Any:
    """Resolve a dot-separated path against the context.

    "scrape_result" → context.get("scrape_result")
    "scrape_result.posts" → context.get("scrape_result")["posts"]
    """
    parts = path.split(".")
    value = context.get(parts[0], default=None)
    if value is None:
        return fallback

    for part in parts[1:]:
        if isinstance(value, dict):
            value = value.get(part)
        elif hasattr(value, part):
            value = getattr(value, part)
        else:
            return fallback
        if value is None:
            return fallback
    return value


def resolve_dependencies(input_params: dict[str, Any], context: Context) -> dict[str, Any]:
    """
    Resolve $$key$$ and $$key.subkey$$ placeholders in input parameters.

    If a value is EXACTLY one placeholder (e.g. "$$scrape_result$$"), the raw
    object (dict, list, Pydantic model) is returned — not a string. If the
    placeholder is embedded in surrounding text, it's stringified in-place.

    Examples:
        >>> context = Context(data={"scrape_result": {"bio": "hello", "posts": [1,2]}})
        >>> resolve_dependencies({"bio": "$$scrape_result.bio$$"}, context)
        {"bio": "hello"}
        >>> resolve_dependencies({"all": "$$scrape_result$$"}, context)
        {"all": {"bio": "hello", "posts": [1, 2]}}
    """
    resolved_input = copy.deepcopy(input_params)

    def resolve(value: Any) -> Any:
        """Recursively resolve placeholders in a value."""
        if isinstance(value, str):
            matches = _PLACEHOLDER.findall(value)
            if not matches:
                return value

            # If the value is EXACTLY one placeholder, return the raw object.
            # If the key doesn't exist in context (e.g. optional node didn't run),
            # return None so Pydantic goal field defaults can kick in.
            if _PLACEHOLDER.fullmatch(value.strip()):
                return _resolve_path(context, matches[0], fallback=None)

            # Multiple placeholders or embedded in text → string interpolation
            resolved_value = value
            for path in matches:
                replacement = _resolve_path(context, path, fallback=f"$${path}$$")
                resolved_value = resolved_value.replace(f"$${path}$$", str(replacement))
            return resolved_value

        elif isinstance(value, dict):
            return {k: resolve(v) for k, v in value.items()}
        elif isinstance(value, list):
            return [resolve(item) for item in value]
        return value

    return cast(dict[str, Any], resolve(resolved_input))


def resolve_node_input(node_input_mapping: dict[str, Any], context: Context) -> dict[str, Any]:
    """Resolve a node's input_mapping using context.

    Convenience wrapper for the common case of resolving node input
    mappings before execution.

    Args:
        node_input_mapping: Node's input_mapping dictionary
        context: Current execution context

    Returns:
        Resolved input mapping ready for node execution
    """
    return resolve_dependencies(node_input_mapping, context)

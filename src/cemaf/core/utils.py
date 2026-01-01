"""
Core utilities for consistent patterns across the codebase.

Provides:
- utc_now(): Consistent UTC datetime
- generate_id(): Consistent ID generation
- safe_json(): Safe JSON serialization
"""

import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4


def utc_now() -> datetime:
    """
    Get current UTC datetime.

    Use this instead of datetime.now() or datetime.now(timezone.utc)
    for consistency across the codebase.
    """
    return datetime.now(UTC)


def generate_id(prefix: str = "") -> str:
    """
    Generate a unique ID.

    Args:
        prefix: Optional prefix for the ID (e.g., "run", "agent", "task")

    Returns:
        Unique ID string like "run_a1b2c3d4" or "a1b2c3d4"

    Example:
        >>> generate_id("run")
        'run_a1b2c3d4'
        >>> generate_id()
        'a1b2c3d4e5f6g7h8'
    """
    uid = uuid4().hex[:16]
    if prefix:
        return f"{prefix}_{uid[:8]}"
    return uid


def safe_json(obj: Any) -> Any:
    """
    Convert an object to JSON-safe format.

    Handles datetime, sets, bytes, and custom objects.
    """
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj

    if isinstance(obj, datetime):
        return obj.isoformat()

    if isinstance(obj, bytes):
        return obj.decode("utf-8", errors="replace")

    if isinstance(obj, (set, frozenset)):
        return list(obj)

    if isinstance(obj, dict):
        return {k: safe_json(v) for k, v in obj.items()}

    if isinstance(obj, (list, tuple)):
        return [safe_json(item) for item in obj]

    # Try common patterns
    if hasattr(obj, "model_dump"):  # Pydantic
        return safe_json(obj.model_dump())

    if hasattr(obj, "__dict__"):
        return safe_json(vars(obj))

    # Last resort
    return str(obj)


def json_dumps(obj: Any, **kwargs: Any) -> str:
    """
    Safe JSON serialization.

    Handles datetime, bytes, sets, and other non-JSON types.
    """
    return json.dumps(safe_json(obj), **kwargs)


def truncate(text: str, max_length: int = 100, suffix: str = "...") -> str:
    """
    Truncate text to max length.

    Args:
        text: Text to truncate
        max_length: Maximum length including suffix
        suffix: Suffix to add when truncated

    Returns:
        Truncated text
    """
    if len(text) <= max_length:
        return text
    return text[: max_length - len(suffix)] + suffix

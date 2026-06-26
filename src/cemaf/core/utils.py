"""
Core utilities for consistent patterns across the codebase.

Provides:
- utc_now(): Consistent UTC datetime
- generate_id(): Consistent ID generation
- safe_json(): Safe JSON serialization
"""

import json
import re
from datetime import UTC, datetime
from pathlib import Path
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


def resolve_path(
    path: str | Path,
    *,
    base_dir: str | Path | None = None,
    prefer_existing: bool = False,
) -> Path:
    """
    Resolve a filesystem path with optional base directory semantics.

    Args:
        path: Absolute or relative path to resolve.
        base_dir: Optional directory used to resolve relative paths.
        prefer_existing: When True, return the base-dir candidate if it already
            exists on disk; otherwise continue to the normal resolved path.
    """

    resolved = Path(path).expanduser()
    if resolved.is_absolute():
        return resolved.resolve()

    if base_dir is not None:
        candidate = (Path(base_dir).expanduser() / resolved).resolve()
        if prefer_existing:
            if candidate.exists():
                return candidate
        else:
            return candidate

    return resolved.resolve()


def json_dumps(obj: Any, **kwargs: Any) -> str:
    """
    Safe JSON serialization.

    Handles datetime, bytes, sets, and other non-JSON types.
    """
    return json.dumps(safe_json(obj), **kwargs)


def parse_jsonish(text: str, *, allow_comments: bool = False) -> Any:
    """
    Parse the first balanced JSON object or array embedded in text.

    Tolerates markdown fences, preamble/trailing prose, and optional inline
    ``//`` comments when ``allow_comments`` is enabled.
    """

    source = text.strip()
    if allow_comments:
        source = re.sub(r"(?m)\s+//.*$", "", source)

    starts = [idx for idx in (source.find("{"), source.find("[")) if idx != -1]
    if not starts:
        raise RuntimeError("No JSON value found in text")

    start = min(starts)
    stack: list[str] = []
    in_string = False
    escape_next = False
    pairs = {"{": "}", "[": "]"}
    closers = {value: key for key, value in pairs.items()}

    for index in range(start, len(source)):
        char = source[index]
        if in_string:
            if escape_next:
                escape_next = False
            elif char == "\\":
                escape_next = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
            continue
        if char in pairs:
            stack.append(char)
            continue
        if char in closers:
            if not stack or stack[-1] != closers[char]:
                raise RuntimeError("Unbalanced JSON value in text")
            stack.pop()
            if not stack:
                payload = source[start : index + 1]
                try:
                    return json.loads(payload)
                except json.JSONDecodeError as exc:
                    raise RuntimeError(f"Could not decode JSON from text: {exc}") from exc

    raise RuntimeError("Unbalanced JSON value in text")


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

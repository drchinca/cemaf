"""Shared validation helpers for embedding vectors."""

from __future__ import annotations

from collections.abc import Iterable


def require_positive_dimension(dimension: int, *, label: str = "dimension") -> int:
    """Validate an embedding/vector dimension value."""
    if dimension <= 0:
        raise ValueError(f"{label} must be positive, got {dimension}")
    return dimension


def normalize_embedding_dimension(
    embedding: Iterable[float] | None,
    *,
    expected_dimension: int,
    label: str = "embedding",
) -> tuple[float, ...]:
    """Return a numeric embedding tuple after validating its dimension."""
    if embedding is None:
        raise ValueError(f"{label} is required")

    try:
        vector = tuple(float(value) for value in embedding)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a numeric vector") from exc

    if len(vector) != expected_dimension:
        raise ValueError(f"{label} has dimension {len(vector)}; expected {expected_dimension}")
    return vector

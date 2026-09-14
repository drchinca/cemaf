"""DataSourceRegistry error types.

Subclass ValueError so callers doing broad `except ValueError` around
construction-time config validation (the pattern InterceptorPipeline's
duplicate-id check already uses) catch these too.
"""

from __future__ import annotations


class DuplicateSourceError(ValueError):
    """Raised when register() is called with a source_id already registered."""


class ReadOnlyViolationError(ValueError):
    """Raised when a DataSource's concrete class exposes public surface beyond
    {retrieve, health, source_id, capabilities}, is missing a required member,
    or (via DataSourceRegistry's tenant-offset validation) declares a priority
    offset outside the allowed ±10 range."""

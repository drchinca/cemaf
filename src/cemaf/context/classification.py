"""Context type classification — behavioral semantics for context sources."""

from dataclasses import dataclass

from cemaf.context.source import ContextType


@dataclass(frozen=True)
class ContextTypeBehavior:
    """Behavioral rules for a context type."""

    cacheable: bool
    shareable: bool
    compressible: bool
    default_ttl_seconds: float | None
    default_priority: int
    preferred_compaction: str  # "full", "summary", or "metadata" — matches CompactionLevel values


CONTEXT_TYPE_BEHAVIORS: dict[ContextType, ContextTypeBehavior] = {
    ContextType.RESOURCE: ContextTypeBehavior(
        cacheable=True,
        shareable=True,
        compressible=True,
        default_ttl_seconds=None,
        default_priority=3,
        preferred_compaction="summary",
    ),
    ContextType.MEMORY: ContextTypeBehavior(
        cacheable=False,
        shareable=False,
        compressible=True,
        default_ttl_seconds=86400.0,
        default_priority=7,
        preferred_compaction="metadata",
    ),
    ContextType.SKILL: ContextTypeBehavior(
        cacheable=True,
        shareable=True,
        compressible=False,
        default_ttl_seconds=None,
        default_priority=5,
        preferred_compaction="full",
    ),
}


_SOURCE_TYPE_MAP: dict[str, ContextType] = {
    "document": ContextType.RESOURCE,
    "tool_output": ContextType.RESOURCE,
    "memory": ContextType.MEMORY,
    "system": ContextType.SKILL,
}


def classify_source(source_type: str) -> ContextType:
    """Map existing string source_types to ContextType."""
    return _SOURCE_TYPE_MAP.get(source_type, ContextType.RESOURCE)


def get_behavior(context_type: ContextType) -> ContextTypeBehavior:
    """Look up behavioral rules for a context type."""
    return CONTEXT_TYPE_BEHAVIORS[context_type]

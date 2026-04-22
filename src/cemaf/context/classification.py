"""Context type classification — behavioral semantics for context sources."""

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

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


@runtime_checkable
class ContextTypeClassifier(Protocol):
    """Protocol for classifying context sources and resolving behavior."""

    def classify(self, source_type: str) -> ContextType: ...

    def get_behavior(self, context_type: ContextType) -> ContextTypeBehavior: ...


class DefaultContextTypeClassifier:
    """Default classifier using a configurable behavior registry."""

    def __init__(
        self,
        *,
        behaviors: dict[ContextType, ContextTypeBehavior] | None = None,
        source_type_map: dict[str, ContextType] | None = None,
    ) -> None:
        self._behaviors = behaviors or DEFAULT_BEHAVIORS
        self._source_type_map = source_type_map or DEFAULT_SOURCE_TYPE_MAP

    def classify(self, source_type: str) -> ContextType:
        """Map a string source_type to ContextType."""
        return self._source_type_map.get(source_type, ContextType.RESOURCE)

    def get_behavior(self, context_type: ContextType) -> ContextTypeBehavior:
        """Look up behavioral rules for a context type."""
        return self._behaviors[context_type]


DEFAULT_BEHAVIORS: dict[ContextType, ContextTypeBehavior] = {
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
    ContextType.SPEC: ContextTypeBehavior(
        cacheable=True,
        shareable=True,
        compressible=False,
        default_ttl_seconds=None,
        default_priority=8,
        preferred_compaction="full",
    ),
}

DEFAULT_SOURCE_TYPE_MAP: dict[str, ContextType] = {
    "document": ContextType.RESOURCE,
    "tool_output": ContextType.RESOURCE,
    "memory": ContextType.MEMORY,
    "system": ContextType.SKILL,
    "spec": ContextType.SPEC,
}


# Module-level convenience functions delegating to a default instance
_default_classifier = DefaultContextTypeClassifier()


def classify_source(source_type: str) -> ContextType:
    """Map existing string source_types to ContextType."""
    return _default_classifier.classify(source_type=source_type)


def get_behavior(context_type: ContextType) -> ContextTypeBehavior:
    """Look up behavioral rules for a context type."""
    return _default_classifier.get_behavior(context_type=context_type)

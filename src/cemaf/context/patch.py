"""
Context patch system for tracking provenance of context changes.

This module provides:
- ContextPatch: An immutable record of a context change
- PatchOperation: The type of change (SET, DELETE, MERGE, APPEND)
- PatchSource: Who/what made the change (TOOL, AGENT, LLM, SYSTEM, USER)
- PatchLog: An append-only log of patches for replay/debugging

Note: Uses PEP 563 (from __future__ import annotations) to defer annotation evaluation
and avoid circular imports with cemaf.context.context.
Type imports happen at runtime within methods that need them.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from cemaf.core.utils import generate_id, utc_now


class PatchOperation(str, Enum):
    """Type of operation performed on context."""

    SET = "set"  # Set a value at a path
    DELETE = "delete"  # Remove a value at a path
    MERGE = "merge"  # Deep merge a dict into existing dict
    APPEND = "append"  # Append to a list


class PatchSource(str, Enum):
    """Source of a context change."""

    TOOL = "tool"  # Change from a tool execution
    AGENT = "agent"  # Change from an agent
    LLM = "llm"  # Change from LLM output parsing
    SYSTEM = "system"  # Change from system/framework
    USER = "user"  # Change from user input


@dataclass(frozen=True)
class ContextPatch:
    """
    An immutable record of a context change with full provenance.

    Tracks:
    - What changed (path, operation, value)
    - Who changed it (source, source_id)
    - When it changed (timestamp)
    - Why it changed (reason)
    - Correlation (correlation_id for tracing)

    Example:
        patch = ContextPatch(
            path="user.preferences.theme",
            operation=PatchOperation.SET,
            value="dark",
            source=PatchSource.TOOL,
            source_id="settings_tool",
            reason="User requested dark theme",
        )
    """

    path: str  # Dot-notation path, e.g., "user.preferences.theme"
    operation: PatchOperation
    value: Any = None  # The new value (None for DELETE)

    # Provenance
    source: PatchSource = PatchSource.SYSTEM
    source_id: str = ""  # e.g., "web_search", "research_agent"
    timestamp: datetime = field(default_factory=utc_now)
    reason: str = ""  # Human-readable explanation
    correlation_id: str | None = None  # For tracing related changes

    # Auto-generated
    id: str = field(default_factory=lambda: generate_id("patch"))

    @classmethod
    def set(
        cls,
        path: str,
        value: Any,
        *,
        source: PatchSource = PatchSource.SYSTEM,
        source_id: str = "",
        reason: str = "",
        correlation_id: str | None = None,
    ) -> ContextPatch:
        """Create a SET patch."""
        return cls(
            path=path,
            operation=PatchOperation.SET,
            value=value,
            source=source,
            source_id=source_id,
            reason=reason,
            correlation_id=correlation_id,
        )

    @classmethod
    def delete(
        cls,
        path: str,
        *,
        source: PatchSource = PatchSource.SYSTEM,
        source_id: str = "",
        reason: str = "",
        correlation_id: str | None = None,
    ) -> ContextPatch:
        """Create a DELETE patch."""
        return cls(
            path=path,
            operation=PatchOperation.DELETE,
            value=None,
            source=source,
            source_id=source_id,
            reason=reason,
            correlation_id=correlation_id,
        )

    @classmethod
    def merge(
        cls,
        path: str,
        value: dict[str, Any],
        *,
        source: PatchSource = PatchSource.SYSTEM,
        source_id: str = "",
        reason: str = "",
        correlation_id: str | None = None,
    ) -> ContextPatch:
        """Create a MERGE patch."""
        return cls(
            path=path,
            operation=PatchOperation.MERGE,
            value=value,
            source=source,
            source_id=source_id,
            reason=reason,
            correlation_id=correlation_id,
        )

    @classmethod
    def append(
        cls,
        path: str,
        value: Any,
        *,
        source: PatchSource = PatchSource.SYSTEM,
        source_id: str = "",
        reason: str = "",
        correlation_id: str | None = None,
    ) -> ContextPatch:
        """Create an APPEND patch."""
        return cls(
            path=path,
            operation=PatchOperation.APPEND,
            value=value,
            source=source,
            source_id=source_id,
            reason=reason,
            correlation_id=correlation_id,
        )

    @classmethod
    def from_tool(
        cls,
        tool_id: str,
        path: str,
        value: Any,
        *,
        operation: PatchOperation = PatchOperation.SET,
        reason: str = "",
        correlation_id: str | None = None,
    ) -> ContextPatch:
        """Create a patch from a tool execution."""
        return cls(
            path=path,
            operation=operation,
            value=value,
            source=PatchSource.TOOL,
            source_id=tool_id,
            reason=reason or f"Set by tool '{tool_id}'",
            correlation_id=correlation_id,
        )

    @classmethod
    def from_agent(
        cls,
        agent_id: str,
        path: str,
        value: Any,
        *,
        operation: PatchOperation = PatchOperation.SET,
        reason: str = "",
        correlation_id: str | None = None,
    ) -> ContextPatch:
        """Create a patch from an agent."""
        return cls(
            path=path,
            operation=operation,
            value=value,
            source=PatchSource.AGENT,
            source_id=agent_id,
            reason=reason or f"Set by agent '{agent_id}'",
            correlation_id=correlation_id,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert patch to dictionary for serialization."""
        return {
            "id": self.id,
            "path": self.path,
            "operation": self.operation.value,
            "value": self.value,
            "source": self.source.value,
            "source_id": self.source_id,
            "timestamp": self.timestamp.isoformat(),
            "reason": self.reason,
            "correlation_id": self.correlation_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ContextPatch:
        """Create patch from dictionary."""
        return cls(
            id=data.get("id", generate_id("patch")),
            path=data["path"],
            operation=PatchOperation(data["operation"]),
            value=data.get("value"),
            source=PatchSource(data.get("source", "system")),
            source_id=data.get("source_id", ""),
            timestamp=datetime.fromisoformat(data["timestamp"]) if "timestamp" in data else utc_now(),
            reason=data.get("reason", ""),
            correlation_id=data.get("correlation_id"),
        )


@dataclass(frozen=True)
class PatchLog:
    """
    An append-only log of context patches.

    Provides:
    - Immutable append (returns new PatchLog)
    - Replay capability
    - Filtering by source, time range, correlation_id

    Example:
        log = PatchLog()
        log = log.append(patch1)
        log = log.append(patch2)

        # Replay patches on initial context
        final_context = log.replay(initial_context)

        # Filter patches
        tool_patches = log.filter_by_source(PatchSource.TOOL)
    """

    patches: tuple[ContextPatch, ...] = ()

    def __len__(self) -> int:
        return len(self.patches)

    def __iter__(self) -> Iterator[ContextPatch]:
        return iter(self.patches)

    def __getitem__(self, index: int) -> ContextPatch:
        return self.patches[index]

    def append(self, patch: ContextPatch) -> PatchLog:
        """Append a patch and return a new PatchLog."""
        return PatchLog(patches=self.patches + (patch,))

    def extend(self, patches: tuple[ContextPatch, ...] | list[ContextPatch]) -> PatchLog:
        """Extend with multiple patches and return a new PatchLog."""
        return PatchLog(patches=self.patches + tuple(patches))

    def replay(self, initial: Context) -> Context:  # noqa: F821
        """
        Replay all patches on an initial context.

        Args:
            initial: Starting context

        Returns:
            Final context after applying all patches
        """
        context = initial
        for patch in self.patches:
            context = context.apply(patch)
        return context

    def filter_by_source(self, source: PatchSource) -> PatchLog:
        """Filter patches by source type."""
        filtered = tuple(p for p in self.patches if p.source == source)
        return PatchLog(patches=filtered)

    def filter_by_source_id(self, source_id: str) -> PatchLog:
        """Filter patches by source ID."""
        filtered = tuple(p for p in self.patches if p.source_id == source_id)
        return PatchLog(patches=filtered)

    def filter_by_correlation_id(self, correlation_id: str) -> PatchLog:
        """Filter patches by correlation ID."""
        filtered = tuple(p for p in self.patches if p.correlation_id == correlation_id)
        return PatchLog(patches=filtered)

    def filter_by_path_prefix(self, prefix: str) -> PatchLog:
        """Filter patches by path prefix."""
        filtered = tuple(p for p in self.patches if p.path.startswith(prefix))
        return PatchLog(patches=filtered)

    def filter_by_time_range(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> PatchLog:
        """Filter patches by time range."""
        filtered = []
        for patch in self.patches:
            if start and patch.timestamp < start:
                continue
            if end and patch.timestamp > end:
                continue
            filtered.append(patch)
        return PatchLog(patches=tuple(filtered))

    def to_list(self) -> list[dict[str, Any]]:
        """Convert to list of dicts for serialization."""
        return [p.to_dict() for p in self.patches]

    @classmethod
    def from_list(cls, data: list[dict[str, Any]]) -> PatchLog:
        """Create PatchLog from list of dicts."""
        patches = tuple(ContextPatch.from_dict(d) for d in data)
        return cls(patches=patches)

    def get_affected_paths(self) -> set[str]:
        """Get all paths affected by patches in this log."""
        return {p.path for p in self.patches}

    def get_latest_for_path(self, path: str) -> ContextPatch | None:
        """Get the most recent patch for a given path."""
        for patch in reversed(self.patches):
            if patch.path == path:
                return patch
        return None

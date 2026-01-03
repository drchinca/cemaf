"""
Run logger for recording and replaying agent runs.

This module provides:
- ToolCall: Record of a single tool invocation
- RunRecord: Complete record of an agent run
- RunLogger: Protocol for recording runs
- InMemoryRunLogger: In-memory implementation

Note: Uses PEP 563 (from __future__ import annotations) to defer annotation evaluation
and avoid circular imports with cemaf.context.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from cemaf.core.types import JSON
from cemaf.core.utils import generate_id, utc_now


@dataclass(frozen=True)
class ToolCall:
    """
    Record of a single tool invocation.

    Captures:
    - What tool was called (tool_id)
    - What input it received (input)
    - What output it produced (output)
    - How long it took (duration_ms)
    - When it happened (timestamp)
    - Tracing info (correlation_id)
    """

    tool_id: str
    input: JSON
    output: JSON
    duration_ms: float = 0.0
    timestamp: datetime = field(default_factory=utc_now)
    correlation_id: str = ""
    success: bool = True
    error: str | None = None

    # Auto-generated
    id: str = field(default_factory=lambda: generate_id("call"))

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "tool_id": self.tool_id,
            "input": self.input,
            "output": self.output,
            "duration_ms": self.duration_ms,
            "timestamp": self.timestamp.isoformat(),
            "correlation_id": self.correlation_id,
            "success": self.success,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ToolCall:
        """Create ToolCall from dictionary."""
        return cls(
            id=data.get("id", generate_id("call")),
            tool_id=data["tool_id"],
            input=data.get("input", {}),
            output=data.get("output", {}),
            duration_ms=data.get("duration_ms", 0.0),
            timestamp=datetime.fromisoformat(data["timestamp"]) if "timestamp" in data else utc_now(),
            correlation_id=data.get("correlation_id", ""),
            success=data.get("success", True),
            error=data.get("error"),
        )


@dataclass(frozen=True)
class LLMCall:
    """
    Record of a single LLM invocation.

    Captures:
    - Model used
    - Input messages/prompt
    - Output response
    - Token usage
    - Duration
    """

    model: str
    input_messages: list[dict[str, Any]]
    output: str
    input_tokens: int = 0
    output_tokens: int = 0
    duration_ms: float = 0.0
    timestamp: datetime = field(default_factory=utc_now)
    correlation_id: str = ""

    # Auto-generated
    id: str = field(default_factory=lambda: generate_id("llm"))

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "model": self.model,
            "input_messages": self.input_messages,
            "output": self.output,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "duration_ms": self.duration_ms,
            "timestamp": self.timestamp.isoformat(),
            "correlation_id": self.correlation_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LLMCall:
        """Create LLMCall from dictionary."""
        return cls(
            id=data.get("id", generate_id("llm")),
            model=data.get("model", ""),
            input_messages=data.get("input_messages", []),
            output=data.get("output", ""),
            input_tokens=data.get("input_tokens", 0),
            output_tokens=data.get("output_tokens", 0),
            duration_ms=data.get("duration_ms", 0.0),
            timestamp=datetime.fromisoformat(data["timestamp"]) if "timestamp" in data else utc_now(),
            correlation_id=data.get("correlation_id", ""),
        )


@dataclass
class RunRecord:
    """
    Complete record of an agent run.

    Contains:
    - Run metadata (run_id, dag_name, started_at, completed_at)
    - Initial and final context
    - All patches applied
    - All tool calls made
    - All LLM calls made
    """

    run_id: str
    dag_name: str = ""
    initial_context: Context | None = None  # noqa: F821
    final_context: Context | None = None  # noqa: F821
    patches: list[ContextPatch] = field(default_factory=list)  # noqa: F821
    tool_calls: list[ToolCall] = field(default_factory=list)
    llm_calls: list[LLMCall] = field(default_factory=list)
    started_at: datetime = field(default_factory=utc_now)
    completed_at: datetime | None = None
    success: bool = True
    error: str | None = None
    metadata: JSON = field(default_factory=dict)

    @property
    def duration_ms(self) -> float:
        """Total duration in milliseconds."""
        if not self.completed_at:
            return 0.0
        delta = self.completed_at - self.started_at
        return delta.total_seconds() * 1000

    @property
    def total_tool_calls(self) -> int:
        """Total number of tool calls."""
        return len(self.tool_calls)

    @property
    def total_llm_calls(self) -> int:
        """Total number of LLM calls."""
        return len(self.llm_calls)

    @property
    def total_patches(self) -> int:
        """Total number of patches."""
        return len(self.patches)

    @property
    def total_tokens(self) -> int:
        """Total tokens used across all LLM calls."""
        return sum(c.input_tokens + c.output_tokens for c in self.llm_calls)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "run_id": self.run_id,
            "dag_name": self.dag_name,
            "initial_context": self.initial_context.to_dict() if self.initial_context else None,
            "final_context": self.final_context.to_dict() if self.final_context else None,
            "patches": [p.to_dict() for p in self.patches],
            "tool_calls": [t.to_dict() for t in self.tool_calls],
            "llm_calls": [llm_call.to_dict() for llm_call in self.llm_calls],
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "success": self.success,
            "error": self.error,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RunRecord:
        """Create RunRecord from dictionary."""
        from cemaf.context.context import Context
        from cemaf.context.patch import ContextPatch

        initial_ctx = None
        if data.get("initial_context"):
            initial_ctx = Context.from_dict(data["initial_context"])

        final_ctx = None
        if data.get("final_context"):
            final_ctx = Context.from_dict(data["final_context"])

        return cls(
            run_id=data["run_id"],
            dag_name=data.get("dag_name", ""),
            initial_context=initial_ctx,
            final_context=final_ctx,
            patches=[ContextPatch.from_dict(p) for p in data.get("patches", [])],
            tool_calls=[ToolCall.from_dict(t) for t in data.get("tool_calls", [])],
            llm_calls=[LLMCall.from_dict(llm_call) for llm_call in data.get("llm_calls", [])],
            started_at=datetime.fromisoformat(data["started_at"]) if "started_at" in data else utc_now(),
            completed_at=datetime.fromisoformat(data["completed_at"]) if data.get("completed_at") else None,
            success=data.get("success", True),
            error=data.get("error"),
            metadata=data.get("metadata", {}),
        )

    def get_patch_log(self) -> PatchLog:  # noqa: F821
        """Get patches as a PatchLog."""
        from cemaf.context.patch import PatchLog

        return PatchLog(patches=tuple(self.patches))


@runtime_checkable
class RunLogger(Protocol):
    """
    Protocol for recording agent runs.

    Implementations may:
    - Store in memory (for testing)
    - Persist to disk (for debugging)
    - Send to external service (for monitoring)
    """

    def start_run(
        self,
        run_id: str,
        dag_name: str = "",
        initial_context: Context | None = None,  # noqa: F821
    ) -> None:
        """Start recording a new run."""
        ...

    def record_tool_call(self, call: ToolCall) -> None:
        """Record a tool call."""
        ...

    def record_llm_call(self, call: LLMCall) -> None:
        """Record an LLM call."""
        ...

    def record_patch(self, patch: ContextPatch) -> None:  # noqa: F821
        """Record a context patch."""
        ...

    def end_run(
        self,
        final_context: Context | None = None,  # noqa: F821
        success: bool = True,
        error: str | None = None,
    ) -> RunRecord:
        """End the run and return the complete record."""
        ...

    def get_current_record(self) -> RunRecord | None:
        """Get the current run record (if any)."""
        ...


class InMemoryRunLogger:
    """
    In-memory run logger implementation.

    Useful for testing and debugging.
    """

    def __init__(self) -> None:
        self._current: RunRecord | None = None
        self._history: list[RunRecord] = []

    def start_run(
        self,
        run_id: str,
        dag_name: str = "",
        initial_context: Context | None = None,  # noqa: F821
    ) -> None:
        """Start recording a new run."""
        self._current = RunRecord(
            run_id=run_id,
            dag_name=dag_name,
            initial_context=initial_context,
        )

    def record_tool_call(self, call: ToolCall) -> None:
        """Record a tool call."""
        if self._current:
            self._current.tool_calls.append(call)

    def record_llm_call(self, call: LLMCall) -> None:
        """Record an LLM call."""
        if self._current:
            self._current.llm_calls.append(call)

    def record_patch(self, patch: ContextPatch) -> None:  # noqa: F821
        """Record a context patch."""
        if self._current:
            self._current.patches.append(patch)

    def end_run(
        self,
        final_context: Context | None = None,  # noqa: F821
        success: bool = True,
        error: str | None = None,
    ) -> RunRecord:
        """End the run and return the complete record."""
        if not self._current:
            raise RuntimeError("No run in progress")

        self._current.final_context = final_context
        self._current.completed_at = utc_now()
        self._current.success = success
        self._current.error = error

        record = self._current
        self._history.append(record)
        self._current = None
        return record

    def get_current_record(self) -> RunRecord | None:
        """Get the current run record (if any)."""
        return self._current

    def get_history(self) -> list[RunRecord]:
        """Get all completed run records."""
        return list(self._history)

    def get_record(self, run_id: str) -> RunRecord | None:
        """Get a specific run record by ID."""
        for record in self._history:
            if record.run_id == run_id:
                return record
        return None

    def clear_history(self) -> None:
        """Clear all recorded runs."""
        self._history.clear()


class NoOpRunLogger:
    """
    No-op run logger that discards all records.

    Useful as a default when recording is not needed.
    """

    def start_run(
        self,
        run_id: str,
        dag_name: str = "",
        initial_context: Context | None = None,  # noqa: F821
    ) -> None:
        """No-op."""
        pass

    def record_tool_call(self, call: ToolCall) -> None:
        """No-op."""
        pass

    def record_llm_call(self, call: LLMCall) -> None:
        """No-op."""
        pass

    def record_patch(self, patch: ContextPatch) -> None:  # noqa: F821
        """No-op."""
        pass

    def end_run(
        self,
        final_context: Context | None = None,  # noqa: F821
        success: bool = True,
        error: str | None = None,
    ) -> RunRecord:
        """Return empty record."""
        return RunRecord(run_id="noop")

    def get_current_record(self) -> RunRecord | None:
        """Always returns None."""
        return None

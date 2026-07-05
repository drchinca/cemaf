"""
Run logger for recording and replaying agent runs.

This module provides:
- ToolCall: Record of a single tool invocation
- RunRecord: Complete record of an agent run
- RunLogger: Protocol for recording runs
- InMemoryRunLogger: In-memory implementation
- FileRunLogger: file-backed implementation for durable local traces

Note: Uses PEP 563 () to defer annotation evaluation
and avoid circular imports with cemaf.context.
"""

import json
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from cemaf.core.types import JSON
from cemaf.core.utils import generate_id, safe_json, utc_now


@dataclass(frozen=True)
class ToolCall:
    """Record of a single tool invocation."""

    tool_id: str
    input: JSON
    output: JSON
    duration_ms: float = 0.0
    timestamp: datetime = field(default_factory=utc_now)
    correlation_id: str = ""
    success: bool = True
    error: str | None = None
    node_id: str | None = None
    agent_id: str | None = None

    # Auto-generated
    id: str = field(default_factory=lambda: generate_id("call"))

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        result = {
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
        if self.node_id is not None:
            result["node_id"] = self.node_id
        if self.agent_id is not None:
            result["agent_id"] = self.agent_id
        return result

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
            node_id=data.get("node_id"),
            agent_id=data.get("agent_id"),
        )


@dataclass(frozen=True)
class LLMCall:
    """Record of a single LLM invocation with provenance tracking."""

    model: str
    input_messages: list[dict[str, Any]]
    output: str
    input_tokens: int = 0
    output_tokens: int = 0
    duration_ms: float = 0.0
    timestamp: datetime = field(default_factory=utc_now)
    correlation_id: str = ""
    node_id: str | None = None
    agent_id: str | None = None
    context_sources_used: tuple[str, ...] = ()
    context_hash: str = ""
    budget_utilization: float = 0.0
    cost_usd: float = 0.0
    provenance_link_id: str | None = None
    error: str | None = None

    # Auto-generated
    id: str = field(default_factory=lambda: generate_id("llm"))

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        result = {
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
        if self.node_id is not None:
            result["node_id"] = self.node_id
        if self.agent_id is not None:
            result["agent_id"] = self.agent_id
        if self.context_sources_used:
            result["context_sources_used"] = list(self.context_sources_used)
        if self.context_hash:
            result["context_hash"] = self.context_hash
        if self.budget_utilization > 0:
            result["budget_utilization"] = self.budget_utilization
        if self.cost_usd > 0:
            result["cost_usd"] = self.cost_usd
        if self.provenance_link_id is not None:
            result["provenance_link_id"] = self.provenance_link_id
        return result

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
            node_id=data.get("node_id"),
            agent_id=data.get("agent_id"),
            context_sources_used=tuple(data.get("context_sources_used", [])),
            context_hash=data.get("context_hash", ""),
            budget_utilization=data.get("budget_utilization", 0.0),
            cost_usd=data.get("cost_usd", 0.0),
            provenance_link_id=data.get("provenance_link_id"),
        )


@dataclass
class RunRecord:
    """Complete record of an agent run with provenance tracking."""

    run_id: str
    dag_name: str = ""
    initial_context: Context | None = None  # type: ignore[name-defined]  # noqa: F821
    final_context: Context | None = None  # type: ignore[name-defined]  # noqa: F821
    patches: list[ContextPatch] = field(default_factory=list)  # type: ignore[name-defined]  # noqa: F821
    tool_calls: list[ToolCall] = field(default_factory=list)
    llm_calls: list[LLMCall] = field(default_factory=list)
    started_at: datetime = field(default_factory=utc_now)
    completed_at: datetime | None = None
    success: bool = True
    error: str | None = None
    metadata: JSON = field(default_factory=dict)
    total_cost_usd: float = 0.0
    provenance_chain: ProvenanceChain | None = None  # type: ignore[name-defined]  # noqa: F821
    selection_summaries: list[dict[str, Any]] = field(default_factory=list)

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
        result = {
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
            "total_cost_usd": self.total_cost_usd,
        }
        if self.provenance_chain is not None:
            result["provenance_chain"] = self.provenance_chain.to_dict()
        if self.selection_summaries:
            result["selection_summaries"] = self.selection_summaries
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RunRecord:
        """Create RunRecord from dictionary."""
        from cemaf.context.context import Context
        from cemaf.context.patch import ContextPatch
        from cemaf.core.provenance import ProvenanceChain

        initial_ctx = None
        if data.get("initial_context"):
            initial_ctx = Context.from_dict(data["initial_context"])

        final_ctx = None
        if data.get("final_context"):
            final_ctx = Context.from_dict(data["final_context"])

        prov_chain = None
        if data.get("provenance_chain"):
            prov_chain = ProvenanceChain.from_dict(data["provenance_chain"])

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
            total_cost_usd=data.get("total_cost_usd", 0.0),
            provenance_chain=prov_chain,
            selection_summaries=data.get("selection_summaries", []),
        )

    def get_patch_log(self) -> PatchLog:  # type: ignore[name-defined]  # noqa: F821
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
        initial_context: Context | None = None,  # type: ignore[name-defined]  # noqa: F821
    ) -> None:
        """Start recording a new run."""
        ...

    def record_tool_call(self, call: ToolCall) -> None:
        """Record a tool call."""
        ...

    def record_llm_call(self, call: LLMCall) -> None:
        """Record an LLM call."""
        ...

    def record_patch(self, patch: ContextPatch) -> None:  # type: ignore[name-defined]  # noqa: F821
        """Record a context patch."""
        ...

    def record_provenance_link(self, link: ProvenanceLink) -> None:  # type: ignore[name-defined]  # noqa: F821
        """Record a provenance link for the current run."""
        ...

    def end_run(
        self,
        final_context: Context | None = None,  # type: ignore[name-defined]  # noqa: F821
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
        initial_context: Context | None = None,  # type: ignore[name-defined]  # noqa: F821
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

    def record_patch(self, patch: ContextPatch) -> None:  # type: ignore[name-defined]  # noqa: F821
        """Record a context patch."""
        if self._current:
            self._current.patches.append(patch)

    def record_provenance_link(self, link: ProvenanceLink) -> None:  # type: ignore[name-defined]  # noqa: F821
        """Record a provenance link, appending to the chain."""
        if self._current:
            from cemaf.core.provenance import ProvenanceChain
            from cemaf.core.types import RunID

            if self._current.provenance_chain is None:
                self._current.provenance_chain = ProvenanceChain(
                    run_id=RunID(self._current.run_id),
                )
            self._current.provenance_chain = self._current.provenance_chain.append(link=link)
            self._current.total_cost_usd += link.cost_usd

    def end_run(
        self,
        final_context: Context | None = None,  # type: ignore[name-defined]  # noqa: F821
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
    No-op run logger that discards recorded events.

    Useful as a default when recording is not needed. The logger keeps only the
    active run envelope so `end_run()` can return a truthful lifecycle record.
    """

    def __init__(self) -> None:
        self._current: RunRecord | None = None

    def start_run(
        self,
        run_id: str,
        dag_name: str = "",
        initial_context: Context | None = None,  # type: ignore[name-defined]  # noqa: F821
    ) -> None:
        """Start a disposable run envelope."""
        self._current = RunRecord(run_id=run_id, dag_name=dag_name, initial_context=initial_context)

    def record_tool_call(self, call: ToolCall) -> None:
        """Discard tool call details."""
        return None

    def record_llm_call(self, call: LLMCall) -> None:
        """Discard LLM call details."""
        return None

    def record_patch(self, patch: ContextPatch) -> None:  # type: ignore[name-defined]  # noqa: F821
        """Discard context patch details."""
        return None

    def record_provenance_link(self, link: ProvenanceLink) -> None:  # type: ignore[name-defined]  # noqa: F821
        """Discard provenance details."""
        return None

    def end_run(
        self,
        final_context: Context | None = None,  # type: ignore[name-defined]  # noqa: F821
        success: bool = True,
        error: str | None = None,
    ) -> RunRecord:
        """Return a lifecycle record without retained events."""
        record = self._current or RunRecord(run_id="noop")
        record.final_context = final_context
        record.completed_at = utc_now()
        record.success = success
        record.error = error
        self._current = None
        return record

    def get_current_record(self) -> RunRecord | None:
        """Return the active disposable run envelope."""
        return self._current


class FileRunLogger(InMemoryRunLogger):
    """In-memory run logger that also writes live JSON snapshots to disk."""

    def __init__(
        self,
        *,
        root: str | Path,
        dir_namer: Callable[[str, str], str] | None = None,
    ) -> None:
        super().__init__()
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._dir_namer = dir_namer or self._default_dir_name
        self._run_dirs: dict[str, Path] = {}

    def _default_dir_name(self, run_id: str, dag_name: str) -> str:
        del dag_name
        safe = run_id.replace(":", "-").replace("/", "-").strip("-") or "run"
        return f"live__{safe}"

    def _write_json(self, path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(safe_json(payload), indent=2), encoding="utf-8")

    def get_run_dir(self, run_id: str) -> Path:
        return self._run_dirs.get(run_id, self._root / self._default_dir_name(run_id, ""))

    def relocate_run_dir(self, *, run_id: str, target: Path) -> Path:
        source = self.get_run_dir(run_id)
        target = target.resolve()
        if source.resolve() == target:
            self._run_dirs[run_id] = target
            return target
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
        if source.exists():
            shutil.move(str(source), str(target))
        else:
            target.mkdir(parents=True, exist_ok=True)
        self._run_dirs[run_id] = target
        return target

    def _persist_current(self) -> None:
        record = self.get_current_record()
        if record is None:
            return
        run_dir = self.get_run_dir(record.run_id)
        self._write_json(run_dir / "run_record.live.json", record.to_dict())

    def start_run(
        self,
        run_id: str,
        dag_name: str = "",
        initial_context: Context | None = None,  # type: ignore[name-defined]  # noqa: F821
    ) -> None:
        super().start_run(run_id=run_id, dag_name=dag_name, initial_context=initial_context)
        self._run_dirs[run_id] = self._root / self._dir_namer(run_id, dag_name)
        self._persist_current()

    def record_tool_call(self, call: ToolCall) -> None:
        super().record_tool_call(call)
        self._persist_current()

    def record_llm_call(self, call: LLMCall) -> None:
        super().record_llm_call(call)
        self._persist_current()

    def record_patch(self, patch: ContextPatch) -> None:  # type: ignore[name-defined]  # noqa: F821
        super().record_patch(patch)
        self._persist_current()

    def record_provenance_link(self, link: ProvenanceLink) -> None:  # type: ignore[name-defined]  # noqa: F821
        super().record_provenance_link(link)
        self._persist_current()

    def end_run(
        self,
        final_context: Context | None = None,  # type: ignore[name-defined]  # noqa: F821
        success: bool = True,
        error: str | None = None,
    ) -> RunRecord:
        record = super().end_run(final_context=final_context, success=success, error=error)
        run_dir = self.get_run_dir(record.run_id)
        self._write_json(run_dir / "run_record.json", record.to_dict())
        self._write_json(
            run_dir / "run_summary.json",
            {
                "run_id": record.run_id,
                "dag_name": record.dag_name,
                "success": record.success,
                "error": record.error,
                "started_at": record.started_at.isoformat(),
                "completed_at": record.completed_at.isoformat() if record.completed_at else None,
                "duration_ms": record.duration_ms,
                "total_tokens": record.total_tokens,
                "total_cost_usd": record.total_cost_usd,
                "total_llm_calls": record.total_llm_calls,
                "total_tool_calls": record.total_tool_calls,
                "total_patches": record.total_patches,
            },
        )
        return record

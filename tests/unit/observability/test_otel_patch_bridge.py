"""Tests for OTelPatchBridge — patches → OTel span events.

Proves that wrapping any RunLogger in OTelPatchBridge causes every
record_patch() call to fire as a "cemaf.context.patch" event on the
caller-supplied span, while preserving the wrapped logger's durable
record. Failures in the OTel side-effect must never block delegation.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from cemaf.context.patch import (
    ContextPatch,
    PatchOperation,
    PatchSource,
    SecurityLevel,
)
from cemaf.observability.otel_patch_bridge import OTelPatchBridge
from cemaf.observability.run_logger import InMemoryRunLogger


class _FakeSpan:
    """Minimal stand-in for an OTel span; records add_event calls."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def add_event(
        self,
        name: str,
        attributes: dict[str, Any] | None = None,
    ) -> None:
        self.events.append((name, dict(attributes or {})))


def _patch(
    *,
    path: str = "ingest.book.bm25_indexed_at",
    operation: PatchOperation = PatchOperation.SET,
    value: Any = "2026-06-29T12:00:00Z",
    source: PatchSource = PatchSource.SYSTEM,
    source_id: str = "bm25_store",
    reason: str = "bm25 commit succeeded",
    correlation_id: str | None = "ingest-abc",
    security_level: SecurityLevel = SecurityLevel.INTERNAL,
) -> ContextPatch:
    return ContextPatch(
        path=path,
        operation=operation,
        value=value,
        source=source,
        source_id=source_id,
        reason=reason,
        correlation_id=correlation_id,
        security_level=security_level,
    )


def test_record_patch_emits_otel_event_with_provenance_attrs() -> None:
    span = _FakeSpan()
    inner = InMemoryRunLogger()
    bridge = OTelPatchBridge(wrapped=inner, span_provider=lambda: span)
    bridge.start_run(run_id="run-1", dag_name="ingest")
    patch = _patch()

    bridge.record_patch(patch=patch)

    assert len(span.events) == 1
    name, attrs = span.events[0]
    assert name == "cemaf.context.patch"
    assert attrs["patch.path"] == "ingest.book.bm25_indexed_at"
    assert attrs["patch.operation"] == "set"
    assert attrs["patch.source"] == "system"
    assert attrs["patch.source_id"] == "bm25_store"
    assert attrs["patch.reason"] == "bm25 commit succeeded"
    assert attrs["patch.correlation_id"] == "ingest-abc"
    assert attrs["patch.security_level"] == "internal"
    # ID is auto-generated; just assert it's a string.
    assert isinstance(attrs["patch.id"], str) and attrs["patch.id"]


def test_record_patch_delegates_to_wrapped_logger() -> None:
    span = _FakeSpan()
    inner = InMemoryRunLogger()
    bridge = OTelPatchBridge(wrapped=inner, span_provider=lambda: span)
    bridge.start_run(run_id="run-2", dag_name="ingest")
    patch = _patch()

    bridge.record_patch(patch=patch)
    record = bridge.end_run()

    assert len(record.patches) == 1
    assert record.patches[0].path == patch.path
    assert record.patches[0].id == patch.id


def test_span_provider_returning_none_skips_otel_but_still_records() -> None:
    inner = InMemoryRunLogger()
    bridge = OTelPatchBridge(wrapped=inner, span_provider=lambda: None)
    bridge.start_run(run_id="run-3", dag_name="ingest")

    bridge.record_patch(patch=_patch())
    record = bridge.end_run()

    assert len(record.patches) == 1  # still recorded
    # No span side-effect to assert; just confirm no exception raised.


def test_otel_side_effect_failure_does_not_block_recording() -> None:
    inner = InMemoryRunLogger()

    broken_span = MagicMock()
    broken_span.add_event.side_effect = RuntimeError("OTel exporter down")

    bridge = OTelPatchBridge(wrapped=inner, span_provider=lambda: broken_span)
    bridge.start_run(run_id="run-4", dag_name="ingest")

    bridge.record_patch(patch=_patch())
    record = bridge.end_run()

    assert len(record.patches) == 1
    broken_span.add_event.assert_called_once()


def test_other_runlogger_methods_pass_through() -> None:
    inner = MagicMock()
    bridge = OTelPatchBridge(wrapped=inner, span_provider=lambda: None)

    bridge.start_run(run_id="run-5", dag_name="ingest")
    inner.start_run.assert_called_once_with(
        run_id="run-5",
        dag_name="ingest",
        initial_context=None,
    )

    tool_call = MagicMock(name="ToolCall")
    bridge.record_tool_call(call=tool_call)
    inner.record_tool_call.assert_called_once_with(call=tool_call)

    llm_call = MagicMock(name="LLMCall")
    bridge.record_llm_call(call=llm_call)
    inner.record_llm_call.assert_called_once_with(call=llm_call)

    link = MagicMock(name="ProvenanceLink")
    bridge.record_provenance_link(link=link)
    inner.record_provenance_link.assert_called_once_with(link=link)

    bridge.end_run(success=True)
    inner.end_run.assert_called_once_with(
        final_context=None,
        success=True,
        error=None,
    )

    bridge.get_current_record()
    inner.get_current_record.assert_called_once()


def test_patch_value_stringified_safely() -> None:
    """OTel attribute values must be scalars; complex values stringified."""
    span = _FakeSpan()
    inner = InMemoryRunLogger()
    bridge = OTelPatchBridge(wrapped=inner, span_provider=lambda: span)
    bridge.start_run(run_id="run-6", dag_name="ingest")

    complex_value = {"chunks_added": 50, "duration_ms": 2700}
    patch = _patch(operation=PatchOperation.MERGE, value=complex_value)
    bridge.record_patch(patch=patch)

    _, attrs = span.events[0]
    assert "chunks_added" in attrs["patch.value_repr"]
    assert isinstance(attrs["patch.value_repr"], str)


@pytest.mark.parametrize(
    "operation,expected",
    [
        (PatchOperation.SET, "set"),
        (PatchOperation.DELETE, "delete"),
        (PatchOperation.MERGE, "merge"),
        (PatchOperation.APPEND, "append"),
    ],
)
def test_all_patch_operations_serialize(operation: PatchOperation, expected: str) -> None:
    span = _FakeSpan()
    inner = InMemoryRunLogger()
    bridge = OTelPatchBridge(wrapped=inner, span_provider=lambda: span)
    bridge.start_run(run_id="run-op", dag_name="ingest")

    bridge.record_patch(patch=_patch(operation=operation, value="x"))

    _, attrs = span.events[0]
    assert attrs["patch.operation"] == expected

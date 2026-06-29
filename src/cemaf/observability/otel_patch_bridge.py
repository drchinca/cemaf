"""OTel bridge for ``cemaf.context.patch.ContextPatch`` events.

``ContextPatch`` is CEMAF's canonical record of a context mutation —
append-only, fully provenanced (``source``, ``source_id``, ``reason``,
``correlation_id``, ``security_level``). ``RunLogger.record_patch()``
persists patches into ``RunRecord.patches`` but emits no OpenTelemetry
telemetry. Users who want patches to appear in their trace viewer
(Jaeger, Tempo, Honeycomb, console) need a bridge.

``OTelPatchBridge`` is a transparent decorator over any ``RunLogger``.
Every ``record_patch()`` call is mirrored as a ``span.add_event(
"cemaf.context.patch", attributes=...)`` on the caller-provided span
before being delegated to the wrapped logger. Other ``RunLogger``
methods pass through untouched.

Typical wiring::

    from cemaf.observability import (
        FileRunLogger,
        OTelPatchBridge,
        configure_otel_to_file,
    )
    from opentelemetry import trace

    configure_otel_to_file(
        service_name="meridian-library",
        output_path=runs_dir / "trace.otlp.jsonl",
    )
    tracer = trace.get_tracer("cemaf.observability")
    root_span = tracer.start_span("cemaf.ingest.run")

    logger = OTelPatchBridge(
        wrapped=FileRunLogger(directory=runs_dir),
        span_provider=lambda: root_span,
    )
    logger.start_run(run_id="...", dag_name="ingest")
    logger.record_patch(ContextPatch.set(
        path="ingest.book.bm25_indexed_at",
        value=now,
        source=PatchSource.SYSTEM,
        source_id="bm25_store",
        reason="bm25 commit succeeded",
    ))
    # → span event "cemaf.context.patch" lands in the OTLP trace.

Attribute naming follows the conventions established for CEMAF
telemetry (``cemaf.<subsystem>.<field>``).
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

    from cemaf.context.context import Context
    from cemaf.context.patch import ContextPatch
    from cemaf.core.provenance import ProvenanceLink
    from cemaf.observability.run_logger import (
        LLMCall,
        RunLogger,
        RunRecord,
        ToolCall,
    )


_EVENT_NAME = "cemaf.context.patch"


def _patch_attrs(*, patch: ContextPatch) -> dict[str, Any]:
    """Flatten a ``ContextPatch`` into OTel-legal scalar attributes.

    OTel rejects dict/list attribute values; only str / int / float / bool and
    sequences of those are valid. ``value`` is therefore stringified, and any
    nullable provenance fields default to empty strings instead of None.
    """
    return {
        "patch.id": patch.id,
        "patch.path": patch.path,
        "patch.operation": str(patch.operation.value),
        "patch.source": str(patch.source.value),
        "patch.source_id": patch.source_id or "",
        "patch.reason": patch.reason or "",
        "patch.correlation_id": patch.correlation_id or "",
        "patch.security_level": str(patch.security_level.value),
        "patch.value_repr": repr(patch.value)[:200] if patch.value is not None else "",
    }


class OTelPatchBridge:
    """Decorate a ``RunLogger`` so every patch also lands as an OTel event.

    The bridge is transparent: it implements the full ``RunLogger`` protocol
    by delegating every method to ``wrapped`` and only adds an OTel
    side-effect inside ``record_patch()``. If ``span_provider`` returns
    ``None`` (no current span) or the span's ``add_event`` raises, the
    delegation still succeeds — observability never blocks the audit trail.

    Args:
        wrapped: Any ``RunLogger`` implementation (in-memory, file, no-op).
        span_provider: Callable returning the OTel span that should host the
            patch event. Typically ``lambda: trace.get_current_span()`` or
            a closure over the run's root span. Returning ``None`` skips
            the OTel side-effect for that patch.
    """

    def __init__(
        self,
        *,
        wrapped: RunLogger,
        span_provider: Callable[[], Any | None],
    ) -> None:
        self._wrapped = wrapped
        self._span_provider = span_provider

    # ---- RunLogger protocol — delegate everything but record_patch() ----

    def start_run(
        self,
        run_id: str,
        dag_name: str = "",
        initial_context: Context | None = None,
    ) -> None:
        self._wrapped.start_run(
            run_id=run_id,
            dag_name=dag_name,
            initial_context=initial_context,
        )

    def record_tool_call(self, call: ToolCall) -> None:
        self._wrapped.record_tool_call(call=call)

    def record_llm_call(self, call: LLMCall) -> None:
        self._wrapped.record_llm_call(call=call)

    def record_patch(self, patch: ContextPatch) -> None:
        # OTel side-effect first, then durable record. The suppress() keeps
        # any OTel SDK failure (provider not configured, batcher down,
        # serialization error) from blocking the audit trail.
        with contextlib.suppress(Exception):
            span = self._span_provider()
            if span is not None:
                span.add_event(
                    name=_EVENT_NAME,
                    attributes=_patch_attrs(patch=patch),
                )
        self._wrapped.record_patch(patch=patch)

    def record_provenance_link(self, link: ProvenanceLink) -> None:
        self._wrapped.record_provenance_link(link=link)

    def end_run(
        self,
        final_context: Context | None = None,
        success: bool = True,
        error: str | None = None,
    ) -> RunRecord:
        return self._wrapped.end_run(
            final_context=final_context,
            success=success,
            error=error,
        )

    def get_current_record(self) -> RunRecord | None:
        return self._wrapped.get_current_record()


__all__ = ["OTelPatchBridge"]

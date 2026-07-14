"""Helpers for analyzing run-level audit summaries."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine, Mapping, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

from cemaf.audit.models import AuditEntry, AuditEntryType
from cemaf.audit.subscriber import EventBusAuditLog
from cemaf.audit.trail import InMemoryAuditTrail


def _run_async_sync[T](factory: Callable[[], Coroutine[Any, Any, T]]) -> T:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(factory())

    with ThreadPoolExecutor(max_workers=1) as executor:
        future: Future[T] = executor.submit(lambda: asyncio.run(factory()))
        return future.result()


async def build_trace_analysis(
    *,
    run_summaries: Sequence[Mapping[str, Any]],
    quality_window: int = 20,
    anomaly_threshold: float = 2.0,
) -> dict[str, Any]:
    """Build trace-analysis aggregates from run-level summary records."""

    audit_log = EventBusAuditLog()

    for item in run_summaries:
        run_id = str(item.get("run_id") or "unknown")
        source = "cemaf.audit.analysis"
        payload = {
            "success": bool(item.get("success", False)),
            "duration_ms": float(item.get("duration_ms") or 0.0),
        }
        await audit_log.append(
            AuditEntry.create(
                type=AuditEntryType.DAG_COMPLETED,
                run_id=run_id,
                source=source,
                payload=payload,
            )
        )

        quality_score = item.get("quality_score")
        if quality_score is not None:
            await audit_log.append(
                AuditEntry.create(
                    type=AuditEntryType.EVAL_RESULT,
                    run_id=run_id,
                    source="quality",
                    payload={
                        "score": float(quality_score),
                        "approved": bool(item.get("approved", False)),
                    },
                )
            )

        if not bool(item.get("approved", False)):
            alert_reason = str(item.get("quality_reason") or "quality rejected").strip()
            await audit_log.append(
                AuditEntry.create(
                    type=AuditEntryType.QUALITY_ALERT,
                    run_id=run_id,
                    source="quality",
                    payload={"reason": alert_reason},
                )
            )

        node_results = item.get("node_results", [])
        if not isinstance(node_results, Sequence):
            continue
        for node in node_results:
            if not isinstance(node, Mapping):
                continue
            await audit_log.append(
                AuditEntry.create(
                    type=AuditEntryType.NODE_EXECUTED,
                    run_id=run_id,
                    source=str(node.get("node_id") or "unknown"),
                    payload={
                        "node_id": str(node.get("node_id") or "unknown"),
                        "success": bool(node.get("success", False)),
                        "error": node.get("error"),
                    },
                )
            )

    # Deferred import: TraceAnalyzerTool lives in the self-hosting `meta` layer,
    # which depends on `audit`. Importing it at module scope creates a cycle
    # (audit -> meta -> audit). Import lazily so the base-layer graph stays acyclic.
    from cemaf.meta.tools import TraceAnalyzerTool

    trail = InMemoryAuditTrail(audit_log=audit_log)
    analyzer = TraceAnalyzerTool(audit_trail=trail)

    quality_result = await analyzer.execute(analysis_type="quality_trend", window=quality_window)
    anomaly_result = await analyzer.execute(
        analysis_type="anomalies",
        threshold=anomaly_threshold,
    )

    latest_run_timeline: list[dict[str, Any]] = []
    if run_summaries:
        latest = max(
            run_summaries,
            key=lambda item: str(item.get("completed_at") or item.get("run_id") or ""),
        )
        timeline_result = await analyzer.execute(
            analysis_type="timeline",
            run_id=str(latest.get("run_id") or "unknown"),
        )
        if timeline_result.success and isinstance(timeline_result.data, list):
            latest_run_timeline = timeline_result.data

    return {
        "quality_trend": quality_result.data if quality_result.success else {},
        "anomalies": anomaly_result.data if anomaly_result.success else {},
        "latest_run_timeline": latest_run_timeline,
    }


def build_trace_analysis_sync(
    *,
    run_summaries: Sequence[Mapping[str, Any]],
    quality_window: int = 20,
    anomaly_threshold: float = 2.0,
) -> dict[str, Any]:
    """Synchronous wrapper for :func:`build_trace_analysis`."""

    return _run_async_sync(
        lambda: build_trace_analysis(
            run_summaries=run_summaries,
            quality_window=quality_window,
            anomaly_threshold=anomaly_threshold,
        )
    )

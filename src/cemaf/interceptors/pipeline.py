"""InterceptorPipeline — the ordered PRE→execute→POST spine (SPEC-01a §2).

Empty pipeline is a no-op (additive guarantee). Holds NO per-run mutable state,
so one instance is safe across the executor's concurrent DAG runs. Interceptor
ids are unique within a pipeline (validated at construction); registration order
is run order.
"""

from __future__ import annotations

import logging

from cemaf.agents.base import AgentContext
from cemaf.interceptors.protocols import Interceptor, PostInterceptor, PreInterceptor
from cemaf.interceptors.types import DecisionKind, PostflightDecision, PreflightDecision
from cemaf.orchestration.dag import Node
from cemaf.orchestration.results import NodeResult

logger = logging.getLogger(__name__)


class InterceptorPipeline:
    """Ordered PRE/POST chain over interceptors. See module docstring."""

    def __init__(self, *, interceptors: tuple[Interceptor, ...] = ()) -> None:
        ids = [i.interceptor_id for i in interceptors]
        dupes = {i for i in ids if ids.count(i) > 1}
        if dupes:
            raise ValueError(f"duplicate interceptor_id(s) in pipeline: {sorted(dupes)}")
        self._interceptors = interceptors

    @property
    def is_empty(self) -> bool:
        return not self._interceptors

    async def run_pre(
        self, *, node: Node, context: AgentContext
    ) -> tuple[AgentContext, PreflightDecision | None]:
        """Run PreInterceptors in order. Returns (enriched context, first REJECT or None).

        A raising interceptor is contained → treated as REJECT (reason = exc repr).
        """
        current = context
        for interceptor in self._interceptors:
            if not isinstance(interceptor, PreInterceptor):
                continue
            try:
                decision = await interceptor.pre(node=node, context=current)
            except Exception as exc:  # noqa: BLE001 — contain, don't crash the run
                logger.warning(
                    "PRE interceptor %s raised %s; treating as REJECT",
                    interceptor.interceptor_id,
                    type(exc).__name__,
                )
                return current, PreflightDecision(
                    kind=DecisionKind.REJECT,
                    interceptor_id=interceptor.interceptor_id,
                    reason=f"{interceptor.interceptor_id} raised {type(exc).__name__}: {exc!r}",
                )
            if decision.kind is DecisionKind.REJECT:
                return current, decision
            if decision.enriched_context is not None:
                current = decision.enriched_context
        return current, None

    async def run_post(
        self, *, node: Node, context: AgentContext, result: NodeResult
    ) -> tuple[NodeResult, PostflightDecision | None]:
        """Run PostInterceptors in order. Returns (result, first non-ACCEPT decision or None).

        Outcomes:
        - ACCEPT — chain continues; metadata (if set) merges under metadata["interceptors"][id].
        - REJECT — chain stops; result flipped to failure, gate_rejected stamped, original
          output preserved for provenance. Returns (failed_result, REJECT decision).
        - RECOVER — chain stops; original ``result`` returned UNCHANGED so the executor
          can re-run the node with the hint. The decision carries the RecoveryHint.
        - A raising interceptor is contained → treated as REJECT.
        """
        current = result
        for interceptor in self._interceptors:
            if not isinstance(interceptor, PostInterceptor):
                continue
            try:
                decision = await interceptor.post(node=node, context=context, result=current)
            except Exception as exc:  # noqa: BLE001 — contain, don't crash the run
                logger.warning(
                    "POST interceptor %s raised %s; treating as REJECT",
                    interceptor.interceptor_id,
                    type(exc).__name__,
                )
                rejected = _apply_reject(
                    result=current,
                    interceptor_id=interceptor.interceptor_id,
                    reason=f"{interceptor.interceptor_id} raised {type(exc).__name__}: {exc!r}",
                )
                return rejected, PostflightDecision(
                    kind=DecisionKind.REJECT,
                    interceptor_id=interceptor.interceptor_id,
                    reason="contained exception",
                )
            if decision.kind is DecisionKind.RECOVER:
                # Hand back to the executor; the result is unchanged. The executor's
                # bounded recovery loop owns the re-run with the hint.
                return current, decision
            if decision.kind is DecisionKind.REJECT:
                rejected = _apply_reject(
                    result=current,
                    interceptor_id=interceptor.interceptor_id,
                    reason=decision.reason or "rejected",
                )
                return rejected, decision
            if decision.metadata is not None:
                current = _merge_accept_metadata(
                    result=current,
                    interceptor_id=interceptor.interceptor_id,
                    metadata=decision.metadata,
                )
        return current, None


def _interceptors_block(metadata: dict[str, object]) -> dict[str, object]:
    existing = metadata.get("interceptors")
    return dict(existing) if isinstance(existing, dict) else {}


def _apply_reject(*, result: NodeResult, interceptor_id: str, reason: str) -> NodeResult:
    """Flip a NodeResult to failure with provenance — preserves original output."""
    import dataclasses

    block = _interceptors_block(dict(result.metadata or {}))
    block["rejected_by"] = interceptor_id
    block["reason"] = reason
    block["rejected_output"] = result.output
    block["gate_rejected"] = True  # signals _execute_with_retry NOT to retry
    new_metadata = {**(result.metadata or {}), "interceptors": block}
    return dataclasses.replace(
        result,
        success=False,
        output=None,
        error=f"interceptor {interceptor_id} rejected node: {reason}",
        metadata=new_metadata,
    )


def _merge_accept_metadata(*, result: NodeResult, interceptor_id: str, metadata: object) -> NodeResult:
    import dataclasses

    block = _interceptors_block(dict(result.metadata or {}))
    block[interceptor_id] = metadata
    new_metadata = {**(result.metadata or {}), "interceptors": block}
    return dataclasses.replace(result, metadata=new_metadata)


def create_interceptor_pipeline(*, interceptors: tuple[Interceptor, ...] = ()) -> InterceptorPipeline:
    """Factory (BYO-X) — wired into RuntimeServices.interceptor_pipeline at bootstrap."""
    return InterceptorPipeline(interceptors=interceptors)

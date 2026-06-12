"""RECOVER decision: retry-with-feedback for POST interceptors.

Tests the type-level contract (PreflightDecision rejects RECOVER, RecoveryHint
validates) and the pipeline-level surfacing (run_post returns the decision
unchanged so the executor can act on it).
"""

from __future__ import annotations

import pytest

from cemaf.agents.base import AgentContext
from cemaf.core.types import NodeID
from cemaf.interceptors.pipeline import InterceptorPipeline
from cemaf.interceptors.types import (
    DecisionKind,
    PostflightDecision,
    PreflightDecision,
    RecoveryHint,
)
from cemaf.orchestration.dag import Node
from cemaf.orchestration.results import NodeResult

CTX = AgentContext(run_id="r", agent_id="a")


def _node() -> Node:
    return Node.agent(id="n", name="n", agent_id="a")


def _ok_result() -> NodeResult:
    return NodeResult(node_id=NodeID("n"), success=True, output="x", metadata={})


# --- RecoveryHint validation -----------------------------------------------


class TestRecoveryHint:
    def test_valid(self) -> None:
        h = RecoveryHint(interceptor_id="g", code="length", detail="too short")
        assert h.suggested_action == ""
        d = h.to_dict()
        assert d == {
            "interceptor_id": "g",
            "code": "length",
            "detail": "too short",
            "suggested_action": "",
        }

    def test_empty_code_rejected(self) -> None:
        with pytest.raises(ValueError, match="code must be non-empty"):
            RecoveryHint(interceptor_id="g", code="  ", detail="x")

    def test_empty_detail_rejected(self) -> None:
        with pytest.raises(ValueError, match="detail must be non-empty"):
            RecoveryHint(interceptor_id="g", code="x", detail="")

    def test_overlong_detail_rejected(self) -> None:
        with pytest.raises(ValueError, match="detail exceeds"):
            RecoveryHint(interceptor_id="g", code="x", detail="a" * 1025)

    def test_overlong_action_rejected(self) -> None:
        with pytest.raises(ValueError, match="suggested_action exceeds"):
            RecoveryHint(interceptor_id="g", code="x", detail="d", suggested_action="a" * 513)


# --- Decision validation ----------------------------------------------------


class TestDecisionValidation:
    def test_pre_cannot_recover(self) -> None:
        with pytest.raises(ValueError, match="PRE interceptors cannot RECOVER"):
            PreflightDecision(kind=DecisionKind.RECOVER, interceptor_id="x")

    def test_post_recover_requires_reason(self) -> None:
        hint = RecoveryHint(interceptor_id="g", code="x", detail="d")
        with pytest.raises(ValueError, match="RECOVER requires a non-empty reason"):
            PostflightDecision(kind=DecisionKind.RECOVER, interceptor_id="g", recovery_hint=hint)

    def test_post_recover_requires_hint(self) -> None:
        with pytest.raises(ValueError, match="RECOVER requires a recovery_hint"):
            PostflightDecision(kind=DecisionKind.RECOVER, interceptor_id="g", reason="bad")

    def test_post_recover_valid(self) -> None:
        hint = RecoveryHint(interceptor_id="g", code="x", detail="d")
        d = PostflightDecision(
            kind=DecisionKind.RECOVER,
            interceptor_id="g",
            reason="quality below threshold",
            recovery_hint=hint,
        )
        assert d.recovery_hint is hint


# --- Pipeline surfacing ----------------------------------------------------


class _PostRecover:
    interceptor_id = "post_rec"

    async def post(self, *, node, context, result):
        return PostflightDecision(
            kind=DecisionKind.RECOVER,
            interceptor_id=self.interceptor_id,
            reason="needs longer output",
            recovery_hint=RecoveryHint(
                interceptor_id=self.interceptor_id,
                code="length",
                detail="output too short",
                suggested_action="add more detail",
            ),
        )


class _PostAccept:
    interceptor_id = "post_ok"

    async def post(self, *, node, context, result):
        return PostflightDecision(kind=DecisionKind.ACCEPT, interceptor_id=self.interceptor_id, metadata={})


@pytest.mark.asyncio
async def test_run_post_surfaces_recover_unchanged() -> None:
    """A RECOVER decision returns (original_result, decision) — result NOT failed."""
    pipe = InterceptorPipeline(interceptors=(_PostRecover(),))
    original = _ok_result()
    result, decision = await pipe.run_post(node=_node(), context=CTX, result=original)

    assert decision is not None
    assert decision.kind is DecisionKind.RECOVER
    assert decision.recovery_hint is not None
    assert decision.recovery_hint.code == "length"
    # The result is the SAME successful result — recovery is the executor's job.
    assert result.success is True
    assert result.output == "x"
    assert "interceptors" not in result.metadata


@pytest.mark.asyncio
async def test_recover_short_circuits_subsequent_interceptors() -> None:
    """Like REJECT, a RECOVER stops the chain — later interceptors do not run."""
    later = _PostAccept()
    pipe = InterceptorPipeline(interceptors=(_PostRecover(), later))
    result, decision = await pipe.run_post(node=_node(), context=CTX, result=_ok_result())

    assert decision is not None and decision.interceptor_id == "post_rec"
    # No metadata block from post_ok — chain short-circuited.
    assert "interceptors" not in result.metadata

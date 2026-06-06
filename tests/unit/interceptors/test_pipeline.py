"""Unit tests for the interceptor spine (SPEC-01a §3 invariants)."""

from __future__ import annotations

import pytest

from cemaf.agents.base import AgentContext
from cemaf.core.types import NodeID
from cemaf.interceptors.pipeline import InterceptorPipeline, create_interceptor_pipeline
from cemaf.interceptors.types import DecisionKind, PostflightDecision, PreflightDecision
from cemaf.orchestration.dag import Node
from cemaf.orchestration.results import NodeResult

CTX = AgentContext(run_id="r", agent_id="a")


def _node() -> Node:
    return Node.agent(id="n", name="n", agent_id="a")


def _ok_result() -> NodeResult:
    return NodeResult(node_id=NodeID("n"), success=True, output="hello world", metadata={})


# --- Test interceptors -----------------------------------------------------


class _PreEnrich:
    interceptor_id = "pre_enrich"

    async def pre(self, *, node, context):
        enriched = context.model_copy(update={"global_memory": {**context.global_memory, "hint": "x"}})
        return PreflightDecision(
            kind=DecisionKind.ACCEPT, interceptor_id=self.interceptor_id, enriched_context=enriched
        )


class _PreReject:
    interceptor_id = "pre_reject"

    async def pre(self, *, node, context):
        return PreflightDecision(
            kind=DecisionKind.REJECT, interceptor_id=self.interceptor_id, reason="blocked"
        )


class _PreRaise:
    interceptor_id = "pre_raise"

    async def pre(self, *, node, context):
        raise RuntimeError("boom")


class _PostAccept:
    interceptor_id = "post_accept"

    async def post(self, *, node, context, result):
        return PostflightDecision(
            kind=DecisionKind.ACCEPT, interceptor_id=self.interceptor_id, metadata={"ran": True}
        )


class _PostReject:
    interceptor_id = "post_reject"

    async def post(self, *, node, context, result):
        return PostflightDecision(
            kind=DecisionKind.REJECT, interceptor_id=self.interceptor_id, reason="bad output"
        )


class _PostRaise:
    interceptor_id = "post_raise"

    async def post(self, *, node, context, result):
        raise RuntimeError("post boom")


# --- Construction / decision validation ------------------------------------


def test_reject_without_reason_is_construction_error() -> None:
    with pytest.raises(ValueError, match="REJECT requires"):
        PreflightDecision(kind=DecisionKind.REJECT, interceptor_id="x")
    with pytest.raises(ValueError, match="REJECT requires"):
        PostflightDecision(kind=DecisionKind.REJECT, interceptor_id="x", reason="  ")


def test_duplicate_interceptor_ids_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate interceptor_id"):
        InterceptorPipeline(interceptors=(_PreEnrich(), _PreEnrich()))


def test_empty_pipeline_is_empty() -> None:
    assert create_interceptor_pipeline().is_empty


# --- PRE chain --------------------------------------------------------------


class TestPre:
    @pytest.mark.asyncio
    async def test_enrichment_is_cumulative(self) -> None:
        pipe = InterceptorPipeline(interceptors=(_PreEnrich(),))
        ctx, reject = await pipe.run_pre(node=_node(), context=CTX)
        assert reject is None
        assert ctx.global_memory["hint"] == "x"
        # original context unmutated (no in-place mutation)
        assert "hint" not in CTX.global_memory

    @pytest.mark.asyncio
    async def test_reject_short_circuits(self) -> None:
        # reject is first; enrich after must NOT run
        pipe = InterceptorPipeline(interceptors=(_PreReject(), _PreEnrich()))
        ctx, reject = await pipe.run_pre(node=_node(), context=CTX)
        assert reject is not None
        assert reject.interceptor_id == "pre_reject"
        assert ctx.global_memory == CTX.global_memory  # enrich never ran

    @pytest.mark.asyncio
    async def test_raise_contained_as_reject(self) -> None:
        pipe = InterceptorPipeline(interceptors=(_PreRaise(),))
        _ctx, reject = await pipe.run_pre(node=_node(), context=CTX)
        assert reject is not None
        assert "pre_raise" in reject.reason and "RuntimeError" in reject.reason


# --- POST chain -------------------------------------------------------------


class TestPost:
    @pytest.mark.asyncio
    async def test_accept_merges_metadata(self) -> None:
        pipe = InterceptorPipeline(interceptors=(_PostAccept(),))
        result, reject = await pipe.run_post(node=_node(), context=CTX, result=_ok_result())
        assert reject is None
        assert result.success is True
        assert result.metadata["interceptors"]["post_accept"] == {"ran": True}

    @pytest.mark.asyncio
    async def test_reject_fails_node_and_preserves_output(self) -> None:
        pipe = InterceptorPipeline(interceptors=(_PostReject(),))
        result, reject = await pipe.run_post(node=_node(), context=CTX, result=_ok_result())
        assert reject is not None
        assert result.success is False
        assert "bad output" in result.error
        block = result.metadata["interceptors"]
        assert block["rejected_by"] == "post_reject"
        assert block["rejected_output"] == "hello world"
        assert block["gate_rejected"] is True

    @pytest.mark.asyncio
    async def test_first_reject_wins(self) -> None:
        pipe = InterceptorPipeline(interceptors=(_PostAccept(), _PostReject()))
        result, reject = await pipe.run_post(node=_node(), context=CTX, result=_ok_result())
        assert reject.interceptor_id == "post_reject"
        assert result.success is False

    @pytest.mark.asyncio
    async def test_raise_contained_as_reject(self) -> None:
        pipe = InterceptorPipeline(interceptors=(_PostRaise(),))
        result, reject = await pipe.run_post(node=_node(), context=CTX, result=_ok_result())
        assert reject is not None
        assert result.success is False
        assert result.metadata["interceptors"]["gate_rejected"] is True

    @pytest.mark.asyncio
    async def test_no_mutation_of_input_result(self) -> None:
        original = _ok_result()
        pipe = InterceptorPipeline(interceptors=(_PostReject(),))
        result, _ = await pipe.run_post(node=_node(), context=CTX, result=original)
        assert original.success is True  # input untouched
        assert result is not original


# --- Phase detection (the crux) --------------------------------------------


class TestPhaseDetection:
    @pytest.mark.asyncio
    async def test_post_only_interceptor_not_called_in_pre(self) -> None:
        # _PostAccept has no `pre` method — must be skipped by run_pre, used by run_post
        pipe = InterceptorPipeline(interceptors=(_PostAccept(),))
        ctx, reject = await pipe.run_pre(node=_node(), context=CTX)
        assert reject is None and ctx is CTX  # pre chain saw nothing to run

        result, _ = await pipe.run_post(node=_node(), context=CTX, result=_ok_result())
        assert result.metadata["interceptors"]["post_accept"] == {"ran": True}

    @pytest.mark.asyncio
    async def test_pre_only_interceptor_not_called_in_post(self) -> None:
        pipe = InterceptorPipeline(interceptors=(_PreEnrich(),))
        result, reject = await pipe.run_post(node=_node(), context=CTX, result=_ok_result())
        assert reject is None
        assert "interceptors" not in result.metadata  # post chain saw nothing to run

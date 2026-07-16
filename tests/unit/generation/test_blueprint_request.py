"""Unit tests for the SPEC-03 blueprint request/result shapes."""

from pydantic import BaseModel

from cemaf.citation.models import Citation
from cemaf.generation.blueprint_request import (
    BlueprintRequest,
    DeliverableType,
    GoalSpec,
    OutputFormat,
    PolicyExhaustedError,
    PolicyKind,
    PolicySpec,
    StreamingIncompleteError,
    StructuredResult,
    StyleSpec,
    ToolLoopExhaustedError,
    ToolLoopFabricationError,
)


class _OrderSummary(BaseModel):
    total: float
    item_count: int


def _citation(id_: str = "c1", source_id: str = "s1") -> Citation:
    return Citation(id=id_, source_id=source_id, source_type="document")


class TestGoalSpec:
    def test_construction(self) -> None:
        goal = GoalSpec(
            objective="Summarize the order",
            deliverable_type=DeliverableType.ANSWER,
            success_criteria=("mentions total",),
        )
        assert goal.objective == "Summarize the order"
        assert goal.deliverable_type is DeliverableType.ANSWER
        assert goal.success_criteria == ("mentions total",)


class TestBlueprintRequest:
    def test_generic_output_schema(self) -> None:
        request = BlueprintRequest[_OrderSummary](
            blueprint_id="bp-1",
            blueprint_version="1.0",
            goal=GoalSpec(objective="x", deliverable_type=DeliverableType.ANSWER),
            entities=(),
            style=StyleSpec(tone="neutral", max_tokens=100, output_format=OutputFormat.JSON),
            policies=(),
            output_schema=_OrderSummary,
            grounding_refs=(_citation(),),
        )
        assert request.output_schema is _OrderSummary
        assert request.policy_retry_budget == 2
        assert request.tool_loop_budget == 5

    def test_untyped_output_schema(self) -> None:
        policy = PolicySpec(rule_id="no-internal", kind=PolicyKind.MUST_NOT, description="internal-only")
        request = BlueprintRequest[BaseModel](
            blueprint_id="bp-1",
            blueprint_version="1.0",
            goal=GoalSpec(objective="x", deliverable_type=DeliverableType.REPORT),
            entities=("order-42",),
            style=StyleSpec(tone="formal", max_tokens=500, output_format=OutputFormat.MARKDOWN),
            policies=(policy,),
            output_schema=None,
            grounding_refs=(),
        )
        assert request.output_schema is None
        assert request.entities == ("order-42",)
        assert request.policies[0].kind is PolicyKind.MUST_NOT


class TestStructuredResult:
    def test_carries_provenance(self) -> None:
        result: StructuredResult[BaseModel] = StructuredResult(
            output=None,
            raw_text="draft text",
            cited_evidence_refs=(_citation(),),
            blueprint_id="bp-1",
            blueprint_version="1.3.0",
        )
        assert result.blueprint_id == "bp-1"
        assert result.blueprint_version == "1.3.0"
        assert result.cited_evidence_refs == (_citation(),)


class TestErrors:
    def test_streaming_incomplete_error_carries_partial_state(self) -> None:
        err = StreamingIncompleteError(finish_reason="length", partial_tokens=42)
        assert err.finish_reason == "length"
        assert err.partial_tokens == 42

    def test_policy_exhausted_error_carries_violations(self) -> None:
        err = PolicyExhaustedError(violations=("rule-a", "rule-b"))
        assert err.violations == ("rule-a", "rule-b")

    def test_tool_loop_exhausted_error_carries_rounds(self) -> None:
        err = ToolLoopExhaustedError(rounds=5)
        assert err.rounds == 5

    def test_tool_loop_fabrication_error_carries_call_identity(self) -> None:
        err = ToolLoopFabricationError(tool_name="search", tool_call_id="call-1")
        assert err.tool_name == "search"
        assert err.tool_call_id == "call-1"

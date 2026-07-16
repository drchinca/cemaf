"""Integration: DefaultStructuredGenerator drives a real LLMClient + ToolRegistry
through the SPEC-03 invariants — schema validation, policy enforcement,
grounding-membership filtering, and the TERMINAL_TOOL round loop.

Real MockLLMClient (CEMAF's sanctioned fake, not an ad-hoc mock) and a real
ToolRegistry/Tool — no patch(), no invented test doubles.
"""

from __future__ import annotations

import json

import pytest
from pydantic import BaseModel

from cemaf.citation.models import Citation
from cemaf.core.result import Result
from cemaf.core.types import ToolID
from cemaf.generation.blueprint_request import (
    BlueprintRequest,
    DeliverableType,
    GoalSpec,
    OutputFormat,
    PolicyExhaustedError,
    PolicyKind,
    PolicySpec,
    StyleSpec,
    ToolLoopExhaustedError,
    ToolLoopFabricationError,
)
from cemaf.generation.structured_generator import DefaultStructuredGenerator
from cemaf.llm.mock import MockLLMClient
from cemaf.llm.protocols import ToolCall
from cemaf.tools.base import Tool, ToolResult, ToolSchema
from cemaf.tools.registry import ToolRegistry


class _OrderSummary(BaseModel):
    total: float
    item_count: int


def _citation(id_: str, source_id: str) -> Citation:
    return Citation(id=id_, source_id=source_id, source_type="document")


def _base_request(**overrides: object) -> BlueprintRequest[_OrderSummary]:
    defaults: dict[str, object] = {
        "blueprint_id": "bp-order-summary",
        "blueprint_version": "1.0",
        "goal": GoalSpec(objective="Summarize the order", deliverable_type=DeliverableType.ANSWER),
        "entities": (),
        "style": StyleSpec(tone="neutral", max_tokens=200, output_format=OutputFormat.JSON),
        "policies": (),
        "output_schema": _OrderSummary,
        "grounding_refs": (_citation("c1", "doc-1"),),
    }
    defaults.update(overrides)
    return BlueprintRequest(**defaults)  # type: ignore[arg-type]


class _LookupTool(Tool):
    """Returns a fixed order total."""

    @property
    def id(self) -> ToolID:
        return ToolID("lookup_order")

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="lookup_order",
            description="Look up an order's total",
            parameters={"type": "object", "properties": {"order_id": {"type": "string"}}},
            required=("order_id",),
        )

    async def execute(self, **kwargs: object) -> ToolResult:
        return Result.ok('{"total": 42.5, "item_count": 3}')


@pytest.mark.asyncio
async def test_generate_returns_validated_schema_output() -> None:
    client = MockLLMClient(responses=[json.dumps({"total": 42.5, "item_count": 3})])
    registry = ToolRegistry()
    generator = DefaultStructuredGenerator()

    result = await generator.generate(request=_base_request(), client=client, tool_registry=registry)

    assert result.output == _OrderSummary(total=42.5, item_count=3)
    assert result.blueprint_id == "bp-order-summary"
    assert result.blueprint_version == "1.0"


@pytest.mark.asyncio
async def test_no_grounding_refs_means_no_cited_evidence() -> None:
    """Inv 9's filter has nothing to admit when the tool loop produces no
    citations — today's _dispatch_tool always returns (), since SPEC-05's
    ClaimExtractor (the thing that would attach citations to tool output) is
    not yet landed. Unit-level filter coverage lives in
    tests/unit/generation/test_structured_generator.py."""
    client = MockLLMClient(responses=[json.dumps({"total": 10.0, "item_count": 1})])
    registry = ToolRegistry()
    generator = DefaultStructuredGenerator()

    result = await generator.generate(
        request=_base_request(grounding_refs=(_citation("real", "doc-1"),)),
        client=client,
        tool_registry=registry,
    )

    assert result.cited_evidence_refs == ()


@pytest.mark.asyncio
async def test_policy_violation_triggers_regeneration_then_succeeds() -> None:
    """Inv 7: a MUST_NOT violation triggers re-generation; second attempt clears it."""
    client = MockLLMClient(
        responses=[
            "This contains internal-only data.",
            json.dumps({"total": 5.0, "item_count": 1}),
        ]
    )
    registry = ToolRegistry()
    generator = DefaultStructuredGenerator()
    policy = PolicySpec(rule_id="no-internal", kind=PolicyKind.MUST_NOT, description="internal-only")

    result = await generator.generate(
        request=_base_request(policies=(policy,)), client=client, tool_registry=registry
    )

    assert client.call_count == 2
    assert result.output == _OrderSummary(total=5.0, item_count=1)


@pytest.mark.asyncio
async def test_policy_exhausted_raises_after_retry_budget() -> None:
    """Inv 7: exceeding policy_retry_budget raises PolicyExhaustedError."""
    client = MockLLMClient(responses=["internal-only always"])
    registry = ToolRegistry()
    generator = DefaultStructuredGenerator()
    policy = PolicySpec(rule_id="no-internal", kind=PolicyKind.MUST_NOT, description="internal-only")

    with pytest.raises(PolicyExhaustedError) as exc_info:
        await generator.generate(
            request=_base_request(policies=(policy,), policy_retry_budget=1),
            client=client,
            tool_registry=registry,
        )
    assert "no-internal" in exc_info.value.violations


@pytest.mark.asyncio
async def test_tool_loop_completes_via_continuation() -> None:
    """A TERMINAL_TOOL round dispatches the tool, then TERMINAL_STOP returns the result."""
    tool_call = ToolCall(id="call-1", name="lookup_order", arguments={"order_id": "42"})
    client = MockLLMClient(
        responses=["", json.dumps({"total": 42.5, "item_count": 3})],
        tool_calls=[[tool_call]],
    )
    registry = ToolRegistry()
    registry.register(_LookupTool)
    generator = DefaultStructuredGenerator()

    request = _base_request(
        tool_schemas=(
            ToolSchema(
                name="lookup_order", description="lookup", parameters={"type": "object", "properties": {}}
            ),
        )
    )
    result = await generator.generate(request=request, client=client, tool_registry=registry)

    assert result.output == _OrderSummary(total=42.5, item_count=3)
    assert client.call_count == 2


@pytest.mark.asyncio
async def test_tool_loop_exhausts_budget() -> None:
    """Inv 11: TERMINAL_TOOL on every round past tool_loop_budget raises."""
    tool_call = ToolCall(id="call-1", name="lookup_order", arguments={"order_id": "42"})
    client = MockLLMClient(
        responses=["", "", ""],
        tool_calls=[[tool_call], [tool_call], [tool_call]],
    )
    registry = ToolRegistry()
    registry.register(_LookupTool)
    generator = DefaultStructuredGenerator()

    request = _base_request(
        tool_loop_budget=2,
        tool_schemas=(
            ToolSchema(
                name="lookup_order", description="lookup", parameters={"type": "object", "properties": {}}
            ),
        ),
    )

    with pytest.raises(ToolLoopExhaustedError) as exc_info:
        await generator.generate(request=request, client=client, tool_registry=registry)
    assert exc_info.value.rounds == 2


@pytest.mark.asyncio
async def test_unverified_tool_output_blocks_fabrication() -> None:
    """Inv 11: an unverified tool output raises before it's fed back to the LLM."""
    tool_call = ToolCall(id="call-1", name="lookup_order", arguments={"order_id": "42"})
    client = MockLLMClient(responses=[""], tool_calls=[[tool_call]])
    registry = ToolRegistry()
    registry.register(_LookupTool)

    async def _always_reject(
        _text: str, _citations: tuple[Citation, ...], _grounding: tuple[Citation, ...]
    ) -> bool:
        return False

    generator = DefaultStructuredGenerator(tool_output_verifier=_always_reject)

    request = _base_request(
        tool_schemas=(
            ToolSchema(
                name="lookup_order", description="lookup", parameters={"type": "object", "properties": {}}
            ),
        )
    )

    with pytest.raises(ToolLoopFabricationError) as exc_info:
        await generator.generate(request=request, client=client, tool_registry=registry)
    assert exc_info.value.tool_name == "lookup_order"

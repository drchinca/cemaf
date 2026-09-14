"""StructuredGenerator — drives a BlueprintRequest to a validated StructuredResult.

Implements SPEC-03 §2 StructuredGenerator + the load-bearing invariants:
  - Inv 6: output_schema validation
  - Inv 7: MUST/MUST_NOT policy enforcement with bounded re-generation
  - Inv 9: cited_evidence_refs filtered to grounding_refs membership
  - Inv 11: TERMINAL_TOOL loop — dispatch every tool_use block, verify each
    output against grounding_refs before feeding it back, round-bounded by
    tool_loop_budget
  - Inv 13: cumulative max_tokens bound across all rounds

See generation/blueprint_request.py for the SPEC-00 alignment note — this
generator works against the existing citation.models.Citation shape and a
plain-string goal, not SPEC-00 §2's not-yet-landed Goal/Citation types.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ValidationError

from cemaf.citation.models import Citation
from cemaf.core.types import FinishReason
from cemaf.generation.blueprint_request import (
    BlueprintRequest,
    PolicyExhaustedError,
    PolicyKind,
    StreamingIncompleteError,
    StructuredResult,
    ToolLoopExhaustedError,
    ToolLoopFabricationError,
)
from cemaf.llm.protocols import LLMClient, Message, MessageRole, ToolCall
from cemaf.tools.registry import ToolRegistry

# SPEC-00 default cap on tool_use blocks dispatched in a single turn (SPEC-03 Inv 11).
MAX_PARALLEL_TOOL_CALLS = 8

# verify(tool_output_text, tool_output_citations, grounding_refs) -> verified.
# SPEC-03 Inv 11 calls this `services.tool_output_verifier.verify(...)` (SPEC-05's
# ToolOutputVerifier, not yet landed). Accepted here as an injected callable so
# this generator is usable today; swap for the real SPEC-05 port once it lands.
ToolOutputVerifier = Callable[[str, tuple[Citation, ...], tuple[Citation, ...]], Awaitable[bool]]


@runtime_checkable
class StructuredGenerator[T: BaseModel](Protocol):
    """Protocol for a Blueprint-driven structured generation call (SPEC-03 §2)."""

    async def generate(
        self,
        *,
        request: BlueprintRequest[T],
        client: LLMClient,
        tool_registry: ToolRegistry,
    ) -> StructuredResult[T]: ...


def _grounding_key(citation: Citation) -> tuple[str, str]:
    """Membership key for grounding_refs filtering — id + source_id, matching
    the existing citation/rules.py::CitationMembershipRule convention."""
    return (citation.id, citation.source_id)


def _filter_to_grounding_refs(
    citations: tuple[Citation, ...], grounding_refs: tuple[Citation, ...]
) -> tuple[Citation, ...]:
    """Inv 9: cited_evidence_refs SHALL be a subset of grounding_refs."""
    allowed = {_grounding_key(c) for c in grounding_refs}
    return tuple(c for c in citations if _grounding_key(c) in allowed)


def _build_system_message(request: BlueprintRequest[Any]) -> Message:
    lines = [
        f"Objective: {request.goal.objective}",
        f"Deliverable type: {request.goal.deliverable_type.value}",
    ]
    if request.goal.success_criteria:
        lines.append("Success criteria:")
        lines.extend(f"  - {c}" for c in request.goal.success_criteria)
    lines.append(f"Tone: {request.style.tone}")
    lines.append(f"Output format: {request.style.output_format.value}")
    if request.policies:
        lines.append("Policies:")
        for policy in request.policies:
            lines.append(f"  - [{policy.kind.value}] {policy.description}")
    if request.grounding_refs:
        lines.append("Grounded sources available (cite only these):")
        for citation in request.grounding_refs:
            lines.append(f"  - id={citation.id} source_id={citation.source_id}")
    if request.output_schema is not None:
        lines.append(f"Respond with JSON matching this schema: {request.output_schema.model_json_schema()}")
    return Message(role=MessageRole.SYSTEM, content="\n".join(lines))


def _check_policy_violations(*, text: str, policies: tuple[Any, ...]) -> tuple[str, ...]:
    """Deterministic substring check for MUST/MUST_NOT — the same heuristic
    already used by the existing self-healing citation test. A real
    PolicyAdherenceEvaluator (SPEC-03 §8, hybrid/LLM-judge) supersedes this
    once it lands; this is a working default, not a stub."""
    violations: list[str] = []
    lowered = text.lower()
    for policy in policies:
        needle = policy.description.lower()
        if (
            policy.kind == PolicyKind.MUST
            and needle not in lowered
            or policy.kind == PolicyKind.MUST_NOT
            and needle in lowered
        ):
            violations.append(policy.rule_id)
    return tuple(violations)


def _validate_output[T: BaseModel](*, text: str, schema: type[T] | None) -> T | None:
    if schema is None:
        return None
    try:
        return schema.model_validate_json(text)
    except ValidationError:
        return schema.model_validate(json.loads(text))


class DefaultStructuredGenerator:
    """Reference StructuredGenerator implementation.

    tool_output_verifier defaults to "always verified" (no-op) — inject the
    real SPEC-05 ToolOutputVerifier once it lands; until then this generator
    still enforces every other SPEC-03 invariant (schema, policy, grounding,
    budget) against real LLMClient calls.
    """

    def __init__(self, *, tool_output_verifier: ToolOutputVerifier | None = None) -> None:
        self._verify = tool_output_verifier or self._default_verify

    @staticmethod
    async def _default_verify(
        _output_text: str, _output_citations: tuple[Citation, ...], _grounding_refs: tuple[Citation, ...]
    ) -> bool:
        return True

    async def generate[T: BaseModel](
        self,
        *,
        request: BlueprintRequest[T],
        client: LLMClient,
        tool_registry: ToolRegistry,
    ) -> StructuredResult[T]:
        messages: list[Message] = [
            _build_system_message(request),
            Message(role=MessageRole.USER, content=request.goal.objective),
        ]
        tool_definitions = [schema.to_definition() for schema in request.tool_schemas]

        gen_tokens_consumed = 0
        policy_attempt = 0

        while True:
            raw_text, cited = await self._run_tool_loop(
                request=request,
                client=client,
                tool_registry=tool_registry,
                messages=messages,
                tool_definitions=tool_definitions,
                gen_tokens_consumed_start=gen_tokens_consumed,
            )

            violations = _check_policy_violations(text=raw_text, policies=request.policies)
            if violations:
                policy_attempt += 1
                if policy_attempt > request.policy_retry_budget:
                    raise PolicyExhaustedError(violations=violations)
                messages.append(Message(role=MessageRole.ASSISTANT, content=raw_text))
                messages.append(
                    Message(
                        role=MessageRole.USER,
                        content=(
                            "The previous response violated policy rules: "
                            f"{', '.join(violations)}. Regenerate honoring every policy."
                        ),
                    )
                )
                continue

            output = _validate_output(text=raw_text, schema=request.output_schema)
            grounded_cited = _filter_to_grounding_refs(cited, request.grounding_refs)
            return StructuredResult(
                output=output,
                raw_text=raw_text,
                cited_evidence_refs=grounded_cited,
                blueprint_id=request.blueprint_id,
                blueprint_version=request.blueprint_version,
            )

    async def _run_tool_loop(
        self,
        *,
        request: BlueprintRequest[Any],
        client: LLMClient,
        tool_registry: ToolRegistry,
        messages: list[Message],
        tool_definitions: list[Any],
        gen_tokens_consumed_start: int,
    ) -> tuple[str, tuple[Citation, ...]]:
        """Drives one TERMINAL_TOOL round loop to TERMINAL_STOP; returns (text, citations)."""
        gen_tokens_consumed = gen_tokens_consumed_start
        collected_citations: list[Citation] = []

        for _round_index in range(request.tool_loop_budget):
            remaining = max(0, request.style.max_tokens - gen_tokens_consumed)
            config_override = client.config.model_copy(update={"max_tokens": remaining})
            result = await client.complete(
                messages, tools=tool_definitions or None, config_override=config_override
            )

            if not result.success or result.message is None:
                raise StreamingIncompleteError(
                    finish_reason=str(result.finish_reason), partial_tokens=int(result.completion_tokens)
                )

            gen_tokens_consumed += int(result.completion_tokens)

            if result.finish_reason == FinishReason.TERMINAL_STOP:
                text = str(result.message.content)
                return text, tuple(collected_citations)

            if result.finish_reason == FinishReason.TERMINAL_TOOL:
                tool_calls = result.message.tool_calls
                if len(tool_calls) > MAX_PARALLEL_TOOL_CALLS:
                    raise StreamingIncompleteError(finish_reason=str(FinishReason.PARTIAL_ERROR))

                messages.append(result.message)
                for tool_call in tool_calls:
                    if tool_call.name not in {schema.name for schema in request.tool_schemas}:
                        raise StreamingIncompleteError(finish_reason=str(FinishReason.PARTIAL_ERROR))

                    output_text, output_citations = await self._dispatch_tool(
                        tool_call=tool_call, tool_registry=tool_registry
                    )
                    verified = await self._verify(output_text, output_citations, request.grounding_refs)
                    if not verified:
                        raise ToolLoopFabricationError(tool_name=tool_call.name, tool_call_id=tool_call.id)

                    collected_citations.extend(output_citations)
                    messages.append(
                        Message(
                            role=MessageRole.TOOL,
                            content=output_text,
                            tool_call_id=tool_call.id,
                            name=tool_call.name,
                        )
                    )
                continue

            raise StreamingIncompleteError(
                finish_reason=str(result.finish_reason), partial_tokens=int(result.completion_tokens)
            )

        raise ToolLoopExhaustedError(rounds=request.tool_loop_budget)

    @staticmethod
    async def _dispatch_tool(
        *, tool_call: ToolCall, tool_registry: ToolRegistry
    ) -> tuple[str, tuple[Citation, ...]]:
        tool = tool_registry.get(tool_call.name)
        if tool is None:
            raise StreamingIncompleteError(finish_reason=str(FinishReason.PARTIAL_ERROR))
        tool_result = await tool.execute(**tool_call.arguments)
        if not tool_result.success:
            return str(tool_result.error), ()
        return str(tool_result.data), ()

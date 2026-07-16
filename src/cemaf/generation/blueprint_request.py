"""Blueprint-driven structured generation — SPEC-03 adapted to landed types.

SPEC-03 (docs/specs/SPEC-03-blueprint-as-llm-input.md) specifies BlueprintRequest
against SPEC-00 §2 common types (Goal, a new Citation shape, EntityRef,
BlueprintID) that are not yet ported into core/types.py, and whose Citation
shape conflicts with the Citation already used throughout citation/,
retrieval/, and evals/grounding.py. This module implements SPEC-03's request/
result/error contract against what's actually landed:
  - goal: str (CEMAF's existing generic GoalT pattern has no shared Goal type)
  - citations: cemaf.citation.models.Citation (the one real implementation)
  - entities: str identifiers (EntityRef does not exist)
See docs/architecture/roadmap-plan.md Phase 4 for the SPEC-00 alignment gap.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum

from pydantic import BaseModel

from cemaf.citation.models import Citation
from cemaf.tools.base import ToolSchema

# SPEC-00 §2 declares `BlueprintID = NewType("BlueprintID", str)`. A plain
# alias here (not NewType) matches how `blueprint/core.py::Blueprint.id` is
# already typed as `str` — promote to NewType only once SPEC-00 §2 lands.
BlueprintID = str


class DeliverableType(StrEnum):
    """What kind of output the generation call is expected to produce."""

    REPORT = "report"
    DECISION = "decision"
    CODE = "code"
    ANSWER = "answer"


class OutputFormat(StrEnum):
    """Wire shape of the generated content."""

    MARKDOWN = "markdown"
    JSON = "json"
    PLAIN = "plain"


class PolicyKind(StrEnum):
    """MUST/MUST_NOT enforcement direction for a PolicySpec rule."""

    MUST = "MUST"
    MUST_NOT = "MUST_NOT"


@dataclass(frozen=True, slots=True)
class GoalSpec:
    """Typed restatement of node intent — what to produce."""

    objective: str
    deliverable_type: DeliverableType
    success_criteria: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class StyleSpec:
    """Generation style constraints — SPEC-03 Inv 13 binds max_tokens against this."""

    tone: str
    max_tokens: int
    output_format: OutputFormat


@dataclass(frozen=True, slots=True)
class PolicySpec:
    """One MUST/MUST_NOT rule the StructuredGenerator enforces before returning."""

    rule_id: str
    kind: PolicyKind
    description: str


@dataclass(frozen=True, slots=True)
class BlueprintRequest[T: BaseModel]:
    """The structured LLM request derived from a Blueprint (SPEC-03 §2).

    Generic in T: BaseModel so callers get typed access to StructuredResult.output.
    Untyped sites use BlueprintRequest[BaseModel].
    """

    blueprint_id: BlueprintID
    blueprint_version: str
    goal: GoalSpec
    entities: tuple[str, ...]
    style: StyleSpec
    policies: tuple[PolicySpec, ...]
    output_schema: type[T] | None
    grounding_refs: tuple[Citation, ...]
    policy_retry_budget: int = 2
    tool_loop_budget: int = 5
    tool_schemas: tuple[ToolSchema, ...] = ()
    metadata: Mapping[str, str] = field(default_factory=dict)


class StreamingIncompleteError(RuntimeError):
    """Raised when the upstream LLM stream returns a partial finish_reason (Inv 11/12)."""

    def __init__(self, *, finish_reason: str, partial_tokens: int = 0) -> None:
        self.finish_reason = finish_reason
        self.partial_tokens = partial_tokens
        super().__init__(f"stream ended with partial finish_reason={finish_reason!r}")


class PolicyExhaustedError(RuntimeError):
    """Raised when blueprint MUST/MUST_NOT re-generation budget is exhausted (Inv 7)."""

    def __init__(self, *, violations: tuple[str, ...]) -> None:
        self.violations = violations
        super().__init__(f"policy retry budget exhausted; unresolved violations={violations!r}")


class ToolLoopExhaustedError(RuntimeError):
    """Raised when the tool-call loop exceeds tool_loop_budget rounds (Inv 11)."""

    def __init__(self, *, rounds: int) -> None:
        self.rounds = rounds
        super().__init__(f"tool loop exhausted after {rounds} rounds")


class ToolLoopFabricationError(RuntimeError):
    """Raised when an intra-loop tool output fails citation-membership verification (Inv 11)."""

    def __init__(self, *, tool_name: str, tool_call_id: str) -> None:
        self.tool_name = tool_name
        self.tool_call_id = tool_call_id
        super().__init__(f"unverified tool output from {tool_name!r} (call_id={tool_call_id!r})")


@dataclass(frozen=True, slots=True)
class StructuredResult[T: BaseModel]:
    """Validated output of one StructuredGenerator.generate call (SPEC-03 §2)."""

    output: T | None
    raw_text: str
    cited_evidence_refs: tuple[Citation, ...]
    blueprint_id: BlueprintID
    blueprint_version: str

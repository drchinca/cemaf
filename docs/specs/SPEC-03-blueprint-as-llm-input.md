---
title: Blueprint as LLM Input
spec_id: SPEC-03
status: Reviewed
last_reviewed: 2026-05-27
owner: drchinca
parent: SPEC-00 — Enterprise Context Brain
depends_on: SPEC-01, SPEC-02
---

# SPEC-03: Blueprint as LLM Input

> Replaces free-form English prompts with structured **Blueprints** as the
> canonical node input for any LLM-calling node. Generation flows from
> Blueprint → typed `BlueprintRequest` → structured response, eliminating
> prompt-stuffing and enabling versioning, A/B routing, and offline evaluation.

## 1. Context

`blueprint/Blueprint` exists with `to_prompt()` but generation today still
constructs English from ad-hoc string templates. Blueprints are advisory, not
load-bearing.

This spec wires Blueprint into the generation path as the **only** allowed
node input shape for any node where `node.is_llm_node == True`. The
interceptor pipeline gains a `BlueprintInterceptor` (PRE phase, position 3 —
runs **after** PullInterceptor so it can bind already-surfaced sources as
grounding refs to the blueprint request). `generation/` gains `BlueprintRequest`
as the typed call shape.

## 2. Interface Contract (MDE)

Common types in SPEC-00 §2 (`Goal`, `AgentResult`, `Citation`, `BlueprintID`).
Tool surface symbols (`ToolSchema`, `ToolRegistry`) come from the existing
CEMAF `tools/` layer (CLAUDE.md "Module Map → Agent System").

```python
from typing import Generic, Protocol, TypeVar, runtime_checkable
from collections.abc import Mapping
from dataclasses import dataclass, field
from pydantic import BaseModel
from cemaf.tools import ToolSchema, ToolRegistry           # tools/base.py, tools/registry.py

T = TypeVar("T", bound=BaseModel)

@dataclass(frozen=True, slots=True)
class GoalSpec:
    """Typed restatement of node intent — what to produce."""
    objective: str
    deliverable_type: str            # "report" | "decision" | "code" | "answer" ...
    success_criteria: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class StyleSpec:
    tone: str
    max_tokens: int
    output_format: str               # "markdown" | "json" | "plain"

@dataclass(frozen=True, slots=True)
class PolicySpec:
    rule_id: str
    kind: str                        # "MUST" | "MUST_NOT"
    description: str

@dataclass(frozen=True, slots=True)
class BlueprintRequest(Generic[T]):
    """The structured LLM request derived from a Blueprint.
    Generic in T: BaseModel so callers get typed access to StructuredResult.output.
    Untyped sites use BlueprintRequest[BaseModel]."""
    blueprint_id: BlueprintID
    blueprint_version: str
    goal: GoalSpec
    entities: tuple[EntityRef, ...]                  # informational — SPEC-02 PullInterceptor extracts entities from goal.text; BlueprintRequest.entities does NOT feed retrieval. This is intentional (Pull runs at PRE position 2, Blueprint at position 3); declare any required entities in goal.metadata for upstream extraction.
    style: StyleSpec
    policies: tuple[PolicySpec, ...]
    output_schema: type[T] | None                    # see "Grounding annotation policy" below
    grounding_refs: tuple[Citation, ...]            # derived from ctx.surfaced_sources
    policy_retry_budget: int = 2                     # consumed by StructuredGenerator (Inv 7)
    tool_loop_budget: int = 5                        # bounds the TERMINAL_TOOL → tool exec → resume loop (Inv 11)
    tool_schemas: tuple[ToolSchema, ...] = ()        # frozen tool surface for this call; folded into canonical serialization (Inv 4)
    metadata: Mapping[str, str] = field(default_factory=dict)   # Mapping per SPEC-00 §2 canonical wrap pattern

class StreamingIncompleteError(RuntimeError):
    """Raised when the upstream LLM stream returns a partial finish_reason (Inv 11)."""

class PolicyExhaustedError(RuntimeError):
    """Raised when blueprint MUST/MUST_NOT re-generation budget is exhausted (Inv 7)."""

class ToolLoopExhaustedError(RuntimeError):
    """Raised when the StructuredGenerator's tool-call loop exceeds tool_loop_budget."""

@dataclass(frozen=True, slots=True)
class StructuredResult(Generic[T]):
    output: T | None                                 # validated when output_schema is set; typed to the schema
    raw_text: str
    cited_evidence_refs: tuple[Citation, ...]
    blueprint_id: BlueprintID
    blueprint_version: str

@runtime_checkable
class BlueprintLibrary(Protocol):
    def get(self, blueprint_id: BlueprintID, *, version: str | None = None) -> Blueprint: ...
    def list_for_capability(self, capability: str) -> tuple[Blueprint, ...]: ...
    def list_all(self) -> tuple[Blueprint, ...]:
        """Enumerate every registered (blueprint_id, version) pair.
        Consumed by SPEC-00 §6 spec audit; cardinality cap ≤200 per §9."""
    def resolve_for_node(self, *, node: DAGNode, goal: Goal) -> Blueprint | None:
        """Resolution policy: explicit node.blueprint_id > capability match > None."""

class BlueprintInterceptor(NodeInterceptor):
    """PRE phase, position 3 — runs AFTER PullInterceptor.

    Pipeline:
      1. If not node.is_llm_node → ACCEPT no-enrichment.
      2. library.resolve_for_node(node, goal). None → REJECT("no_blueprint_resolved").
      3. Build BlueprintRequest:
           - GoalSpec from blueprint + goal.text
           - entities from node.entities or extracted from goal
           - grounding_refs := tuple(c.citation for c in ctx.surfaced_sources)
      4. Attach to enriched_goal.metadata["blueprint_request"] (serialized).
    """
    interceptor_id = "blueprint"
    phase = InterceptorPhase.PRE

class StructuredGenerator(Protocol):
    async def generate(
        self, *,
        request: BlueprintRequest[T],
        client: LLMClient,
        tool_registry: ToolRegistry,            # bound by ContextNodeExecutor from services.tool_registry
    ) -> StructuredResult[T]: ...
```

### Grounding annotation policy

`SchemaFieldClaimExtractor` (SPEC-05 §2) treats only Pydantic fields annotated
`Field(json_schema_extra={"grounding_required": True})` as Claims. To prevent
factual prose escaping claim extraction, every blueprint that declares an
`output_schema` containing a free-text factual field SHALL annotate that
field. Built-in conventions:

| Field name (or role) | Annotation |
|---|---|
| `summary`, `answer`, `findings`, `recommendation`, `description`, `analysis`, `narrative`, free-text factual prose | `grounding_required=True` |
| Names in STRUCTURAL_METADATA_ALLOW_LIST (closed set, see below) | NOT annotated (these are not Claims) |

`STRUCTURAL_METADATA_ALLOW_LIST` (single source of truth for the SPEC-00 §6
Spec Audit gate; closed set, additions require a spec PR amending this list):

```python
STRUCTURAL_METADATA_ALLOW_LIST: frozenset[str] = frozenset({
    # Identifiers
    "id", "uuid", "external_id", "ref", "ref_id", "key",
    # Foreign keys
    "parent_id", "owner_id", "tenant_id", "workspace_id", "task_id",
    "node_id", "dag_id", "blueprint_id", "correlation_id", "source_id",
    # Status / classification
    "status", "state", "kind", "type", "category", "label", "tag",
    # Numeric scoring (not factual prose)
    "score", "confidence", "rank", "version", "count", "total",
    # Timestamps
    "created_at", "updated_at", "started_at", "finished_at", "at",
    # Booleans (always non-factual-prose)
    "enabled", "active", "verified", "achieved",
})
```

The spec audit (SPEC-00 §6 Spec Audit) SHALL fail the build when any
registered blueprint has an `output_schema` field that satisfies ALL of:
(1) Pydantic field type is `str` or `Optional[str]`; (2) declared
`max_length ≥ 64` or no `max_length` constraint; (3) field `name`
NOT in `STRUCTURAL_METADATA_ALLOW_LIST` AND NOT in the
PR-amendable extension set in `cemaf/data/eval_pins/grounding_allow_list_extensions.json`;
AND (4) field annotation lacks `Field(json_schema_extra={"grounding_required": True})`.
Override (i.e., declare a free-text field that is genuinely structural and
should not require grounding) requires an explicit waiver entry in
`cemaf/data/eval_pins/grounding_audit_waivers.json` carrying
`{blueprint_id, field_name, justification}`.

## 3. Invariants (DbC)

1. `WHEN node.is_llm_node == True AND BlueprintLibrary.resolve_for_node returns None, THE BlueprintInterceptor SHALL emit REJECT(reason="no_blueprint_resolved").`
2. `WHEN node.is_llm_node == False, THE BlueprintInterceptor SHALL emit ACCEPT with no enrichment.`
3. `BlueprintRequest.grounding_refs SHALL equal tuple(c.citation for c in ctx.surfaced_sources) at the moment BlueprintInterceptor runs. The LLM call carries citation_id only — Citation.locator (which may be a long URL or KG ref) SHALL NOT be inlined into the prompt; this keeps the request size O(citation_id × N) rather than O(locator × N) and preserves enforceability of node.budget.generation_tokens. The generator resolves locator at post-flight from ctx.surfaced_sources for cite-or-fail membership and for user-facing rendering.`
4. `THE BlueprintRequest SHALL be structurally equal under canonical serialization given the same Blueprint, goal, entities, ctx.surfaced_sources, and tool_schemas (replay-deterministic). Canonical serialization SHALL include tool_schemas in sorted-key form so registry mutations between runs surface as byte-level drift.`
5. `Every StructuredResult SHALL carry the source blueprint_id and version (provenance).`
6. `IF blueprint declares output_schema, THEN StructuredResult.output SHALL be an instance of that schema and pass its validators; failure → PostflightDecision determined by node.schema_failure_policy (SPEC-00 §2 SchemaFailurePolicy enum, default RECOVER).`
7. `Policies in the Blueprint (MUST / MUST_NOT) SHALL be enforced by the StructuredGenerator before returning the result; violations trigger re-generation up to BlueprintRequest.policy_retry_budget (default 2). On exhaustion the generator SHALL raise PolicyExhaustedError; the post-flight chain converts it to REJECT(reason="policy_exhausted").`
8. `BlueprintLibrary SHALL return immutable Blueprint instances; mutation requires a new version (semver bump).`
9. `THE generator SHALL filter cited_evidence_refs to ⊆ BlueprintRequest.grounding_refs before returning the StructuredResult — i.e., it SHALL NOT introduce non-member Citations. SPEC-05 cite-or-fail enforces the same membership predicate at post-flight against ctx.surfaced_sources (which equals grounding_refs at the moment BlueprintInterceptor ran, per Inv 3) — the two checks are redundant by design (defense in depth).`
10. `IF a registered blueprint declares an output_schema with a free-text factual field (str-typed, max_length ≥ 64 or unbounded, name ∉ structural-metadata allow-list per §2 "Grounding annotation policy") AND no field on that schema carries grounding_required=True, THEN the SPEC-00 §6 Spec Audit SHALL fail the build. Override requires a waiver entry in cemaf/data/eval_pins/grounding_audit_waivers.json with a justification string.`
11. `StructuredGenerator.generate SHALL return only after the upstream LLM stream has reached its terminal token (finish_reason == FinishReason.TERMINAL_STOP per SPEC-00 §2). WHEN finish_reason == FinishReason.TERMINAL_TOOL, THE StructuredGenerator SHALL execute EVERY tool_use block emitted in that turn (in provider-emitted order), append one ToolCallOutput per call with matched tool_call_id, AND for each newly produced tool output SHALL invoke services.tool_output_verifier.verify(tool_outputs=(out,), surfaced=request.grounding_refs) BEFORE feeding the result back into the LLM stream — on verified=False the generator SHALL raise ToolLoopFabricationError converted by post-flight to RECOVER(RETRY_WITH_HINTS, reason='tool_unverified_in_loop') subject to SPEC-05 Inv 15 budget escalation. Number of parallel tool calls per turn SHALL NOT exceed SPEC-00 MAX_PARALLEL_TOOL_CALLS (default 8); excess raises StreamingIncompleteError(finish_reason=FinishReason.PARTIAL_ERROR). The LLM adapter SHALL serialize tool results to the provider-native envelope per the SPEC-00 §2 canonical mapping table. The generator returns ONLY when a resumed stream reaches FinishReason.TERMINAL_STOP, or raises StreamingIncompleteError if any resumed stream returns a partial reason. BlueprintRequest.tool_loop_budget (default 5) bounds the number of TERMINAL_TOOL ROUNDS (provider turns), not individual calls — a single turn with 3 parallel tool_use blocks consumes 1 round; on round-count exhaustion the generator SHALL raise ToolLoopExhaustedError converted by post-flight to REJECT(reason="tool_loop_exhausted"). Across all rounds within one StructuredGenerator.generate call, the generator SHALL maintain a running gen_tokens_consumed counter and request max_tokens = max(0, node.budget.generation_tokens - gen_tokens_consumed) on each resumed stream — exhaustion raises StreamingIncompleteError(finish_reason=FinishReason.PARTIAL_LENGTH) so a tool_loop_budget=N call cannot exceed node.budget.generation_tokens (closes the per-call cap multiplication defect). Partial completion due to stream error, client-side cancellation, or finish_reason ∈ {FinishReason.PARTIAL_LENGTH, FinishReason.PARTIAL_FILTER, FinishReason.PARTIAL_ERROR} SHALL raise StreamingIncompleteError carrying the partial token count and finish_reason; the post-flight chain converts it to REJECT(reason="generation_incomplete"). Adapters MUST normalize provider-native values per the SPEC-00 §2 canonical mapping table at the adapter boundary (SPEC-00 §3 Inv 12). Validators, policy checks, and cited_evidence_ref filtering (Invs 6/7/9) SHALL NOT run against partial output — incomplete generations never produce a StructuredResult. WHEN finish_reason == FinishReason.TERMINAL_TOOL AND any requested tool_name is NOT in request.tool_schemas, THE generator SHALL raise StreamingIncompleteError(finish_reason=FinishReason.PARTIAL_ERROR) rather than dispatch — closes registry-mutation race.`
12. `WHEN a chain-level or per-interceptor timeout fires during agent.run, THE Executor SHALL cancel the upstream LLM stream, charge consumed input+output tokens to task.budget_remaining (already-paid cost), and emit RECOVER(RETRY_WITH_HINTS, reason='agent:timeout'). A cancelled stream SHALL NOT produce a StructuredResult — same path as Inv 11 (no validators, no policy checks, no cited_evidence_ref filtering on partial output). On retry exhaustion per SPEC-05 Inv 15, the chain escalates to HALT(reason='agent:timeout_exhausted'). This aligns with SPEC-05 §10 user-facing copy promising automatic retry on timeout.`
13. `THE StructuredGenerator SHALL bound the LLM request's effective max_tokens at min(node.budget.generation_tokens, blueprint.style.max_tokens). For multi-round tool loops (Inv 11), the bound is enforced cumulatively across rounds via gen_tokens_consumed — total output across all rounds in one StructuredGenerator.generate SHALL NOT exceed node.budget.generation_tokens. RuntimeServices.eval_budget applies ONLY to guardian-invoked judges (SPEC-05 Inv 17) and SHALL NOT debit task.budget_remaining or override the StructuredGenerator's per-node cap.`
14. `WHEN StructuredGenerator.generate completes (terminal or partial), THE generator SHALL emit a gen_ai.generate.structured span carrying gen_ai.request.model, gen_ai.usage.input_tokens, gen_ai.usage.output_tokens, gen_ai.response.finish_reason — including on StreamingIncompleteError paths (finish_reason ∈ partial set per Inv 11).`

## 4. Acceptance Criteria (BDD)

```gherkin
Feature: Blueprint-driven generation

  Scenario: LLM node without Blueprint is rejected
    Given a node with is_llm_node=True
    And BlueprintLibrary.resolve_for_node returns None
    When BlueprintInterceptor runs
    Then PreflightDecision is REJECT with reason "no_blueprint_resolved"
    And the agent is not invoked

  Scenario: Non-LLM node bypasses Blueprint
    Given a router node with is_llm_node=False
    When BlueprintInterceptor runs
    Then PreflightDecision is ACCEPT with no enrichment

  Scenario: grounding_refs equals surfaced_sources citations
    Given ctx.surfaced_sources contains 5 chunks with distinct Citations
    When BlueprintInterceptor runs
    Then BlueprintRequest.grounding_refs has length 5
    And each is exactly one of the chunk citations

  Scenario: Blueprint policy enforced before return
    Given a Blueprint with MUST_NOT-contain "internal-only"
    And the generator produces a draft containing "internal-only"
    When the generator runs
    Then the draft is rejected and re-generation triggered up to retry budget

  Scenario: Structured output validated
    Given a Blueprint with output_schema=OrderSummary
    When generation completes
    Then StructuredResult.output is an OrderSummary instance and validates with no errors

  Scenario: Provenance recorded
    Given a Blueprint version 1.3.0 used to drive a node
    When the result is stored
    Then StructuredResult.blueprint_id and blueprint_version are populated

  Scenario: Structural determinism under same inputs
    Given identical Blueprint, goal, entities, ctx.surfaced_sources, and tool_schemas
    When BlueprintRequest is built twice
    Then the canonical serialization (JSON, sorted keys) of both is byte-identical
    And the serialization includes tool_schemas in sorted-key form

  Scenario: blueprint.style.max_tokens binds when smaller than node budget (Inv 13)
    Given node.budget.generation_tokens == 4000 and blueprint.style.max_tokens == 800
    When StructuredGenerator dispatches the first round
    Then the LLM request carries max_tokens == 800
    And gen_tokens_consumed is initialized to 0

  Scenario: eval_budget does not debit task.budget_remaining (Inv 13)
    Given a node where guardian judges consume 500 tokens of services.eval_budget
    And the agent itself consumes 1200 tokens of node.budget.generation_tokens
    When the node completes
    Then task.budget_remaining decremented by 1200, NOT 1700
    And eval_budget consumption is observable only on the EvalBudgetCounter snapshot

  Scenario: Blueprint registry over cap fails startup
    Given BlueprintLibrary.list_all() returns 201 (id, version) pairs
    When bootstrap.create_executor runs
    Then StartupError(reason="blueprint_registry_over_cap", count=201) is raised

  Scenario: Citation filtered to grounding_refs at generator boundary
    Given a generator draft whose cited_evidence_refs includes a Citation absent from BlueprintRequest.grounding_refs
    When the generator post-processes the draft
    Then the returned StructuredResult.cited_evidence_refs has the non-member Citation removed
    And the StructuredResult is still returned (the post-flight cite-or-fail in SPEC-05 makes the final accept/reject call against ctx.surfaced_sources)

  Scenario: Spec audit fails on un-annotated factual field
    Given a registered blueprint whose output_schema has a str field "summary" with max_length=2000 and no grounding_required annotation
    And no waiver entry exists in cemaf/data/eval_pins/grounding_audit_waivers.json
    When the SPEC-00 §6 Spec Audit runs
    Then the audit fails with a message naming the blueprint and the un-annotated field

  Scenario: Spec audit passes on annotated factual field
    Given a blueprint whose output_schema has "summary" annotated grounding_required=True
    When the audit runs
    Then it passes

  Scenario: Partial completion raises StreamingIncompleteError
    Given an LLM node whose upstream stream errors before the terminal token
    When StructuredGenerator.generate runs
    Then it raises StreamingIncompleteError(finish_reason=FinishReason.PARTIAL_ERROR, partial_tokens=N>0)
    And the post-flight chain converts it to REJECT(reason="generation_incomplete")
    And no validators or policy checks run against partial output
    And no StructuredResult is produced

  Scenario: Tool-call loop completes via continuation
    Given an LLM stream returns finish_reason=FinishReason.TERMINAL_TOOL with a tool_use block
    When the StructuredGenerator dispatches the tool, appends the result, and resumes the stream
    And the resumed stream reaches finish_reason=FinishReason.TERMINAL_STOP within tool_loop_budget rounds
    Then a single StructuredResult is returned with the validated output schema instance

  Scenario: Tool-call loop exhausts budget
    Given a StructuredGenerator with tool_loop_budget=2
    And the LLM emits TERMINAL_TOOL on rounds 1, 2, and 3
    When the generator processes the third TERMINAL_TOOL
    Then it raises ToolLoopExhaustedError
    And the post-flight chain converts to REJECT(reason="tool_loop_exhausted")

  Scenario: Structured-generate span emits usage attrs
    Given a StructuredGenerator completes a successful generation
    Then the gen_ai.generate.structured span carries non-null gen_ai.request.model, gen_ai.usage.input_tokens, gen_ai.usage.output_tokens, gen_ai.response.finish_reason

  Scenario: Chain timeout triggers retry-with-hints (not REJECT)
    Given a chain-level timeout fires during agent.run on attempt_idx=1
    And node.retry_budget == 2
    When the executor handles the timeout
    Then the upstream LLM stream is cancelled
    And consumed input+output tokens are charged to task.budget_remaining
    And the post-flight emits RECOVER(RETRY_WITH_HINTS, reason="agent:timeout")
    And no StructuredResult is produced (Inv 11/12 same path)
    And on retry exhaustion (attempt_idx == retry_budget), the chain escalates to HALT(reason="agent:timeout_exhausted")

  Scenario: Parallel tool calls — all dispatched and verified in one round
    Given an LLM stream returns finish_reason=FinishReason.TERMINAL_TOOL with three tool_use blocks [t1, t2, t3]
    And BlueprintRequest.tool_loop_budget == 2
    When the generator dispatches every tool_use block in provider-emitted order
    Then services.tool_output_verifier.verify is invoked once per produced ToolCallOutput
    And the resumed stream observes three tool_result envelopes with matched tool_call_id
    And tool_loop_budget consumed == 1 (round-counted, not call-counted)

  Scenario: Parallel tool-call cap rejects on >MAX_PARALLEL_TOOL_CALLS
    Given an LLM stream returns finish_reason=FinishReason.TERMINAL_TOOL with 9 tool_use blocks
    And SPEC-00 MAX_PARALLEL_TOOL_CALLS == 8
    When the generator inspects the turn
    Then it raises StreamingIncompleteError(finish_reason=FinishReason.PARTIAL_ERROR)
    And no tool dispatches occur

  Scenario: Intra-loop tool-output verifier blocks fabrication
    Given a TERMINAL_TOOL turn produces a ToolCallOutput whose citations are not members of request.grounding_refs
    When services.tool_output_verifier.verify returns verified=False
    Then the generator raises ToolLoopFabricationError before resuming the stream
    And the post-flight chain converts to RECOVER(RETRY_WITH_HINTS, reason="tool_unverified_in_loop")
    And the unverified output is NEVER fed back into the LLM context

  Scenario: Tool-loop generation budget is bounded across rounds
    Given node.budget.generation_tokens == 1000 and tool_loop_budget == 3
    And rounds 1 and 2 consume 400 + 400 == 800 output tokens
    When round 3 begins
    Then the generator requests max_tokens == max(0, 1000 - 800) == 200 on the resumed stream
    And total output across all rounds SHALL NOT exceed 1000 tokens
    And on cumulative exhaustion the generator raises StreamingIncompleteError(finish_reason=FinishReason.PARTIAL_LENGTH)

  Scenario: Adapter normalizes Anthropic pause_turn to PARTIAL_ERROR
    Given the Anthropic adapter receives finish_reason="pause_turn"
    When it maps to FinishReason
    Then the result is FinishReason.PARTIAL_ERROR
    And no TERMINAL_* mapping is produced
    And the gen_ai.generate.structured span carries finish_reason="partial_error"

  Scenario: Adapter rejects unknown finish_reason as PARTIAL_ERROR
    Given an adapter receives a null or unrecognized provider finish_reason
    When it maps to FinishReason
    Then the result is FinishReason.PARTIAL_ERROR
    And the adapter emits log event "finish_reason.unmapped" with provider and native_value
    And no TERMINAL_* mapping is produced

  Scenario: Partial completion still emits gen_ai.usage span attrs
    Given a StructuredGenerator raises StreamingIncompleteError(finish_reason=FinishReason.PARTIAL_LENGTH)
    Then the gen_ai.generate.structured span carries non-null gen_ai.usage.input_tokens and gen_ai.usage.output_tokens reflecting the partial token count
    And gen_ai.response.finish_reason == "partial_length"
```

## 5. Out of Scope

- Blueprint authoring UI / DSL.
- Auto-blueprint synthesis from prose (handled by MetaSynthesizer in SPEC-06).
- Per-tenant blueprint overrides — config layer.
- Streaming structured generation (deferred per SPEC-00 §5).

## 6. Dependencies

- SPEC-01 (interceptor protocol)
- SPEC-02 (PullInterceptor populates `ctx.surfaced_sources` *before* BlueprintInterceptor runs — chain order is canonical)
- `blueprint/`, `generation/`
- `pydantic` (output_schema validation)

## 7. Correctness Properties

### Property 1: LLM gating
*For any* node with `is_llm_node == True`, the chain has resolved a Blueprint
and produced a `BlueprintRequest` before `agent.run` is invoked. Non-LLM nodes
pass through.

**Validates: §3 Invariants 1, 2 / §4 "LLM node without Blueprint is rejected", "Non-LLM node bypasses Blueprint"**

### Property 2: Schema conformance
*For any* StructuredResult with non-None output_schema, `result.output` is an
instance of that schema and passes its validators.

**Validates: §3 Invariant 6 / §4 "Structured output validated"**

### Property 3: Citation membership at generation
*For any* StructuredResult, `set(cited_evidence_refs) ⊆ set(request.grounding_refs)`.
This is the same membership predicate SPEC-05 cite-or-fail enforces; drift
between the two is a contract bug.

**Validates: §3 Invariant 9 / §4 "Citation filtered to grounding_refs at generator boundary" / SPEC-05 Property 1**

### Property 4: Provenance presence
*For every* StructuredResult, `blueprint_id` and `blueprint_version` are
populated.

**Validates: §3 Invariant 5 / §4 "Provenance recorded"**

### Property 5: Structural determinism
*For any* identical (Blueprint, goal, entities, ctx.surfaced_sources), two
constructions of `BlueprintRequest` are byte-identical under canonical
serialization (sorted-key JSON).

**Validates: §3 Invariant 4 / §4 "Structural determinism under same inputs"**

## 8. Eval Criteria

All evaluators in this table are eval_kind=`guardian` unless explicitly marked `online` (per SPEC-05 Inv 20).

| Evaluator | Node | Mode | Threshold | Method | Pinned |
|---|---|---|---|---|---|
| BlueprintResolutionEvaluator | every LLM node | GATE | resolved == true | deterministic | n/a |
| SchemaConformanceEvaluator | nodes with output_schema | GATE | validation_errors == 0 | deterministic | n/a |
| PolicyAdherenceEvaluator | every generative node | GATE | violations == 0 | hybrid | LLM judge prompt `prompts/policy_judge_v1.md`, model `claude-haiku-4-5@2026-04-12`, temp=0 |
| BlueprintEffectivenessEvaluator | per-blueprint cohort | OBSERVE | quality_score ≥ baseline from `cemaf/data/eval_pins/blueprint_baselines_vN.json` (versioned snapshot, refreshed only by explicit PR; absolute floor 0.6 if no entry) | LLM judge | judge `claude-haiku-4-5@2026-04-12` (cross-family from default agent per SPEC-05 Inv 23) temp=0, prompt `prompts/blueprint_quality_v1.md` |

Baselines and prompts are versioned artifacts under `cemaf/data/eval_pins/`.

## 9. Observability Contract

- **Span**: `gen_ai.blueprint.resolve` — `blueprint.id`, `blueprint.version`, `entities.count`, `policies.count`, `grounding_refs.count`
- **Span**: `gen_ai.generate.structured` — `blueprint.id`, `output_schema`, `validation.passed`, `policy.violations`, `gen_ai.request.model`, `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, `gen_ai.response.finish_reason`
- **Log events**: `blueprint.not_resolved`, `blueprint.policy_violation`, `blueprint.schema_failed`, `blueprint.citation_dropped`
- **Metrics** (per SPEC-00 §9 cardinality — `blueprint_id` and `version` are bounded by the registry. Hard cap: ≤200 distinct (id,version) pairs; **registry size >200 at startup SHALL be a startup error** (parity with SPEC-00 §9 evaluator-label rule), forcing the swap to `blueprint_kind` enum before runtime — no metric explosion possible): `cemaf_blueprint_resolutions_total{blueprint_id,version}` (cap-enforced ≤200), `cemaf_blueprint_policy_violations_total` (no labels), `cemaf_blueprint_schema_failures_total` (no labels), `cemaf_blueprint_duration_seconds` (histogram, no labels)

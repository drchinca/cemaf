---
title: Blueprint as LLM Input
spec_id: SPEC-03
status: Draft
last_reviewed: 2026-05-26
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

```python
from typing import Protocol, runtime_checkable
from dataclasses import dataclass, field
from pydantic import BaseModel

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
class BlueprintRequest:
    """The structured LLM request derived from a Blueprint."""
    blueprint_id: BlueprintID
    blueprint_version: str
    goal: GoalSpec
    entities: tuple[EntityRef, ...]                  # informational — SPEC-02 PullInterceptor extracts entities from goal.text; BlueprintRequest.entities does NOT feed retrieval. This is intentional (Pull runs at PRE position 2, Blueprint at position 3); declare any required entities in goal.metadata for upstream extraction.
    style: StyleSpec
    policies: tuple[PolicySpec, ...]
    output_schema: type[BaseModel] | None           # see "Grounding annotation policy" below
    grounding_refs: tuple[Citation, ...]            # derived from ctx.surfaced_sources
    policy_retry_budget: int = 2                     # consumed by StructuredGenerator (Inv 7)
    metadata: dict[str, str] = field(default_factory=dict)

@dataclass(frozen=True, slots=True)
class StructuredResult:
    output: BaseModel | None                        # validated when output_schema is set
    raw_text: str
    cited_evidence_refs: tuple[Citation, ...]
    blueprint_id: BlueprintID
    blueprint_version: str

@runtime_checkable
class BlueprintLibrary(Protocol):
    def get(self, blueprint_id: BlueprintID, *, version: str | None = None) -> Blueprint: ...
    def list_for_capability(self, capability: str) -> tuple[Blueprint, ...]: ...
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
    async def generate(self, *, request: BlueprintRequest, client: LLMClient) -> StructuredResult: ...
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
| `id`, `status`, `category`, `kind`, `confidence`, `score`, enums, labels, ids, foreign keys, structural metadata | NOT annotated (these are not Claims) |

The spec audit (SPEC-00 §6 Spec Audit) SHALL fail the build when any
registered blueprint has an `output_schema` whose field set contains a
free-text factual field (heuristic: `str` typed, `max_length` ≥ 64 or
unbounded, name ∉ structural-metadata allow-list) WITHOUT
`grounding_required=True`. Override requires an explicit waiver entry in
`cemaf/data/eval_pins/grounding_audit_waivers.json`.

## 3. Invariants (DbC)

1. `WHEN node.is_llm_node == True AND BlueprintLibrary.resolve_for_node returns None, THE BlueprintInterceptor SHALL emit REJECT(reason="no_blueprint_resolved").`
2. `WHEN node.is_llm_node == False, THE BlueprintInterceptor SHALL emit ACCEPT with no enrichment.`
3. `BlueprintRequest.grounding_refs SHALL equal tuple(c.citation for c in ctx.surfaced_sources) at the moment BlueprintInterceptor runs.`
4. `THE BlueprintRequest SHALL be structurally equal under canonical serialization given the same Blueprint, goal, entities, and ctx.surfaced_sources (replay-deterministic).`
5. `Every StructuredResult SHALL carry the source blueprint_id and version (provenance).`
6. `IF blueprint declares output_schema, THEN StructuredResult.output SHALL be an instance of that schema and pass its validators; failure → PostflightDecision determined by node.schema_failure_policy (SPEC-00 §2 SchemaFailurePolicy enum, default RECOVER).`
7. `Policies in the Blueprint (MUST / MUST_NOT) SHALL be enforced by the StructuredGenerator before returning the result; violations trigger re-generation up to BlueprintRequest.policy_retry_budget (default 2). On exhaustion the generator SHALL raise PolicyExhaustedError; the post-flight chain converts it to REJECT(reason="policy_exhausted").`
8. `BlueprintLibrary SHALL return immutable Blueprint instances; mutation requires a new version (semver bump).`
9. `THE generator SHALL filter cited_evidence_refs to ⊆ BlueprintRequest.grounding_refs before returning the StructuredResult — i.e., it SHALL NOT introduce non-member Citations. SPEC-05 cite-or-fail enforces the same membership predicate at post-flight against ctx.surfaced_sources (which equals grounding_refs at the moment BlueprintInterceptor ran, per Inv 3) — the two checks are redundant by design (defense in depth).`
10. `IF a registered blueprint declares an output_schema with a free-text factual field (str-typed, max_length ≥ 64 or unbounded, name ∉ structural-metadata allow-list per §2 "Grounding annotation policy") AND no field on that schema carries grounding_required=True, THEN the SPEC-00 §6 Spec Audit SHALL fail the build. Override requires a waiver entry in cemaf/data/eval_pins/grounding_audit_waivers.json with a justification string.`

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
    Given identical Blueprint, goal, entities, ctx.surfaced_sources
    When BlueprintRequest is built twice
    Then the canonical serialization (JSON, sorted keys) of both is byte-identical

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

**Validates: §3 Invariants 1, 2 / §4 "LLM node without Blueprint is rejected", "Non-LLM node bypasses"**

### Property 2: Schema conformance
*For any* StructuredResult with non-None output_schema, `result.output` is an
instance of that schema and passes its validators.

**Validates: §3 Invariant 6 / §4 "Structured output validated"**

### Property 3: Citation membership at generation
*For any* StructuredResult, `set(cited_evidence_refs) ⊆ set(request.grounding_refs)`.
This is the same membership predicate SPEC-05 cite-or-fail enforces; drift
between the two is a contract bug.

**Validates: §3 Invariant 9 / §4 "Citation drop on non-member" / SPEC-05 Property 1**

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

| Evaluator | Node | Mode | Threshold | Method | Pinned |
|---|---|---|---|---|---|
| BlueprintResolutionEvaluator | every LLM node | GATE | resolved == true | deterministic | n/a |
| SchemaConformanceEvaluator | nodes with output_schema | GATE | validation_errors == 0 | deterministic | n/a |
| PolicyAdherenceEvaluator | every generative node | GATE | violations == 0 | hybrid | LLM judge prompt `prompts/policy_judge_v1.md`, model `claude-haiku-4-5`, temp=0 |
| BlueprintEffectivenessEvaluator | per-blueprint cohort | OBSERVE | quality_score ≥ baseline from `cemaf/data/eval_pins/blueprint_baselines_vN.json` (versioned snapshot, refreshed only by explicit PR; absolute floor 0.6 if no entry) | LLM judge | judge `claude-sonnet-4-6` temp=0, prompt `prompts/blueprint_quality_v1.md` |

Baselines and prompts are versioned artifacts under `cemaf/data/eval_pins/`.

## 9. Observability Contract

- **Span**: `gen_ai.blueprint.resolve` — `blueprint.id`, `blueprint.version`, `entities.count`, `policies.count`, `grounding_refs.count`
- **Span**: `gen_ai.generate.structured` — `blueprint.id`, `output_schema`, `validation.passed`, `policy.violations`
- **Log events**: `blueprint.not_resolved`, `blueprint.policy_violation`, `blueprint.schema_failed`, `blueprint.citation_dropped`
- **Metrics** (per SPEC-00 §9 cardinality — `blueprint_id` and `version` are bounded by the registry; if the registry exceeds 200 distinct (id,version) pairs in a deployment, swap to `blueprint_kind` enum): `cemaf_blueprint_resolutions_total{blueprint_id,version}` (cap: ≤200 pairs), `cemaf_blueprint_policy_violations_total` (no labels), `cemaf_blueprint_schema_failures_total` (no labels), `cemaf_blueprint_duration_seconds` (histogram, no labels)

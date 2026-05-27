---
title: Guardian Mesh — legitimacy, cite-or-fail, tool-verify, eval-halt, goal-completion
spec_id: SPEC-05
status: Reviewed
last_reviewed: 2026-05-27
owner: drchinca
parent: SPEC-00 — Enterprise Context Brain
depends_on: SPEC-01, SPEC-02, SPEC-03, SPEC-04
budget_override: "≤700 lines (scenarios ≤25) — six guardians + §10 user-facing copy table + §10 audit-gate scope boundary + judge prompt-injection isolation (Inv 16) + judge token budget routing (Inv 17) + attempt_kind rolling-window scoping (Inv 18) is the integrity layer's single contract; splitting fragments the cross-spec coverage scenario (rules/context-engineering.md permits override with justification)"
---

# SPEC-05: Guardian Mesh

> The integrity layer. Auto-injects six guardians into the interceptor pipeline:
> **legitimacy** (pre), **cite-or-fail** (post), **tool-verify** (post),
> **online-eval** (post), **goal-completion** (post-on-terminal),
> **audit** (both). Together they enforce the **low-to-zero hallucination,
> total awareness, audited-and-assertive** property of the Context Brain.

## 1. Context

`evals/`, `citation/`, `moderation/`, `audit/` already exist. None are wired
into the default chain. This spec concretizes six guardian interceptors that
ship in the default chain, each backed by an existing CEMAF subsystem, and
**defines the Claim extraction algorithm and surfaced-sources membership set**
that make cite-or-fail testable.

| Guardian | Phase | Backing |
|---|---|---|
| LegitimacyInterceptor | PRE (first) | `moderation/ModerationPipeline` + new `AuthorizationPolicy` |
| CiteOrFailInterceptor | POST (first) | `citation/`, `evals/grounding.py`, new `ClaimExtractor` |
| ToolOutputVerifierInterceptor | POST (second) | new `ToolOutputVerifier` (LLM-judge with pinned prompt + heuristic checks) |
| OnlineEvalInterceptor | POST | `evals/online.py`, `evals/police.py` |
| GoalCompletionInterceptor | POST (terminal node only) | `evals/judge.py` extended; pinned prompt |
| AuditInterceptor | BOTH (last) | `audit/` |

Recovery is wired via `RecoveryStrategy` (SPEC-01); a guardian rejection can
re-route to a fix-it agent or trigger SPEC-06 meta dispatch.

### ChainProfile selection

`RuntimeServices.chain_profile` selects which guardians activate:

| Profile | PRE order | POST order |
|---|---|---|
| `DEFAULT` | legitimacy → pull → blueprint → task_inject → audit | cite_or_fail → tool_verify → online_eval → goal_completion → audit |
| `RECOVERY` | legitimacy → pull → blueprint → task_inject → audit | cite_or_fail → tool_verify → audit |

`DAGExecutor.run(*, chain_profile=ChainProfile.DEFAULT)` is the default;
`MetaDispatcher` (SPEC-06) overrides to `RECOVERY` for sub-DAG runs.
Guardians are auto-injected at bootstrap; opting out is explicit.

## 2. Interface Contract (MDE)

Common types in SPEC-00 §2 (`Citation`, `CiteableChunk`, `AgentResult`, `DAGNode`).

### Claim — the unit of grounding

`Claim` is defined in SPEC-00 §2 (hoisted there so `AgentResult.unverified_claims`
types without a layer inversion). SPEC-05 owns the extraction algorithms and
policy below; the dataclass shape lives in the umbrella.

```python
# Claim is defined in SPEC-00 §2 (single source of truth). At implementation:
#   from cemaf.core.types import Claim
# This spec owns the extraction protocol + grounding-annotation policy below.

@runtime_checkable
class ClaimExtractor(Protocol):
    """Deterministic given a fixed implementation. Two impls in v1:
       - SchemaFieldClaimExtractor: ONLY fields explicitly annotated with
         `Field(json_schema_extra={"grounding_required": True})` on the
         Pydantic output schema become Claims. Non-annotated fields are NOT
         Claims (avoids false-positive grounding on labels, ids, enums, and
         other non-factual fields). When the schema declares zero
         grounding-required fields, the extractor returns ().
       - SentenceClaimExtractor: segment raw_text via the pinned rules in
         `evals/claim_extractor.py::SENTENCE_RULES_V1`:
           * sentence boundary: `(?<=[.!?])\s+(?=[A-Z])`
           * hedge phrases (skipped, not Claims): {"i think", "perhaps",
             "maybe", "it is possible that", "likely", "probably", "i'm not
             sure", "could be"} (case-insensitive prefix match)
           * factual: any remaining sentence with ≥1 token whose
             POS-tag-equivalent is NOUN, PROPN, NUM, or DATE per the
             `en_core_web_sm` tagger pinned in `cemaf/data/eval_pins/`.
       Default selection: SchemaFieldClaimExtractor when output_schema is set
       AND ≥1 field is `grounding_required=True`; otherwise
       SentenceClaimExtractor over `raw_text`. Pluggable via
       RuntimeServices.claim_extractor.
    """
    def extract(self, *, result: AgentResult) -> tuple[Claim, ...]: ...
```

### Legitimacy

```python
@runtime_checkable
class AuthorizationPolicy(Protocol):
    async def authorize(self, *, node: DAGNode, task: TaskContext,
                        services: RuntimeServices) -> AuthorizationResult: ...

@dataclass(frozen=True, slots=True)
class AuthorizationResult:
    authorized: bool
    denied_scope: str | None = None
    reason: str | None = None

class LegitimacyInterceptor(NodeInterceptor):
    """PRE position 1.
    Composition:
      1. AuthorizationPolicy.authorize() — scope/role check.
      2. ModerationPipeline.preflight(goal.text) — content safety on the request.
      3. REJECT on either failure with reason "out_of_scope:<s>" or "moderation:<rule>".
    """
    interceptor_id = "legitimacy"
    phase = InterceptorPhase.PRE
```

### Cite-or-Fail (membership-only, deterministic)

```python
class CiteOrFailInterceptor(NodeInterceptor):
    """POST position 1.
    Algorithm (deterministic):
      surfaced = {c.citation for c in ctx.surfaced_sources}
      claims   = ClaimExtractor.extract(result=result)
      cited    = set(result.cited_evidence_refs)
      ungrounded = tuple(c for c in claims if c.citations == ())

      # Decision kinds use SPEC-01 PostflightKind grammar: REJECT carries no
      # recovery_strategy; RECOVER(strategy=RETRY_WITH_HINTS) does. Budget
      # escalation is enforced via Inv 15 below — when retry budget is
      # exhausted the interceptor SHALL emit HALT(scope=TASK) instead of
      # another RECOVER, closing the infinite-loop hazard.
      #
      # Membership check applies regardless of grounding policy.
      if cited - surfaced:                  -> RECOVER(RETRY_WITH_HINTS,
                                                       reason="non_member_citation",
                                                       hints=[fix=cite from surfaced])

      # Grounding-policy branching (SPEC-00 §2 GroundingPolicy):
      if node.grounding == REQUIRED and ungrounded:
                                            -> RECOVER(RETRY_WITH_HINTS,
                                                       reason="ungrounded_claim",
                                                       hints=[fix=cite source X for claim Y])
      if node.grounding == BEST_EFFORT and ungrounded:
          # ACCEPT. The chain returns the ungrounded tuple on the
          # PostflightDecision.derived_unverified_claims; per SPEC-01 Inv 6
          # the Executor constructs a NEW AgentResult with
          # `unverified_claims = ungrounded` (the agent-emitted AgentResult
          # MUST have unverified_claims == () — see SPEC-00 §2 ownership note
          # below; agents do not self-flag, the chain does) and persists it as
          # NodeOutcome.result. The agent-emitted AgentResult is unchanged in
          # audit storage. Downstream consumers and user-facing copy SHALL
          # annotate these claims as "[unverified]"; per Inv 14 they are NOT
          # promoted into any downstream node's ctx.surfaced_sources.
                                            -> ACCEPT(derived_unverified_claims=ungrounded)
      # OPTIONAL and DISABLED: no claim-level enforcement.
    """
    interceptor_id = "cite_or_fail"
    phase = InterceptorPhase.POST
```

### Tool-Output Verifier (closes hallucination at the tool layer)

```python
@runtime_checkable
class ToolOutputVerifier(Protocol):
    """Inspects tool results consumed by the next node for fabrication.
    Hybrid: deterministic schema/format check + pinned LLM-judge for plausibility.
    """
    async def verify(self, *, tool_outputs: tuple[ToolCallOutput, ...],
                     surfaced: tuple[CiteableChunk, ...]) -> VerifyResult: ...

@dataclass(frozen=True, slots=True)
class VerifyResult:
    verified: bool
    unverified_outputs: tuple[ToolCallOutput, ...] = ()
    reason: str | None = None

class ToolOutputVerifierInterceptor(NodeInterceptor):
    """POST position 2. Active when `result.tool_calls` is non-empty,
    regardless of `consumed_by_node` value. Terminal-node tool outputs are
    also verified — the agent's `raw_text` may ingest tool output and emit
    it as the final answer; skipping verification at terminal nodes opens
    a citation-laundering path closed by this rule. Timing: at post-flight
    assembly time the executor inspects static DAG successors of `node`,
    builds a NEW AgentResult whose `tool_calls` tuple has `consumed_by_node`
    populated, and passes that to the post chain. The original AgentResult
    is not mutated (frozen-dataclass invariant preserved); the interceptor
    never touches dag.edges directly.

    Deterministic schema check: each ToolCallOutput.output is validated
    against the registered ToolSchema.output_schema; a schema-mismatch
    contributes one entry to VerifyResult.unverified_outputs with
    reason="schema_mismatch".

    LLM-judge plausibility check (pinned `prompts/tool_verify_v1.md`,
    `claude-haiku-4-5`, temp=0) runs only on outputs that pass schema
    validation, scoring fabrication likelihood.

    RECOVER(RETRY_WITH_HINTS, reason="tool_unverified") on failure; budget
    exhaustion escalates to HALT(scope=TASK) per Inv 15.
    """
    interceptor_id = "tool_verify"
    phase = InterceptorPhase.POST
```

### Online eval + halt

```python
class AlertLevel(Enum):
    OK    = "ok"      # rolling-window mean ≥ baseline_mean − 1·σ
    WARN  = "warn"    # within (baseline_mean − 2.5·σ, baseline_mean − 1·σ)
    HALT  = "halt"    # rolling-window z-score ≤ −2.5 OR three consecutive WARN scores

class OnlineEvalInterceptor(NodeInterceptor):
    """POST. Runs configured evaluators in GATE mode synchronously, records
    scores into QualityPolice. Returns HALT(scope=DAG, reason="quality_halt")
    when QualityPolice.alert_level == AlertLevel.HALT.

    Per-node binding: the executor reads `node.online_evaluators: tuple[str, ...]`
    (declared on DAGNode at design time, default ()); each id resolves through
    `services.online_eval_pipeline.get(id)`. Empty tuple → no synchronous eval.
    Threshold mapping is the single source of truth in AlertLevel above; the
    rolling-window N=30 + z=−2.5 baseline is pinned at SPEC-05 §8 row
    "QualityTrendMonitor" and SPEC-00 §8 (read-once at executor start).

    Cassette payload SHALL carry (level, score, attempt_idx, attempt_kind)
    where attempt_idx is the get_retry(task.retry_ledger, node.id) value at
    decision time (0 for the first dispatch, 1 for first RECOVER re-dispatch,
    ...). attempt_kind ∈ {"first", "retry_after_hints", "retry_after_meta"}
    distinguishes:
      - "first"               : attempt_idx == 0
      - "retry_after_hints"   : attempt_idx > 0, prior RECOVER was
                                RETRY_WITH_HINTS or RETRY_FRESH
      - "retry_after_meta"    : attempt_idx > 0, prior RECOVER was
                                INVOKE_META_ARCHITECT (SPEC-06 path)
    """
    interceptor_id = "online_eval"
    phase = InterceptorPhase.POST
```

### Goal completion

```python
@runtime_checkable
class GoalCompletionEvaluator(Protocol):
    async def evaluate(self, *, task: TaskContext,
                       outputs: tuple[AgentResult, ...],
                       surfaced_sources: tuple[CiteableChunk, ...]
                       ) -> GoalCompletionResult:
        """surfaced_sources is the membership set the judge MUST cite from
        (Inv 12). The interceptor passes ctx.surfaced_sources of the terminal
        node — the judge is structurally barred from inventing citations.
        """

@dataclass(frozen=True, slots=True)
class GoalCompletionResult:
    achieved: bool
    confidence: Confidence
    missing_criteria: tuple[str, ...] = ()         # ≤10 entries; surplus dropped at judge boundary
    reason: str | None = None
    judge_citations: tuple[Citation, ...] = ()       # ≤10 entries; judge cites surfaced sources for its reasoning. Both tuples are user-facing copy + audit payload, capped to bound prompt + UI growth.

class GoalCompletionInterceptor(NodeInterceptor):
    """POST, runs only when node.is_terminal == True.
    Decision policy (uses get_retry(task.retry_ledger, node.id), per SPEC-04 Inv 10):
      - achieved AND confidence ≥ 0.8                                              → ACCEPT
      - !achieved AND get_retry(task.retry_ledger, node.id) < node.retry_budget    → RECOVER(INVOKE_META_ARCHITECT)
      - !achieved AND get_retry(task.retry_ledger, node.id) ≥ node.retry_budget    → HALT(scope=TASK, reason="goal_unreachable")
    """
    interceptor_id = "goal_completion"
    phase = InterceptorPhase.POST
```

### Audit

```python
class AuditInterceptor(NodeInterceptor):
    """phase=BOTH; PRE position last (after task_inject); POST position last (after goal_completion).
    Emits one AuditEntry per phase invocation that runs.
    """
    interceptor_id = "audit"
    phase = InterceptorPhase.BOTH
```

## 3. Invariants (DbC)

1. `WHEN AuthorizationPolicy.authorize returns authorized=False, THE LegitimacyInterceptor SHALL emit REJECT(reason="out_of_scope:<denied_scope>") and the agent SHALL NOT be invoked.`
2. `WHEN any element of result.cited_evidence_refs ∉ {c.citation for c in ctx.surfaced_sources}, THE CiteOrFailInterceptor SHALL emit RECOVER(RETRY_WITH_HINTS, reason="non_member_citation") subject to Inv 15 budget escalation (which converts RECOVER → HALT once the retry ledger reaches node.retry_budget).`
3. `Grounding-policy decision matrix for ungrounded Claims. Four sub-rules, each independently testable:
   - 3a. WHEN node.grounding == REQUIRED AND ClaimExtractor.extract yields a Claim with citations==(), THE CiteOrFailInterceptor SHALL emit RECOVER(RETRY_WITH_HINTS, reason="ungrounded_claim") subject to Inv 15 budget escalation.
   - 3b. WHEN node.grounding == BEST_EFFORT AND ungrounded claims exist, THE CiteOrFailInterceptor SHALL ACCEPT and PostflightDecision.derived_unverified_claims SHALL include those claims (executor merges per SPEC-01 Inv 6d); user-facing surfaces render them as "[unverified]".
   - 3c. WHEN node.grounding == OPTIONAL, ungrounded claims SHALL NOT trigger any decision change.
   - 3d. WHEN node.grounding == DISABLED, ClaimExtractor SHALL NOT be invoked at all.`
4. `WHEN ToolOutputVerifier.verify returns verified=False, THE ToolOutputVerifierInterceptor SHALL emit RECOVER(RETRY_WITH_HINTS, reason="tool_unverified") subject to Inv 15 budget escalation.`
5. `WHEN OnlineEvalInterceptor records a score that triggers QualityPolice HALT, THE PostflightDecision SHALL be HALT(scope=DAG).`
6. `WHEN chain_profile == ChainProfile.DEFAULT, THE GoalCompletionInterceptor SHALL run iff node.is_terminal == True. Under ChainProfile.RECOVERY the interceptor is absent from the chain (per §1 ChainProfile table and SPEC-00 RECOVERY_POST_ORDER) — terminal recovery sub-DAG nodes therefore SHALL NOT trigger goal completion evaluation.`
7. `WHEN GoalCompletionResult.achieved == False AND get_retry(task.retry_ledger, node.id) < node.retry_budget, THE PostflightDecision SHALL be RECOVER(INVOKE_META_ARCHITECT). Otherwise HALT(scope=TASK).`
8. `THE AuditInterceptor SHALL emit one AuditEntry per phase invocation, scoped per ATTEMPT (one PRE→optional EXECUTE→POST pass). A SPEC-06 recovery sub-DAG is a separate run with its own entries linked via parent_correlation_id (SPEC-06 Inv 6); the parent's next attempt begins after RECOVER + increment_retry. Per-attempt completeness: ACCEPTED end-to-end → 2 entries; post-flight REJECT/RECOVER/HALT → 2 entries; pre-flight REJECT → 1 entry (audit runs last in PRE and is exempt from SPEC-01 Inv 5 short-circuit).`
9. `Recovery via RETRY_WITH_HINTS SHALL pass RecoveryHint instances in goal.metadata["remediation"] to the re-dispatched agent (per SPEC-01 Inv 10).`
10. `Guardian interceptors SHALL be auto-injected at bootstrap when the corresponding RuntimeServices.* field is non-None; opting out requires an explicit ChainConfig override. EXCEPTION: THE AuditInterceptor SHALL be auto-injected unconditionally — it has no backing service flag, so per-attempt audit completeness (Inv 8) and §9 telemetry hold regardless of RuntimeServices configuration. When no AuditLog backing is configured, AuditInterceptor SHALL bind to an in-memory NullSafeAuditLog default (defined here, not in SPEC-00 §6 — that is the build-time spec-audit gate, a separate concern).`
11. `Citation membership check (Inv 2) SHALL be replay-safe: identical surfaced_sources + identical cited_evidence_refs yield identical decisions.`
12. `WHEN node.grounding == REQUIRED at the terminal node, THE GoalCompletionEvaluator SHALL self-cite — judge_citations SHALL be a non-empty subset of {c.citation for c in ctx.surfaced_sources at terminal node}; failure → REJECT the judge result and treat as achieved=False with confidence=0. WHERE grounding ∈ {OPTIONAL, DISABLED}, judge_citations MAY be empty.`
13. `THE AuditInterceptor SHALL NOT be subject to the SPEC-01 Inv 5 short-circuit — its PRE entry SHALL be emitted even when an earlier PRE interceptor REJECTED (Inv 8 above is the per-attempt completeness contract that depends on this).`
14. `THE Executor SHALL NOT include AgentResult.unverified_claims in any downstream node's ctx.surfaced_sources — unverified_claims have no Citation and SHALL appear only in the originating AgentResult and in user-facing copy (rendered as "[unverified]"). Promotion of an unverified claim into a citable surface SHALL require a fresh PullInterceptor pass that produces a CiteableChunk with a real Citation.`
15. `Retry budget escalation (closes infinite-loop hazard): WHEN CiteOrFailInterceptor or ToolOutputVerifierInterceptor would emit RECOVER(RETRY_WITH_HINTS), THE interceptor SHALL first check get_retry(task.retry_ledger, node.id). If the value < node.retry_budget, emit RECOVER (executor calls increment_retry per SPEC-04 Inv 11). If the value ≥ node.retry_budget, emit HALT(scope=TASK, reason="<original_reason>_exhausted") with the original reason string suffixed "_exhausted" (e.g. "non_member_citation_exhausted", "ungrounded_claim_exhausted", "tool_unverified_exhausted"). SPEC-05 §10 SHALL carry one user-copy row per *_exhausted reason.`
16. `LLM-judge prompt-injection isolation. Every judge that consumes adversarial-controlled text (AgentResult.raw_text, AgentResult.output, ToolCallOutput.output, CiteableChunk.content) SHALL: (a) wrap untrusted segments in delimited envelopes — judge prompts use canonical XML-like markers <untrusted-input id="..."> ... </untrusted-input> with content-hash echo verification; (b) pass through services.judge_input_sanitizer (a deterministic regex+heuristic stripper for known directive patterns: "ignore previous", "system:", "</untrusted-input>", base64-encoded directives); (c) include the sanitizer version in the cassette key (judge_input_projection_version per SPEC-00 §7). Judges that consume CiteableChunk.content SHALL NOT trust citation_id selection from inside untrusted segments — judge_citations SHALL be re-validated against ctx.surfaced_sources by the Executor before recording the GoalCompletionResult. Closes the cite-or-fail bypass where an attacker emits "achieved=true, judge_citations=[<real_id>]" inside their output. The untrusted-source list SHALL also include `goal.text` and every `goal.metadata['remediation'][i].detail` / `.suggested_action` string when present — these flow through the same XML envelope sanitization.`
17. `LLM-judge token budget. OnlineEvalInterceptor, GoalCompletionInterceptor, ToolOutputVerifierInterceptor, and BlueprintInterceptor's policy judge SHALL debit services.eval_budget — NOT task.budget_remaining (SPEC-00 §"RuntimeServices additions"). Per-judge cap = eval_budget.generation_tokens / max(1, services.online_eval_pipeline.size). On per-judge cap exceedance, judges SHALL truncate the prompt input projection by dropping lowest-priority CiteableChunks first (SPEC-02 Inv 11 sort) and emit "eval.judge_input_truncated{judge_id,dropped_chunks}". On hard exhaustion, judges SHALL return score=0, level="budget_exhausted" — counted as a non-passing observation in QualityPolice (NOT silently dropped).`
18. `OnlineEvalInterceptor rolling-window scoping (closes attempt mis-attribution): QualityPolice.record_score SHALL accept (node_id, score, attempt_kind) and bucket the rolling window separately by attempt_kind. The default N=30, z=−2.5 HALT trigger fires only on the "first" bucket; "retry_after_hints" and "retry_after_meta" maintain independent windows scored OBSERVE-only with separate metric labels (SPEC-05 §9 cemaf_eval_score{attempt_kind}). Mixed-bucket aggregation across attempt kinds is forbidden — prevents post-recovery scores from masking pre-recovery regressions.`
19. `THE QualityPolice rolling window SHALL be keyed by (node_id, attempt_kind, judge_id, prompt_template_version, model_id). Bumping any of {prompt_template_version, model_id} SHALL start a fresh window in OBSERVE mode for that key; window transitions back to GATE only after N samples (default 30) accumulate under the new pin. Mixed-regime samples SHALL NOT enter z-score baseline computation.`
20. `EVERY evaluator declared with mode=GATE in any §8 Eval Criteria table across the spec set SHALL be bound to every applicable LLM node in the registered DAG. bootstrap.create_executor SHALL emit StartupError(reason='gate_evaluator_unbound', evaluator_id=..., node_id=...) when an LLM node's online_evaluators tuple omits any GATE-mode evaluator whose node-pattern matches that node. Mode-flip from GATE to OBSERVE requires a spec amendment, never a missing tuple element.`

## 4. Acceptance Criteria (BDD)

```gherkin
Feature: Guardian mesh

  Scenario: Legitimacy denies an out-of-scope action
    Given an AuthorizationPolicy denying scope "kg.write"
    And a node attempting an out-of-scope operation
    When LegitimacyInterceptor runs
    Then PreflightDecision is REJECT with reason "out_of_scope:kg.write"
    And the agent is not invoked
    And one PRE AuditEntry is recorded

  Scenario: Legitimacy denies on moderation failure
    Given goal.text contains content blocked by ModerationPipeline rule "PII"
    When LegitimacyInterceptor runs
    Then PreflightDecision is REJECT with reason "moderation:PII"

  Scenario: Cite-or-fail recovers on non-member citation
    Given ctx.surfaced_sources Citations = {a, b, c}
    And result.cited_evidence_refs = {d}
    And get_retry(task.retry_ledger, node.id) < node.retry_budget
    When CiteOrFailInterceptor runs
    Then PostflightDecision is RECOVER(RETRY_WITH_HINTS, reason="non_member_citation")

  Scenario: Cite-or-fail recovers on ungrounded claim
    Given node.grounding == REQUIRED
    And SchemaFieldClaimExtractor extracts a Claim with citations==()
    And get_retry(task.retry_ledger, node.id) < node.retry_budget
    When CiteOrFailInterceptor runs
    Then PostflightDecision is RECOVER(RETRY_WITH_HINTS, reason="ungrounded_claim")

  Scenario: Cite-or-fail downgrades ungrounded claim under BEST_EFFORT
    Given node.grounding == BEST_EFFORT
    And ClaimExtractor extracts two Claims, one with citations==() and one cited from surfaced
    When CiteOrFailInterceptor runs
    Then PostflightDecision is ACCEPT
    And the persisted AgentResult.unverified_claims contains exactly the ungrounded Claim
    And the agent is not re-dispatched

  Scenario: Tool-output verifier catches fabricated tool result
    Given a tool output consumed by the next node
    And ToolOutputVerifier.verify returns verified=False with one unverified output
    And get_retry(task.retry_ledger, node.id) < node.retry_budget
    When ToolOutputVerifierInterceptor runs
    Then PostflightDecision is RECOVER(RETRY_WITH_HINTS, reason="tool_unverified")
    And recovery_hints reference the unverified output

  Scenario: Online eval triggers DAG halt
    Given QualityPolice configured with HALT threshold breached
    When OnlineEvalInterceptor records the next score
    Then it returns HALT(scope=DAG, reason="quality_halt")
    And the DAGExecutor stops dispatching new nodes
    And the Task transitions to HALTED

  Scenario: Goal completion first failure recovers
    Given a terminal node with node.retry_budget == 1
    And get_retry(task.retry_ledger, node.id) == 0
    And GoalCompletionResult.achieved == False
    When GoalCompletionInterceptor runs
    Then PostflightDecision is RECOVER(INVOKE_META_ARCHITECT)
    And the executor increments the retry ledger to 1 before the next attempt

  Scenario: Goal completion second failure halts
    Given a terminal node with node.retry_budget == 1
    And get_retry(task.retry_ledger, node.id) == 1 (incremented after the prior RECOVER)
    And GoalCompletionResult.achieved == False
    When GoalCompletionInterceptor runs
    Then PostflightDecision is HALT(scope=TASK, reason="goal_unreachable")

  Scenario: Goal-completion judge must self-cite
    Given GoalCompletionEvaluator returns judge_citations==()
    When GoalCompletionInterceptor processes the result
    Then the judge result is treated as achieved=False, confidence=0
    And PostflightDecision follows the !achieved branch (recover or halt)

  Scenario: Audit completeness — accepted node
    Given a node accepted end-to-end
    When the chain finishes
    Then exactly 2 AuditEntries are emitted (PRE and POST)

  Scenario: Audit completeness — pre-rejected node
    Given a node rejected in pre-flight
    When the chain finishes
    Then exactly 1 AuditEntry is emitted (PRE only)

  Scenario: Audit completeness — recover then accept (per attempt)
    Given a node whose first attempt RECOVERS in post-flight
    And whose second attempt is ACCEPTED end-to-end
    When the chain finishes both attempts
    Then exactly 4 AuditEntries are emitted (2 PRE + 2 POST across attempts)

  Scenario: Recovery hints reach the next attempt
    Given a CiteOrFail rejection with hint code "non_member_citation"
    When the agent is re-dispatched via RETRY_WITH_HINTS
    Then goal.metadata["remediation"] contains the hint code and suggested_action

  Scenario: Replay determinism — citation membership
    Given identical ctx.surfaced_sources and identical result.cited_evidence_refs
    When CiteOrFailInterceptor runs twice
    Then both PostflightDecisions are byte-identical (kind, reason, recovery_strategy)

  Scenario: Unverified claims are not promoted to downstream surfaced_sources
    Given node A produces AgentResult.unverified_claims=(c1,) under GroundingPolicy.BEST_EFFORT
    And node B is a downstream consumer of A's output
    When node B's PRE chain completes
    Then ctx.surfaced_sources at node B contains no CiteableChunk derived from c1
    And c1 appears only in A's persisted AgentResult and in user-facing copy as "[unverified]"

  Scenario: SchemaFieldClaimExtractor ignores non-annotated fields
    Given an output schema with one field annotated grounding_required=True and three unannotated fields
    And result.output populates all four fields with non-empty values
    When SchemaFieldClaimExtractor.extract runs
    Then exactly one Claim is returned, sourced from the annotated field

  Scenario: SchemaFieldClaimExtractor returns empty when no fields are annotated
    Given an output schema with zero grounding_required fields
    When SchemaFieldClaimExtractor.extract runs
    Then the result is the empty tuple
    And CiteOrFailInterceptor ACCEPTs regardless of grounding policy

  Scenario: Every emitted reason string maps to a §10 copy row
    Given the set R of reason strings any guardian (REJECT, RECOVER, or HALT) can emit in code
    When the §10 user-facing copy table is loaded
    Then every r in R matches a row key (with <scope>/<rule>/<class>/<id> placeholders matched by pattern)
    And every row in §10 is reachable from at least one emission site in code

  Scenario: Cite-or-fail RECOVER escalates to HALT on retry-budget exhaustion (Inv 15)
    Given a node N with retry_budget=2 and grounding=REQUIRED
    And the agent emits an ungrounded Claim on every attempt
    When attempt 1 runs CiteOrFailInterceptor
    Then PostflightDecision is RECOVER(RETRY_WITH_HINTS, reason="ungrounded_claim")
    And TaskRepository.increment_retry is called (ledger 0→1)
    When attempt 2 runs and the agent again emits an ungrounded Claim
    Then PostflightDecision is RECOVER (ledger 1→2)
    When attempt 3 runs and the agent again emits an ungrounded Claim
    Then get_retry(task.retry_ledger, N.id) ≥ N.retry_budget
    And PostflightDecision is HALT(scope=TASK, reason="ungrounded_claim_exhausted")
    And the §10 copy row for "ungrounded_claim_exhausted" exists

  Scenario: Cite-or-fail HALTs immediately when retry_budget == 0 (Inv 15 boundary)
    Given a node N with retry_budget=0 and grounding=REQUIRED
    And the agent emits an ungrounded Claim on attempt 1
    When CiteOrFailInterceptor runs
    Then get_retry(task.retry_ledger, N.id) == 0
    And 0 ≥ N.retry_budget holds
    And PostflightDecision is HALT(scope=TASK, reason="ungrounded_claim_exhausted")
    And TaskRepository.increment_retry is NOT called

  Scenario: Online-eval HALT triggered by AlertLevel.HALT
    Given an OnlineEvalInterceptor bound to evaluator E with rolling-window N=30
    And QualityPolice.alert_level transitions OK → WARN over the last 3 nodes
    When the next score yields rolling z-score ≤ −2.5
    Then QualityPolice.alert_level == AlertLevel.HALT
    And PostflightDecision is HALT(scope=DAG, reason="quality_halt")
    And the §10 copy row for "quality_halt" is rendered
```

## 5. Out of Scope

- Per-tenant policy authoring UI.
- ML-trained AuthorizationPolicy (defaults are rule-based).
- Adversarial prompt-injection defense beyond ModerationPipeline (separate spec).
- Cross-task policy reuse (policies are task-scoped this cycle).
- Mid-stream grounding (streaming deferred per SPEC-00 §5).

## 6. Dependencies

- SPEC-01 (chain + RecoveryStrategy)
- SPEC-02 (`ctx.surfaced_sources` is the membership set)
- SPEC-03 (`BlueprintRequest.grounding_refs` aligns with `ctx.surfaced_sources`)
- SPEC-04 (`task.retry_ledger`, `node.retry_budget`)
- `evals/online.py`, `evals/police.py`, `evals/grounding.py`, `evals/judge.py` (extend)
- `citation/`, `moderation/`, `audit/`
- `spacy==3.7.4` + `en_core_web_sm==3.7.1` (exact pins, mirrored in `pyproject.toml` + `cemaf/data/eval_pins/spacy_model_version.txt`) for `SentenceClaimExtractor`. Two CI runs MUST produce byte-identical segmentation; missing model aborts test startup.
- New code:
  - `evals/goal_completion.py` (LLM-judge with pinned prompt)
  - `evals/tool_output_verifier.py` (hybrid)
  - `evals/claim_extractor.py` (deterministic Sentence + SchemaField)

## 7. Correctness Properties

### Property 1: Citation membership
*For any* generative result `r` accepted by CiteOrFail with surfaced sources
`S = {c.citation for c in ctx.surfaced_sources}`, `set(r.cited_evidence_refs) ⊆ S`.
Non-member-citation results trigger RECOVER and are never accepted as-is.

**Validates: §3 Invariants 2, 11 / §4 cite-or-fail scenarios / SPEC-00 Property 1**

### Property 1a: Grounding-policy matrix
*For any* node N with ungrounded Claims extracted by ClaimExtractor:
- `N.grounding == REQUIRED` ⇒ PostflightDecision is RECOVER (Inv 3a) or
  HALT (Inv 15 escalation).
- `N.grounding == BEST_EFFORT` ⇒ PostflightDecision is ACCEPT and
  `derived_unverified_claims` carries the ungrounded set (Inv 3b).
- `N.grounding ∈ {OPTIONAL, DISABLED}` ⇒ PostflightDecision is ACCEPT
  with no derived claims (Inv 3c, 3d).

**Validates: §3 Invariants 3a/3b/3c/3d / §4 grounding-policy scenarios**

### Property 2: Halt safety
*Once* OnlineEvalInterceptor emits HALT(DAG), no further node is dispatched
until the Task is reset or aborted. Same predicate as SPEC-04 halt monotonicity.

**Validates: §3 Invariant 5 / SPEC-00 Property 3 / SPEC-04 Property 1**

### Property 3: Audit completeness by status (per attempt)
*Per ATTEMPT* on a given node: ACCEPTED end-to-end → exactly 2 AuditEntries
(PRE + POST); REJECTED in pre-flight → exactly 1 entry (PRE only — audit
runs last in PRE and is exempt from short-circuit per SPEC-01 Inv 5);
REJECTED/RECOVERED/HALTED in post-flight → exactly 2 entries. A node that
recovers once and then accepts produces 4 total entries across its 2
attempts.

**Validates: §3 Invariant 8 / §4 audit-completeness scenarios**

### Property 4: Recovery boundedness
*For any* node, `task.retry_ledger[node_id] ≤ node.retry_budget`. Once equal,
the next failure escalates to HALT.

**Validates: §3 Invariant 7 / §4 "Goal completion recovers once then halts"**

### Property 5: Authorization side-effect freedom
*For any* AuthorizationPolicy.authorize call, the policy SHALL NOT mutate
Task, Context, or RuntimeServices state — it returns a decision only.

**Validates: §3 Invariant 1**

### Property 6: Tool-layer grounding
*For any* node consuming tool output, ToolOutputVerifierInterceptor runs and
its decision is recorded before downstream dispatch. Unverified outputs never
reach a downstream node's surfaced_sources.

**Validates: §3 Invariant 4 / §4 "Tool-output verifier" / SPEC-00 Invariant 11**

### Property 7: Judge self-citation
*For any* GoalCompletionResult treated as ACCEPT, `judge_citations` is a
non-empty subset of the terminal node's surfaced_sources citations. This
prevents the judge LLM from being a hallucination surface itself.

**Validates: §3 Invariant 12 / §4 "Goal-completion judge must self-cite"**

## 8. Eval Criteria

LLM-judge evaluators are fully pinned. Prompts and corpora live under
`cemaf/data/eval_pins/` and are versioned with the spec.

| Evaluator | Node | Mode | Threshold | Method | Pinned |
|---|---|---|---|---|---|
| GroundingEvaluator | every REQUIRED-grounding node | GATE | membership_violations == 0 | deterministic | n/a |
| GoalCompletionEvaluator | terminal node | GATE | achieved == true ∧ confidence ≥ 0.8 ∧ judge_citations ⊆ surfaced (fixed pin; calibration corpus `cemaf/data/eval_pins/goal_completion_calibration_v1.jsonl` is regenerated only by explicit PR that simultaneously updates the threshold) | LLM judge | prompt `prompts/goal_completion_v1.md`, model `claude-sonnet-4-6`, temp=0, top_p=1 |
| LegitimacyEvaluator | every node (pre) | GATE | authorized == true | deterministic (rule-based AuthorizationPolicy) | n/a |
| HallucinationProbe | every generative node | OBSERVE (always — gating happens via per-PR diff against pinned baseline JSON, not via runtime mode flip) | rate ≤ 0.02 with Wilson 95% CI upper bound on labeled corpus; PR-time check fails when current rate regresses beyond baseline + 0.5pp | LLM judge | corpus `tests/fixtures/hallucination_corpus_v1.jsonl` (≥500 labeled spans — landing this fixture is a precondition for SPEC-05 implementation start), prompt `prompts/halluc_judge_v1.md`, model `claude-sonnet-4-6`, temp=0; baseline JSON `cemaf/data/eval_pins/halluc_baseline.json` updated by explicit PR only |
| QualityTrendMonitor | per-Task | GATE | no HALT alert | deterministic z-score (QualityPolice rolling window) | window 30 nodes, z=−2.5 ⇒ HALT |
| AuditCompletenessEvaluator | every node | GATE | entries == expected_for_status (2 for ACCEPTED, 1 for pre-rejected, 2 otherwise) | deterministic | n/a |
| RecoveryBoundEvaluator | every node | GATE | retry_ledger[node_id] ≤ retry_budget | deterministic | n/a |
| ToolOutputVerifierEvaluator | every node consuming tool output | GATE | unverified == 0 | hybrid | LLM judge prompt `prompts/tool_verify_v1.md`, model `claude-haiku-4-5`, temp=0; deterministic schema check |

### Hallucination measurement protocol

Corpus `tests/fixtures/hallucination_corpus_v1.jsonl` (≥500 generative outputs with claim-level {grounded, ungrounded} labels) → run HallucinationProbe end-to-end with the pinned judge → Wilson 95% CI on the ungrounded rate → pass when upper bound ≤ 0.02. First `main` measurement is the recorded baseline; subsequent PRs SHALL NOT regress beyond +0.5pp without an explicit waiver.

## 9. Observability Contract

- **Spans**:
  - `gen_ai.guardian.legitimacy` — `authorized`, `policy.id`, `denied_scope`, `moderation.rule`
  - `gen_ai.guardian.cite_or_fail` — `claims.total`, `claims.ungrounded`, `non_member_refs.count`
  - `gen_ai.guardian.tool_verify` — `tool_outputs.count`, `unverified.count`
  - `gen_ai.guardian.online_eval` — `evaluator.id`, `score`, `police.alert_level`
  - `gen_ai.guardian.goal_completion` — `achieved`, `confidence`, `missing_criteria.count`, `judge_citations.count`
  - `gen_ai.guardian.audit` — `phase`, `entry.id`, `node.status_at_emission`
- **Log events**: `legitimacy.denied`, `cite.ungrounded_claim`, `cite.non_member_citation`, `tool_verify.unverified`, `eval.halt`, `goal.recover`, `goal.halted`, `goal.judge_uncited`, `audit.entry_emitted`
- **Metrics** (per SPEC-00 §9 — `guardian` is bounded ≤6, safe; node_id, task_id forbidden as labels): `cemaf_guardian_decisions_total{guardian,decision}`, `cemaf_guardian_duration_seconds{guardian,phase}` (histogram — required RED metric for hot-path alerting), `cemaf_grounding_score` (gauge, no labels), `cemaf_goal_completion_score` (gauge, no labels), `cemaf_recovery_attempts_total{strategy,outcome}`, `cemaf_tool_verify_rejections_total`, `cemaf_hallucination_probe_rate` (gauge, no labels)

## 10. User-facing failure copy

Reason strings are engineer-facing IDs; every consumer SHALL render them via
this single mapping — no ad-hoc paraphrasing. Tests assert every reason
emitted in code appears as a row here.

**Reason-string normalization (audit contract):** the SPEC-00 §6 Spec Audit
"§10 copy-coverage" gate compares emitted reason strings to row keys after
the following deterministic normalization:

```python
def normalize_reason(emitted: str) -> str:
    # Replace parametric segments with their <placeholder> form before lookup.
    # Patterns are evaluated in declared order; first match wins.
    PATTERNS = (
        (r"^out_of_scope:.+$",            "out_of_scope:<scope>"),
        (r"^moderation:.+$",              "moderation:<rule>"),
        (r"^([a-z_]+):timeout$",          "<id>:timeout"),
        (r"^([a-z_]+):exception:[A-Za-z_][A-Za-z0-9_]*$", "<id>:exception:<class>"),
    )
    for pat, canonical in PATTERNS:
        if re.fullmatch(pat, emitted):
            return canonical
    return emitted  # exact-match for non-parametric reasons
```

The audit script (`scripts/spec_audit.py`) SHALL collect emitted reasons from
codebase string-literal scan + this normalization, then compare to the row
keys in this section. Build fails on either direction (emitted reason with
no row, or row with no emitted-reason match in code).

**Scope (audit-gate boundary):** the §10 copy-coverage gate covers reason
strings emitted by guardians on `PreflightDecision.reason` /
`PostflightDecision.reason` (REJECT, RECOVER, HALT). Executor-internal audit
reasons that do not surface to end users — e.g. SPEC-06 §3 Inv 15
`patch_unverified_promotion`, emitted by the executor when it drops an
unverified ContextPatch entry — are out of scope for §10 copy coverage. They
remain auditable via the AuditEntry stream but do not require user-facing
copy. The audit script SHALL exclude any reason string declared in the
allowlist `scripts/spec_audit.allowlist.txt` from the §10 comparison;
`patch_unverified_promotion` is the canonical entry in that allowlist.

| Reason | Human message | Suggested next action |
|---|---|---|
| `out_of_scope:<scope>` | "This action isn't permitted in your current workspace scope (`<scope>`)." | "Ask an admin to grant the scope, or rephrase the request to stay within current permissions." |
| `moderation:<rule>` | "Your request was blocked by content safety (rule: `<rule>`)." | "Remove the flagged content (e.g., PII, secrets) and resend." |
| `non_member_citation` | "The answer cited a source that wasn't part of the surfaced evidence." | "We retried automatically. If you keep seeing this, check that the relevant data source is connected." |
| `ungrounded_claim` | "Part of the answer wasn't backed by a cited source, so we held it back." | "Try rephrasing more narrowly, or attach a document with the missing context." |
| `tool_unverified` | "A tool response looked unreliable, so we didn't pass it downstream." | "We're retrying with hints. No action needed; we'll surface a result or a clear failure." |
| `policy_exhausted` | "The blueprint policy couldn't be satisfied after retries." | "Review the policy on this blueprint, or relax the constraint and retry." |
| `no_blueprint_resolved` | "We couldn't pick a blueprint for this step." | "Check the agent capability or assign an explicit blueprint to this node." |
| `no_grounding_available` | "We couldn't find any source material to ground this answer." | "Connect a relevant data source or broaden the query." |
| `meta_unavailable` | "The answer needed a fix-up plan, but the recovery engine is offline." | "Retry later. If urgent, escalate — recovery is not configured for this deployment." |
| `meta_depth_exceeded` | "We tried to fix the run but kept hitting the same wall." | "Simplify the request or break it into smaller steps." |
| `meta_token_exhausted` | "We hit the recovery budget for this task." | "Either raise the recovery budget for this task class or accept the partial output and retry manually." |
| `quality_halt` | "We stopped this run — output quality dropped below the safe threshold." | "Check recent runs of this pipeline; the issue likely started earlier." |
| `goal_unreachable` | "We couldn't satisfy the request after the allowed retries." | "Narrow the request, or raise the retry budget for this task class." |
| `non_member_citation_exhausted` | "After repeated retries we still couldn't ground the answer in surfaced evidence." | "Check the connected data sources; rephrase the request; or accept a partial result and retry manually." |
| `ungrounded_claim_exhausted` | "After repeated retries part of the answer remained ungrounded." | "Attach a document with the missing context, or relax this node's grounding policy to BEST_EFFORT." |
| `tool_unverified_exhausted` | "After repeated retries the tool output remained unreliable." | "Investigate the tool's recent behavior; raise the retry budget; or disable the offending tool for this DAG." |
| `<id>:timeout` | "An internal step (`<display_name>`) took too long." | "Retry. If it persists, check service health for that subsystem." |
| `<id>:exception:<class>` | "An internal step (`<display_name>`) hit an error." | "Retry. If it persists, the error is logged with `correlation_id` for engineering follow-up — no user action available." |

`<display_name>` resolves via SPEC-01 Inv 15 (`InterceptorChain.display_name_for(id)`); built-ins: cite_or_fail→"citation check", tool_verify→"tool result check", goal_completion→"answer review", legitimacy→"permission check", pull→"evidence retrieval", blueprint→"answer plan", task_inject→"task setup", audit→"audit".

`AuthorizationPolicy` and `ModerationPipeline` SHALL return human-readable scope/rule labels (≤40 chars, no namespacing/numeric IDs — "knowledge graph writes" not `cemaf.kg.write_relation`).

Per-retry status events (SPEC-04 §9, SPEC-06 §9) — informational, not failures:

| Event | Human message |
|---|---|
| `task.retry_started` | "Retrying step (`<DAGNode.display_name>`), attempt N of M." (surfaces MAY collapse repeats; underlying event SHALL be emitted on every re-dispatch per SPEC-04 §9) |
| `task.recovery_started` | "We hit a snag — retrying with a fix-up plan." |
| `task.recovery_finished` (accepted=True) | "Fix-up succeeded — continuing." |
| `task.recovery_finished` (halt=True) | "Fix-up couldn't recover the run." |

Unverified-claim rendering (`GroundingPolicy.BEST_EFFORT`): each claim in `AgentResult.unverified_claims` SHALL render with a leading `[unverified]` tag, and the surface SHALL show a one-line footer: "Some statements above couldn't be matched to a cited source — treat them as unconfirmed."

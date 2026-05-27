---
title: Guardian Mesh — legitimacy, cite-or-fail, tool-verify, eval-halt, goal-completion
spec_id: SPEC-05
status: Draft
last_reviewed: 2026-05-26
owner: drchinca
parent: SPEC-00 — Enterprise Context Brain
depends_on: SPEC-01, SPEC-02, SPEC-03, SPEC-04
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
| `DEFAULT` | legitimacy → pull → blueprint → task_inject | cite_or_fail → tool_verify → online_eval → goal_completion → audit |
| `RECOVERY` | legitimacy → pull → blueprint → task_inject | cite_or_fail → tool_verify → audit |

`DAGExecutor.run(*, chain_profile=ChainProfile.DEFAULT)` is the default;
`MetaDispatcher` (SPEC-06) overrides to `RECOVERY` for sub-DAG runs.
Guardians are auto-injected at bootstrap; opting out is explicit.

## 2. Interface Contract (MDE)

Common types in SPEC-00 §2 (`Citation`, `CiteableChunk`, `AgentResult`, `DAGNode`).

### Claim — the unit of grounding

```python
@dataclass(frozen=True, slots=True)
class Claim:
    """A factual proposition that requires a citation."""
    claim_id: str
    text: str                                       # the spanning text
    span: tuple[int, int] | None                    # offsets in raw_text when applicable
    citations: tuple[Citation, ...]                 # claimed grounding (subset of result.cited_evidence_refs)

@runtime_checkable
class ClaimExtractor(Protocol):
    """Deterministic given a fixed implementation. Two impls in v1:
       - SchemaFieldClaimExtractor: each non-trivial field (non-None,
         non-empty, non-default) of a Pydantic output is one Claim.
       - SentenceClaimExtractor: segment raw_text via the pinned rules in
         `evals/claim_extractor.py::SENTENCE_RULES_V1`:
           * sentence boundary: `(?<=[.!?])\s+(?=[A-Z])`
           * hedge phrases (skipped, not Claims): {"i think", "perhaps",
             "maybe", "it is possible that", "likely", "probably", "i'm not
             sure", "could be"} (case-insensitive prefix match)
           * factual: any remaining sentence with ≥1 token whose
             POS-tag-equivalent is NOUN, PROPN, NUM, or DATE per the
             `en_core_web_sm` tagger pinned in `cemaf/data/eval_pins/`.
       Default is SchemaFieldClaimExtractor when output_schema is set, else
       SentenceClaimExtractor. Pluggable via RuntimeServices.claim_extractor.
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
      claims  = ClaimExtractor.extract(result=result)
      cited   = set(result.cited_evidence_refs)

      if cited - surfaced:                  -> REJECT(reason="non_member_citation",
                                                       hints=[fix=cite from surfaced])
      if any claim with claim.citations == () and node.grounding == REQUIRED:
                                            -> REJECT(reason="ungrounded_claim",
                                                       hints=[fix=cite source X for claim Y])
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
    """POST position 2. Active when any element of result.tool_calls has
    consumed_by_node != None. Timing: at post-flight assembly time the
    executor inspects static DAG successors of `node`, builds a NEW
    AgentResult whose `tool_calls` tuple has `consumed_by_node` populated,
    and passes that to the post chain. The original AgentResult is not
    mutated (frozen-dataclass invariant preserved); the interceptor never
    touches dag.edges directly.

    Deterministic schema check: each ToolCallOutput.output is validated
    against the registered ToolSchema.output_schema; a schema-mismatch
    contributes one entry to VerifyResult.unverified_outputs with
    reason="schema_mismatch".

    LLM-judge plausibility check (pinned `prompts/tool_verify_v1.md`,
    `claude-haiku-4-5`, temp=0) runs only on outputs that pass schema
    validation, scoring fabrication likelihood.

    REJECT(reason="tool_unverified", strategy=RETRY_WITH_HINTS) on failure.
    """
    interceptor_id = "tool_verify"
    phase = InterceptorPhase.POST
```

### Online eval + halt

```python
class OnlineEvalInterceptor(NodeInterceptor):
    """POST. Runs configured evaluators in GATE mode synchronously, records
    scores into QualityPolice. Returns HALT(scope=DAG) when AlertLevel.HALT.
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
    missing_criteria: tuple[str, ...] = ()
    reason: str | None = None
    judge_citations: tuple[Citation, ...] = ()       # judge cites surfaced sources for its reasoning

class GoalCompletionInterceptor(NodeInterceptor):
    """POST, runs only when node.is_terminal == True.
    Decision policy (uses get_retry(task.retry_ledger, node.id), per SPEC-04 Inv 10):
      - achieved AND confidence ≥ 0.8                                              → ACCEPT
      - !achieved AND get_retry(task.retry_ledger, node.id) < node.retry_budget    → RECOVER(INVOKE_META_ARCHITECT)
      - !achieved AND get_retry(task.retry_ledger, node.id) ≥ node.retry_budget    → HALT(scope=TASK)
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
2. `WHEN any element of result.cited_evidence_refs ∉ {c.citation for c in ctx.surfaced_sources}, THE CiteOrFailInterceptor SHALL REJECT(reason="non_member_citation").`
3. `WHEN node.grounding == REQUIRED AND ClaimExtractor.extract yields a Claim with citations==(), THE CiteOrFailInterceptor SHALL REJECT(reason="ungrounded_claim").`
4. `WHEN ToolOutputVerifier.verify returns verified=False, THE ToolOutputVerifierInterceptor SHALL REJECT(reason="tool_unverified").`
5. `WHEN OnlineEvalInterceptor records a score that triggers QualityPolice HALT, THE PostflightDecision SHALL be HALT(scope=DAG).`
6. `THE GoalCompletionInterceptor SHALL run iff node.is_terminal == True.`
7. `WHEN GoalCompletionResult.achieved == False AND get_retry(task.retry_ledger, node.id) < node.retry_budget, THE PostflightDecision SHALL be RECOVER(INVOKE_META_ARCHITECT). Otherwise HALT(scope=TASK).`
8. `THE AuditInterceptor SHALL emit one AuditEntry per phase invocation that runs, scoped per ATTEMPT. Definition: an ATTEMPT is one (PRE → optional EXECUTE → POST) pass through the parent node's chain. A SPEC-06 recovery sub-DAG dispatched mid-attempt is NOT a new attempt of the parent — it is a separate run with its own audit entries (linked via parent_correlation_id, SPEC-06 Inv 6); the parent's RECOVER decision plus the executor's increment_retry then begin attempt N+1, which is a fresh PRE/POST audit pair. Audit completeness per attempt: ACCEPTED end-to-end → 2 entries (PRE + POST); REJECTED/RECOVERED/HALTED in post-flight → 2 entries; REJECTED in pre-flight → 1 entry (PRE only — audit is the LAST PRE interceptor and SHALL still emit when an earlier PRE rejected, per SPEC-01 Inv 5).`
9. `Recovery via RETRY_WITH_HINTS SHALL pass RecoveryHint instances in goal.metadata["remediation"] to the re-dispatched agent (per SPEC-01 Inv 10).`
10. `Guardian interceptors SHALL be auto-injected at bootstrap when the corresponding RuntimeServices.* field is non-None; opting out requires an explicit ChainConfig override.`
11. `Citation membership check (Inv 2) SHALL be replay-safe: identical surfaced_sources + identical cited_evidence_refs yield identical decisions.`
12. `WHEN node.grounding == REQUIRED at the terminal node, THE GoalCompletionEvaluator SHALL self-cite — judge_citations SHALL be a non-empty subset of {c.citation for c in ctx.surfaced_sources at terminal node}; failure → REJECT the judge result and treat as achieved=False with confidence=0. WHERE grounding ∈ {OPTIONAL, DISABLED}, judge_citations MAY be empty.`
13. `THE AuditInterceptor SHALL NOT be subject to the SPEC-01 Inv 5 short-circuit — its PRE entry SHALL be emitted even when an earlier PRE interceptor REJECTED (Inv 8 above is the per-attempt completeness contract that depends on this).`

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

  Scenario: Cite-or-fail rejects non-member citation
    Given ctx.surfaced_sources Citations = {a, b, c}
    And result.cited_evidence_refs = {d}
    When CiteOrFailInterceptor runs
    Then PostflightDecision is REJECT(reason="non_member_citation")
    And recovery_strategy is RETRY_WITH_HINTS

  Scenario: Cite-or-fail rejects ungrounded claim
    Given node.grounding == REQUIRED
    And SchemaFieldClaimExtractor extracts a Claim with citations==()
    When CiteOrFailInterceptor runs
    Then PostflightDecision is REJECT(reason="ungrounded_claim")

  Scenario: Tool-output verifier catches fabricated tool result
    Given a tool output consumed by the next node
    And ToolOutputVerifier.verify returns verified=False with one unverified output
    When ToolOutputVerifierInterceptor runs
    Then PostflightDecision is REJECT(reason="tool_unverified")
    And recovery_hints reference the unverified output

  Scenario: Online eval triggers DAG halt
    Given QualityPolice configured with HALT threshold breached
    When OnlineEvalInterceptor records the next score
    Then it returns HALT(scope=DAG)
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
    Then PostflightDecision is HALT(scope=TASK)

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
- `spacy==3.7.4` + `en_core_web_sm==3.7.1` (exact pins; mirrored in `pyproject.toml` and `cemaf/data/eval_pins/spacy_model_version.txt`) — required by `SentenceClaimExtractor`'s POS-tag pass. Two CI runs MUST produce byte-identical sentence segmentation given identical input; absence of the pinned model file aborts SPEC-05 test suite startup.
- New code:
  - `evals/goal_completion.py` (LLM-judge with pinned prompt)
  - `evals/tool_output_verifier.py` (hybrid)
  - `evals/claim_extractor.py` (deterministic Sentence + SchemaField)

## 7. Correctness Properties

### Property 1: Citation membership
*For any* generative result `r` accepted by CiteOrFail with surfaced sources
`S = {c.citation for c in ctx.surfaced_sources}`, `set(r.cited_evidence_refs) ⊆ S`.
Rejected results are never stored.

**Validates: §3 Invariants 2, 3, 11 / §4 cite-or-fail scenarios / SPEC-00 Property 1**

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

To support the `rate ≤ 0.02` claim:
1. **Corpus**: `tests/fixtures/hallucination_corpus_v1.jsonl` — ≥500 generative
   outputs from CEMAF nodes, each with claim-level human labels {grounded,
   ungrounded}.
2. **Run**: HallucinationProbe over the corpus end-to-end with the pinned judge.
3. **Statistic**: Wilson 95% CI on the unlabeled-as-ungrounded rate.
4. **Pass**: upper CI bound ≤ 0.02.
5. **Baseline**: first measure on `main` is the recorded baseline; subsequent
   PRs cannot regress beyond +0.5pp without explicit waiver.

## 9. Observability Contract

- **Spans**:
  - `gen_ai.guardian.legitimacy` — `authorized`, `policy.id`, `denied_scope`, `moderation.rule`
  - `gen_ai.guardian.cite_or_fail` — `claims.total`, `claims.ungrounded`, `non_member_refs.count`
  - `gen_ai.guardian.tool_verify` — `tool_outputs.count`, `unverified.count`
  - `gen_ai.guardian.online_eval` — `evaluator.id`, `score`, `police.alert_level`
  - `gen_ai.guardian.goal_completion` — `achieved`, `confidence`, `missing_criteria.count`, `judge_citations.count`
  - `gen_ai.guardian.audit` — `phase`, `entry.id`, `node.status_at_emission`
- **Log events**: `legitimacy.denied`, `cite.ungrounded_claim`, `cite.non_member_citation`, `tool_verify.unverified`, `eval.halt`, `goal.recover`, `goal.halted`, `goal.judge_uncited`, `audit.entry_emitted`
- **Metrics**: `guardian_decisions_total{guardian,decision}`, `grounding_score`, `goal_completion_score`, `recovery_attempts_total`, `tool_verify_rejections_total`, `hallucination_probe_rate`

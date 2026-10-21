# Context and provenance acceptance cases

Status: 25 engineering cases implemented and verified offline. Two pilot cases remain unverified: real-provider portability and independently measured business value.

The pilot must let an authorized reviewer inspect the exact evidence behind an
answer, verify the recorded input, and identify answers affected by later policy
changes. This is a bounded acceptance slice of
[SPEC-17](../specs/SPEC-17-autonomous-context-substrate.md), not a new orchestration
or manifest architecture. Its invariant mappings identify the owning requirement;
a passing local case does not close the entire SPEC-17 invariant.

## 1. Pilot contract

The consuming application owns policy approval, effective dates, conflicts,
questions, and review workflow. CEMAF owns context compilation, source identity,
provenance, citation membership, recording, replay, and runtime bounds through
its existing public protocols.

For each answer, acceptance requires:

1. Authorized, versioned source references and integrity-checked snapshots.
2. The exact ordered model request, model/tool configuration, selected and
   excluded evidence, compiler version, and authorization/policy version.
3. Claim-level source attribution with a separate support verdict. A citation
   pointing to a known source does not make the claim verified.
4. Reconstructable recorded state and an access-controlled evidence export.
5. Exact affected-answer lookup when a source changes, expires, or is revoked,
   including dependencies introduced through compaction.

A historical authorization decision records what was permitted at generation;
it does not grant permanent permission to disclose that evidence later.
Deterministic state replay does not promise identical fresh model output.

## 2. Composition and protocol ownership

| Concern | Existing CEMAF path | Missing behavior belongs in |
|---|---|---|
| Source identity and bounded selection | `ContextSource`, `ContextCompiler`, `TokenBudget` | SPEC-17 `ContextManifest` and `WorkingContextReceipt`; context module |
| Integrity and authorization | security services and SPEC-17 `ArtifactRegistry` contract | persistence adapters and context resolution; never a second app cache |
| Claim attribution | `Citation`, `CitationTracker`, `SourceRegistry`, citation evaluator | citation/evals protocols; app policy defines publication decisions |
| Context transformations | `ContextPatch`, `PatchLog`, `ProvenanceChain` | context/provenance; immutable revision and summary dependency references |
| Runtime behavior | `create_executor`, `RuntimeServices`, interceptor pipeline | existing runtime, resilience, and budget services |
| Recording and replay | `RunLogger`, `RunRecord`, `Replayer` | existing observability/replay modules and durable adapter boundaries |
| Support policy domain | revision approval, effective dates, conflict resolution | consuming application; represented here by test fixtures |

The executable DAG cases compose `create_executor(agent_registry=...,
services=RuntimeServices(...))`, the real compiler, citation gate, instrumented
LLM client, run logger, and replay. Fixed model responses test those mechanisms;
they do not constitute live-provider or answer-quality evidence. The pilot composes these services through the framework; policy approval, effective dates, and refund semantics stay in the example application.

## 3. Evidence states and commands

The machine-readable [case catalog](../../tests/acceptance/context_provenance/cases.json)
contains Given/When/Then criteria, SPEC-17 mappings, and evidence requirements.
The [policy corpus](../../tests/acceptance/context_provenance/policies.json)
contains historical, current, draft, future, confidential, cross-tenant,
conflicting, and instruction-poisoned policies, evaluated as of 2026-10-20.

| State | Meaning |
|---|---|
| `automated` | Public-path behavior has an executable acceptance test; its result must still pass |
| `known_defect` | A behavioral test reproduces a current defect; ordinary runs expose strict expected failures |
| `unimplemented` | The catalog defines the required behavior, but executable evidence is absent |
| `pilot` | Real-provider or independent human-review evidence is required |

Run the progress suite and its evidence summary:

```bash
make test-context-provenance
```

Require the complete engineering test matrix (25 cases):

```bash
make check-context-provenance
```

Run the strict adoption gate (all 27 cases, including real evidence):

```bash
make accept-context-provenance
```

The strict command disables expected-failure handling for known defects and
returns nonzero while any required catalog case lacks passing executable
evidence. Running a subset cannot graduate the pilot. Skips, expected failures,
missing credentials, missing implementations, and missing human timings are
never acceptance passes. A defect fixed without updating its expected-failure
classification fails the ordinary suite as an unexpected pass.

For machine-readable results, use pytest's standard JUnit output:

```bash
uv run pytest tests/acceptance/context_provenance -q -rx \
  --junitxml=/tmp/cemaf-context-provenance-results.xml
```

CI runs the engineering gate and uploads JUnit plus the case catalog. A green
engineering job verifies the implemented cases. Full graduation requires the
strict adoption command and the live/human evidence described below. The catalog
pins the required test matrix, including every adversarial parameter; selecting
only passing variants cannot satisfy a case.

## 4. Acceptance scenarios

The catalog pins each case to its complete executable test matrix. Offline tests
verify framework behavior; live and human evidence remain separate.

### compiled_revision_ids

Requirements: HC-2, HC-3, DA-1. Evidence: `automated`.

```gherkin
Scenario: compiled revision ids
  Given Two policy revisions have distinct revision-qualified source IDs.
  When The compiler selects their evidence.
  Then Each selected ID resolves to the supplied revision.
  And The rendered context retains selected identifiers.
```

### selection_budget

Requirements: HC-3, SA-2. Evidence: `automated`.

```gherkin
Scenario: selection budget
  Given Two policies compete for a budget that holds one under the injected estimator.
  When PriorityContextCompiler selects evidence.
  Then Estimated source tokens fit the available budget.
  And The omitted source has a budget exclusion reason.
```

### clearance_filter

Requirements: HC-3, SA-1. Evidence: `automated`.

```gherkin
Scenario: clearance filter
  Given A confidential policy has higher priority than a permitted policy.
  When The caller compiles with INTERNAL clearance.
  Then The confidential text is absent from model context.
  And The permitted policy fills the freed budget.
```

### compaction_lineage

Requirements: HC-4, DA-3. Evidence: `automated`.

```gherkin
Scenario: compaction lineage
  Given Old evidence is compacted while recent evidence is preserved.
  When The real compiler creates a summary.
  Then The summary names every compacted parent.
  And Recent evidence and its identifier remain intact.
```

### citation_membership

Requirements: DA-1, SA-1. Evidence: `automated`.

```gherkin
Scenario: citation membership
  Given Only the selected policy revision is citable for the answer.
  When A real DAG emits a selected, superseded, excluded, or fabricated citation.
  Then Only the selected revision passes the citation gate.
  And A rejected citation prevents downstream publication.
```

### citation_verification_status

Requirements: HC-5, EV-3. Evidence: `automated`.

```gherkin
Scenario: citation verification status
  Given An answer cites a source present in the selected evidence.
  When CitationTracker records the claim without an independent support check.
  Then The claim remains UNVERIFIED.
  And Source membership is not labeled factual verification.
```

### recorded_messages

Requirements: DA-1, DA-3. Evidence: `automated`.

```gherkin
Scenario: recorded messages
  Given An instrumented LLM receives compiled policy messages and returns a fixed response.
  When The run record is serialized and restored.
  Then The exact message order and text survive.
  And The recorded output and token usage survive.
```

### runtime_replay

Requirements: DA-1, DA-3. Evidence: `automated`.

```gherkin
Scenario: runtime replay
  Given A policy-answer agent runs through create_executor and RuntimeServices.
  When The final RunRecord is restored and replayed in PATCH_ONLY mode.
  Then The final state matches the original.
  And Replay makes no further model call.
  And The original evidence identity survives.
```

### ordered_input_hash

Requirements: HC-4, DA-3. Evidence: `automated`.

```gherkin
Scenario: ordered input hash
  Given The same evidence appears in two different prompt orders.
  When Their rendered messages and fingerprints are compared.
  Then Different rendered message orders produce different input fingerprints.
```

### scoped_read

Requirements: XS-1, SA-1. Evidence: `automated`.

```gherkin
Scenario: scoped read
  Given A user has an explicit read grant for the item scope path.
  When RBACMemoryStore.get loads that permitted policy.
  Then The authorized item is returned without a global role.
```

### abac_list

Requirements: XS-1, SA-1. Evidence: `automated`.

```gherkin
Scenario: abac list
  Given A user can list tenant A, but a tenant B grant fails its attribute condition.
  When RBACMemoryStore lists project policies.
  Then Only tenant A items are returned.
  And Tenant B content and identifiers are absent.
```

### concurrent_logger

Requirements: DA-1, DA-3. Evidence: `automated`.

```gherkin
Scenario: concurrent logger
  Given Two runs overlap on one executor with one run logger.
  When Both runs complete after a synchronization barrier.
  Then Both runs succeed.
  And Two separate records contain their own output and run identity.
```

### runtime_budget

Requirements: SA-2. Evidence: `automated`.

```gherkin
Scenario: runtime budget
  Given A custom agent emits no optional token metadata but its LLM calls are instrumented.
  When Recorded token usage exceeds the configured run budget.
  Then The guard charges actual logged usage.
  And Further dispatch is blocked before another model call.
```

### repair_budget

Requirements: SA-2, SA-3. Evidence: `automated`.

```gherkin
Scenario: repair budget
  Given Schema repair requires two model calls and the cumulative output allowance is five tokens.
  When The first response consumes four tokens and requires repair.
  Then The next allowance is at most one token.
  And Repair never resets the cumulative allowance.
```

### result_failure_resilience

Requirements: SA-3. Evidence: `automated`.

```gherkin
Scenario: result failure resilience
  Given A protocol adapter returns retryable failed completion results.
  When The foreground client executes its retry and circuit policies.
  Then Attempt count respects the configured retry policy.
  And Failed results count toward opening the circuit.
```

### snapshot_integrity

Requirements: HC-4, BD-2, DA-3. Evidence: `automated`.

```gherkin
Scenario: snapshot integrity
  Given A manifest pins a policy revision, content digest, and exact excerpt.
  When The backing bytes are modified, replaced, or missing.
  Then Resolution fails before model dispatch.
  And The original snapshot remains independently verifiable.
```

### request_manifest

Requirements: HC-4, DA-1, EV-2. Evidence: `automated`.

```gherkin
Scenario: request manifest
  Given One model call includes messages, tools, model options, and compiler/policy versions.
  When An independently loaded evidence manifest is inspected.
  Then Every input field and ordered message is recoverable.
  And Changing input order, tool schema, model settings, source revision, or policy version changes the request identity.
```

### actual_prompt_budget

Requirements: HC-3, SA-2. Evidence: `automated`.

```gherkin
Scenario: actual prompt budget
  Given A complete request includes system/user messages, framing, tools, and an output reservation.
  When The application computes the provider-specific input allowance before dispatch.
  Then Actual input accounting includes the complete rendered request, not only raw source estimates.
  And Over-budget or zero-remaining-budget requests halt before the provider call.
  And Estimated and provider-reported token counts remain separately labeled.
```

### permission_revocation

Requirements: XS-1, SA-1, DA-4. Evidence: `automated`.

```gherkin
Scenario: permission revocation
  Given A policy is retrieved while authorized and access is revoked before dispatch or export.
  When The application attempts to use or disclose the snapshot.
  Then Authorization is rechecked at the declared boundary.
  And Denied bytes and identifiers do not reach the caller or model.
  And Historical evidence access follows current retention and authorization policy.
```

### fresh_conflicting_policy

Requirements: HC-3, HC-5. Evidence: `automated`.

```gherkin
Scenario: fresh conflicting policy
  Given Policy fixtures include superseded, expired, future-effective, and conflicting current revisions.
  When The application answers an as-of-date question.
  Then Only an authoritative effective revision supports an answer.
  And Unresolved conflict or missing current evidence yields an explicit abstention.
```

### claim_support

Requirements: HC-5, EV-3. Evidence: `automated`.

```gherkin
Scenario: claim support
  Given The selected policy says thirty days and proposed claims say thirty days, ninety days, or contain an uncited extra assertion.
  When Claims are checked against independently labeled supporting excerpts.
  Then Supported and contradicted claims receive distinct verdicts.
  And Unsupported additional claims cannot be published as verified.
```

### change_impact

Requirements: HC-4, DA-1, DA-4. Evidence: `automated`.

```gherkin
Scenario: change impact
  Given Answers depend on different revisions and some evidence is used only through a summary.
  When One source revision changes, expires, or is revoked.
  Then Exactly the dependent answers are flagged, including transitive summary dependencies.
  And Unrelated answers and the historical record are unchanged.
```

### export_privacy

Requirements: XS-1, SA-1, DA-4. Evidence: `automated`.

```gherkin
Scenario: export privacy
  Given A reviewer can access public evidence but not restricted documents or secrets.
  When The application exports an evidence record or telemetry.
  Then The export contains only permitted evidence.
  And Redaction is recorded without leaking original secrets.
  And Redaction does not silently rewrite the historical evidence identity.
```

### durable_evidence

Requirements: DE-5, DA-3, EV-2. Evidence: `automated`.

```gherkin
Scenario: durable evidence
  Given A completed answer and immutable source references are committed.
  When All original worker objects are discarded and the evidence is loaded in a fresh process.
  Then The exact recorded context and source revisions can be reconstructed.
  And Missing artifacts fail explicitly.
  And No fresh model generation is presented as deterministic replay.
```

### model_portability

Requirements: BP-2, EV-2, EV-3. Evidence: `pilot`.

```gherkin
Scenario: model portability
  Given Two explicitly versioned provider adapters use the same corpus, retrieval outputs, and evidence contract.
  When The same labeled questions are executed through each provider.
  Then Both emit the same evidence schema and preserve source identity.
  And Missing credentials are reported as not-run.
  And No equality of newly generated answer text is required.
```

Open evidence: The opt-in real-provider suite is implemented. Available credentials returned HTTP 401 (OpenAI) and 403 (Gemini) during preflight; no successful live portability evidence was collected.

### pilot_value

Requirements: HC-5, EV-1, EV-2, EV-3. Evidence: `pilot`.

```gherkin
Scenario: pilot value
  Given A frozen corpus and at least one hundred independently labeled questions cover ordinary and adversarial policy cases.
  When Simple prompting, citation-enabled retrieval, and the CEMAF path are compared with the same model, corpus, retriever, output budget, and question order.
  Then Record unsupported-claim rate, unauthorized evidence, affected-answer precision/recall, review time, token cost, and p50/p95 latency.
  And Use blinded counterbalanced reviewer assignments and publish paired results and uncertainty.
  And Zero unauthorized evidence in the tested cases and at least thirty percent lower median verification time than the citation baseline are initial go/no-go targets.
  And Do not graduate when required human timings or live results are absent.
```

Open evidence: The matched runner, blinded assignments, and evidence validator are implemented. Independent workload labels, actual costs, and human timings have not been collected.

### source_instruction_isolation

Requirements: SA-1, SA-6. Evidence: `automated`.

```gherkin
Scenario: source instruction isolation
  Given A retrieved policy contains instructions to ignore permissions or expose another tenant.
  When That source is compiled and sent as evidence.
  Then Source text cannot modify trusted authorization policy or grant tool capabilities.
  And An evidence record distinguishes source content from trusted instructions.
```

## 5. Pilot comparison and go or no go decision

Freeze and hash the corpus, question set, model/provider versions, retrieval
outputs, output budget, policy configuration, and evaluation instructions before
comparison. Use at least 100 independently labeled questions, including every
policy fixture category, missing evidence, contradictory claims, uncited extra
claims, revocations, and source changes through summaries. Retain per-case raw
results and report class counts; a large benign majority cannot hide a failed
security class.

Compare three application paths:

1. The same model with a simple fixed-context prompt.
2. The same model with citation-enabled retrieval.
3. The same model/retrieval configuration with CEMAF evidence handling.

Hold question order, corpus, model settings, retriever, and output budget fixed
across paths. Randomize and counterbalance blinded reviewer assignments so a
reviewer does not gain an advantage from previously seeing the same question.
Measure support correctness and abstention against independent labels; report
reviewer agreement and adjudicate disputed labels separately.

Publish paired per-question results and uncertainty for:

- unsupported, contradicted, and uncited claims;
- unauthorized evidence in model requests, outputs, exports, and telemetry;
- source-change impact precision and recall, including summary dependencies;
- reviewer verification time, both median and distribution;
- actual provider token usage and cost, separated from estimates;
- added p50/p95 latency and recorded evidence size.

Initial proposed decision thresholds are zero unauthorized evidence in the
adversarial suite, complete reconstruction for every accepted answer, complete
identification of labeled affected answers without unrelated flags, and at least
30% lower median reviewer verification time than the citation baseline. Record
and approve the latency/cost overhead ceiling before running the pilot; missing
ceilings or timings leave the value case unverified. These are pilot targets,
not measured results or universal security guarantees.


## 6. Implemented path and limits

The public ports are `context.manifest.ContextManifest`, `WorkingContextReceipt`,
`RequestManifest`, `persistence.artifacts.ArtifactRegistry`/`ArtifactResolver`,
`persistence.evidence.EvidenceStore`, `llm.preflight.RequestTokenCounter`, and
`citation.support.ClaimSupportVerifier`. The local adapters use SQLite for
immutable snapshots, complete recorded requests/responses, and transitive answer
dependencies. `RuntimeServices` carries the adapters;
`llm.factories.create_evidence_client` composes the request-scoped boundary.
Configuring service fields alone does not wrap arbitrary application clients.

The boundary verifies complete selected text snapshots and their summary parents,
counts the rendered request through a provider-specific port, and checks current
permissions/integrity again immediately before dispatch. Model input, tool
schemas, generation options, compiler/policy versions, source references, and
authorization version contribute to request identity. This is the complete
CEMAF request before adapter conversion, not an assertion that each provider
uses the same wire format. Estimated and provider-reported tokens remain separate;
uncertified counters fail the default exact-preflight mode.

OpenAI preflight uses the [input token endpoint](https://developers.openai.com/api/docs/guides/token-counting);
Gemini uses [countTokens with the complete generateContentRequest](https://ai.google.dev/api/tokens).
Gemini keeps trusted instructions in `systemInstruction` and credentials in a
header. Strict counting errors cannot silently fall back to estimates.

`security.evidence.export_evidence_view` rechecks current access, including summary
parents. Default export masks free-form request, response, and source content.
Applications supply explicit masking policies to disclose permitted fields.
Denied evidence also withholds potentially tainted request/response bodies.
Redactions receive a new view identity while retaining the historical evidence
identity. Raw run/evidence databases are private operator artifacts; do not expose
them through an unauthenticated file server or generic telemetry export.

The [policy example](../../examples/app_shapes/policy_evidence.py) owns the latest
approved effective revision, conflict abstention, and bounded refund-window
verification. The generic exact-quote verifier deliberately leaves paraphrases
unsupported. The publication gate accepts only checked claims and rejects an
additional unchecked answer sentence. Instructions in source text cannot grant
capabilities through this path. These tests do not claim universal prompt-injection
prevention or general semantic entailment.

The local adapter accepts bounded text artifacts (one megabyte each, at most 256
references per manifest) and canonical request records up to one megabyte. It is
not the distributed authority, bulk-object plane, atomic task/outbox commit,
automatic failover, retention scheduler, or production profile required by the
rest of SPEC-17. The owning modules and missing seams were checked before adding
these narrow ports; the acceptance tests exercise them through the same factory,
DAG, runtime services, logging, citation/eval gate, and replay used by applications.

## 7. Runnable comparison and review

Run the offline three-arm demonstration:

```bash
uv run python examples/app_shapes/policy_evidence.py
uv run python benchmarks/run_policy_pilot.py --output /tmp/cemaf-policy-pilot
```

The runner executes simple prompting, citation prompting, and the evidence path
through a shared executor/logger harness. It freezes question order, retrieval,
model settings, and output limits. Every run retains a run-record digest, tokens,
latency, and provider version when available. The default three fixture questions
are an offline demonstration, not an independently labeled customer workload.
Costs remain unmeasured until a documented price profile or invoice is attached.

For a real corpus and question list, run:

```bash
uv run python benchmarks/run_policy_pilot.py --live \
  --corpus /path/to/policies.json --dataset /path/to/questions.json \
  --limit 100 --output /private/path/to/pilot
```

Corpus uses the policy fixture schema; questions are objects with `id`,
`question`, and ISO-date `as_of` fields. The initial domain is tenant A's refund
policy. Three reviewer identities are assigned without showing one reviewer
multiple arms of the same question. `private/` retains the arm mapping and raw
records; `reviews/` contains blinded packets with answers, evidence, and empty
review fields. Assign these IDs to real independent reviewers and retain their
original timing/label receipts. The validator checks their supplied attestations;
it does not authenticate that a person performed the review.

Defaults are the existing OpenAI adapter model and Gemini's documented stable
Flash-Lite profile. Override with `CEMAF_PILOT_OPENAI_MODEL` and
`CEMAF_PILOT_GEMINI_MODEL`; credentials remain environment-only. Missing credentials
are not-run, and rejected credentials are failed preflights. The observed local
preflights returned OpenAI HTTP 401 and Gemini HTTP 403; no successful live result
is claimed.

Run just the live evidence contracts when access is available:

```bash
CEMAF_RUN_CONTEXT_PROVENANCE_LIVE=1 uv run pytest \
  tests/acceptance/context_provenance/test_live_evidence.py -q
```

`evals.pilot.PilotStudy` defines the collected study schema. Its conditions pin the
model version, corpus/retrieval digests, output allowance, question order, and
prompt version. Observations require actual provider tokens, documented costs,
blinded human timings, independent labels, and source/run/review digests.
`evaluate_pilot` requires at least 100 matched questions across all three arms,
reports paired bootstrap uncertainty, and enforces the declared cost/latency
ceilings and 30% median verification-time target. Installed source changes
invalidate the report. Adoption also resolves every run, human-label, and review
receipt from `artifacts/<sha256>.json` beside the study, verifies its digest, and
checks usage/identity against the observation. Label receipts include `question_id`,
`labeler_id`, `human: true`, and `category`; review receipts include `question_id`,
`reviewer_id`, `human: true`, and `review_seconds`. Ordinary, stale, conflicting,
unauthorized, injected, revoked, and source-change cases are required. Synthetic
statistical unit tests never satisfy the pilot acceptance marker.

```bash
uv run python benchmarks/run_policy_pilot.py --study /path/to/study.json
CEMAF_RUN_CONTEXT_PROVENANCE_LIVE=1 \
CEMAF_POLICY_PILOT_STUDY=/path/to/study.json make accept-context-provenance
```

The final command remains red until both real-provider contracts and the
independently measured pilot pass. The broader distributed-production and
industry-standard graduation gates remain owned by SPEC-17.

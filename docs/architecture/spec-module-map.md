# Spec → Module Map

> One-page index from SPEC-00..10 concepts to the modules that house them. SPEC-00..06 form the Enterprise Context Brain target architecture; SPEC-07 (hub-and-spoke KG), SPEC-08 (failure-feedback loop), SPEC-09 (auction agent selection), and SPEC-10 (agent council) are landed capabilities. SPEC-07/08 close audit gaps #9 and #13; SPEC-09 closes the auction gap from the axocoatl audit; SPEC-10 builds the deliberative council layer surfaced as missing by the buried-pattern excavation. Source-of-truth for where to look — and where to land — each concept during the multi-phase build-out.

## Conventions

- **Status** values:
  - `scaffold pending` — module/file does not exist yet
  - `partial` — module exists but lacks fields/methods called out in the spec
  - `landed` — concept implemented per spec
  - `landed (needs review)` — implemented but not yet aligned to current spec text
- All target paths are under `src/` (e.g., `cemaf/interceptors/` → `src/cemaf/interceptors/`).
- "Source spec" cites the *primary* defining section. Cross-cutting concepts may be referenced in multiple specs.

## Common types and runtime (SPEC-00)

| Spec concept | Source spec | Target module | Status |
|---|---|---|---|
| `NodeBudget` | SPEC-00 §2 | `cemaf/core/types.py` | scaffold pending |
| `RunResult` (with `recovery_request`, `failed_node`) | SPEC-00 §2 | `cemaf/core/types.py` | scaffold pending |
| `RecoveryRequest` (projection type) | SPEC-00 §2, SPEC-06 §2 | `cemaf/core/types.py` | scaffold pending |
| `AcquiredLease` | SPEC-00 §2, SPEC-04 §2 | `cemaf/task/lease.py` | scaffold pending |
| `Citation` + `cited_evidence_refs` predicate | SPEC-00 §2 | `cemaf/citation/` | partial — predicate pending |
| `RuntimeServices` extensions — landed: `interceptor_pipeline`, `agent_selector`, `council_aggregator`, `knowledge_graph`, `max_recovery_attempts`; pending: `datasource_registry`, `task_repository`, `guardian_mesh`, `meta_dispatcher`, `structured_generator` | SPEC-00 §2 | `cemaf/orchestration/services.py` | partial — core fields landed |
| `RuntimeServices.knowledge_graph` | SPEC-02 §2 | `cemaf/orchestration/services.py` | landed |
| `bootstrap.create_executor()` wiring of new services | SPEC-00 §2 | `cemaf/bootstrap.py` | partial |
| OTel GenAI spans (`gen_ai.tool.execute`, `gen_ai.agent.run`, `cemaf.interceptor.*`) | SPEC-00 §9 | `cemaf/observability/` | partial |
| GATE evaluator SLOs registry | SPEC-00 §8 | `cemaf/evals/gate.py` | scaffold pending |

## Interceptor pipeline (SPEC-01)

| Spec concept | Source spec | Target module | Status |
|---|---|---|---|
| `PreInterceptor` / `PostInterceptor` Protocols (split phases) | SPEC-01a §2 | `cemaf/interceptors/protocols.py` | landed (SPEC-01a slice) |
| `InterceptorPipeline` + `GateEvalInterceptor` | SPEC-01a §2 | `cemaf/interceptors/{pipeline,gate_eval}.py` | landed (SPEC-01a slice) |
| `DecisionKind` ACCEPT/REJECT/**RECOVER** + `RecoveryHint` + `GateFailureMode` | SPEC-01a §2 | `cemaf/interceptors/types.py` | landed (RECOVER shipped) |
| `ChainProfile` enum (DEFAULT / RECOVERY) | SPEC-01 §2 | `cemaf/interceptors/profiles.py` | scaffold pending (full SPEC-01) |
| `InterceptorContext` (PRE/POST payload) | SPEC-01 §2 | `cemaf/interceptors/context.py` | scaffold pending (full SPEC-01) |
| Pipeline integration into `ContextNodeExecutor` (PRE/POST + bounded RECOVER loop) | SPEC-01a §2 | `cemaf/orchestration/context_node_executor.py` | landed |

## KG and DataSource services (SPEC-02)

| Spec concept | Source spec | Target module | Status |
|---|---|---|---|
| `DataSource` Protocol | SPEC-02 §2 | `cemaf/datasources/protocols.py` | scaffold pending |
| `DataSourceRegistry` | SPEC-02 §2 | `cemaf/datasources/registry.py` | scaffold pending |
| `PullInterceptor` (PRE-phase, hydrates context) | SPEC-02 §2 | `cemaf/datasources/pull_interceptor.py` | scaffold pending |
| Deterministic eviction policy | SPEC-02 §2 | `cemaf/datasources/eviction.py` | scaffold pending |
| KG-as-DataSource adapter | SPEC-02 §2 | `cemaf/datasources/kg_adapter.py` | scaffold pending |

## Blueprint as LLM input (SPEC-03)

| Spec concept | Source spec | Target module | Status |
|---|---|---|---|
| `BlueprintRequest[T]` (typed structured-output request) | SPEC-03 §2 | `cemaf/blueprint/request.py` | scaffold pending |
| `StructuredGenerator` Protocol | SPEC-03 §2 | `cemaf/blueprint/generator.py` | scaffold pending |
| `BlueprintInterceptor` (POST-phase, validates structured output) | SPEC-03 §2 | `cemaf/blueprint/interceptor.py` | scaffold pending |
| Blueprint → JSON Schema compilation | SPEC-03 §2 | `cemaf/blueprint/schema.py` | partial |
| Blueprint validation / repair loop | SPEC-03 §2 | `cemaf/blueprint/validator.py` | scaffold pending |

## Task state machine (SPEC-04)

| Spec concept | Source spec | Target module | Status |
|---|---|---|---|
| `Task` entity (with state machine) | SPEC-04 §2 | `cemaf/task/models.py` | scaffold pending |
| `TaskState` enum (DRAFT → QUEUED → LEASED → RUNNING → COMPLETED/FAILED) | SPEC-04 §2 | `cemaf/task/enums.py` | scaffold pending |
| `TaskRepository` Protocol | SPEC-04 §2 | `cemaf/task/repository.py` | scaffold pending |
| `AcquiredLease` (HITL pause/resume token) | SPEC-04 §2 | `cemaf/task/lease.py` | scaffold pending |
| `TaskContext` (per-task scoped context) | SPEC-04 §2 | `cemaf/task/context.py` | scaffold pending |
| Lease expiry + reclamation | SPEC-04 §2 | `cemaf/task/scheduler.py` | scaffold pending |

## Guardian mesh (SPEC-05)

| Spec concept | Source spec | Target module | Status |
|---|---|---|---|
| `Guardian` Protocol | SPEC-05 §2 | `cemaf/guardian/protocols.py` | scaffold pending |
| `GuardianMesh` (composes 6 guardians) | SPEC-05 §2 | `cemaf/guardian/mesh.py` | scaffold pending |
| `CiteOrFailGuardian` | SPEC-05 §2 | `cemaf/guardian/cite_or_fail.py` | scaffold pending |
| `UngroundedClaimGuardian` | SPEC-05 §2 | `cemaf/guardian/ungrounded_claim.py` | scaffold pending |
| `SchemaGuardian` | SPEC-05 §2 | `cemaf/guardian/schema.py` | scaffold pending |
| `PolicyGuardian` | SPEC-05 §2 | `cemaf/guardian/policy.py` | scaffold pending |
| `HallucinationGuardian` | SPEC-05 §2 | `cemaf/guardian/hallucination.py` | scaffold pending |
| `CalibrationGuardian` | SPEC-05 §2 | `cemaf/guardian/calibration.py` | scaffold pending |
| Guardian → POST-interceptor adapter | SPEC-05 §2 | `cemaf/guardian/interceptor.py` | scaffold pending |

## Self-resolving DAG (SPEC-06)

| Spec concept | Source spec | Target module | Status |
|---|---|---|---|
| `MetaDispatcher` (decides recovery routing) | SPEC-06 §2 | `cemaf/meta/dispatcher.py` | scaffold pending |
| `RecoveryRequest` projection | SPEC-06 §2 | `cemaf/core/types.py` | scaffold pending |
| Self-resolution loop in `DAGExecutor` (RECOVERY profile) | SPEC-06 §2 | `cemaf/orchestration/executor.py` | partial |
| Recovery DAG factory | SPEC-06 §2 | `cemaf/meta/recovery_dag.py` | scaffold pending |
| Audit-gate on recovery acceptance | SPEC-06 §2 | `cemaf/audit/recovery_gate.py` | scaffold pending |

### NodeResolver dispatch chain (orchestration seam — underpins SPEC-06 routing)

The bespoke council / auction / static `if`-branches in `execute_node` were
migrated to a first-match-wins resolver chain. Adding a node "kind" is now
registering a resolver, not editing `execute_node`. This is the seam a future
`MetaDispatcher` (SPEC-06) plugs a recovery-routing resolver into.

| Spec concept | Source spec | Target module | Status |
|---|---|---|---|
| `NodeResolver` protocol + `ResolveOutcome` (`RunAgent | NodeComplete`) | (orchestration) | `cemaf/orchestration/resolvers/protocols.py` | landed |
| `CouncilResolver` / `AuctionResolver` / `StaticRefResolver` (first-match-wins) | SPEC-09/10 | `cemaf/orchestration/resolvers/{council,auction,static_ref}.py` | landed |
| Resolver-chain dispatch in `execute_node` | (orchestration) | `cemaf/orchestration/context_node_executor.py` | landed |

## Hub & spoke knowledge (SPEC-07)

| Spec concept | Source spec | Target module | Status |
|---|---|---|---|
| `SpokeCacheConfig` / `SpokeStats` | SPEC-07 §2 | `cemaf/knowledge/hub_spoke.py` | landed |
| `LocalSpokeCache` (bounded LRU + TTL + negative cache) | SPEC-07 §2 | `cemaf/knowledge/hub_spoke.py` | landed |
| `HubKnowledgeGraph` (write-through + invalidation publish) | SPEC-07 §2 | `cemaf/knowledge/hub_spoke.py` | landed |
| `KGInvalidationEvent` + `kg.invalidation` topic | SPEC-07 §2, §9 | `cemaf/knowledge/hub_spoke.py` | landed |
| `SpokeReadHubWriteKG` (drop-in `KnowledgeGraph` facade) | SPEC-07 §1 | `cemaf/knowledge/hub_spoke.py` | landed |
| `create_hub_spoke_kg()` factory | SPEC-07 §2 | `cemaf/knowledge/hub_spoke.py` | landed |
| Composition-root wiring (`enable_hub_spoke_kg`) | SPEC-07 §1 | `cemaf/meta/bootstrap.py` | landed |

## Failure-feedback loop (SPEC-08)

| Spec concept | Source spec | Target module | Status |
|---|---|---|---|
| `FailureSignal` / `FailureItem` / `FailureKind` | SPEC-08 §2 | `cemaf/iteration/types.py` | landed |
| `IterationLimits` / `IterationOutcome` / `IterationReport` / `HaltSignal` | SPEC-08 §2 | `cemaf/iteration/types.py` | landed |
| `FailureParser` Protocol (specificity + max_items) | SPEC-08 §2 | `cemaf/iteration/protocols.py` | landed |
| `PytestParser` / `RuffParser` / `MypyParser` / `ShellFallbackParser` | SPEC-08 §2 | `cemaf/iteration/parsers.py` | landed |
| `IterationLoop` (attempt → verify → parse → re-attempt) | SPEC-08 §2 | `cemaf/iteration/loop.py` | landed |

> SPEC-08 is a per-task substrate, not a `RuntimeService` — the canonical caller is the `iccha_autonomy` control plane (per CLAUDE.md substrate boundary). It composes with, but does not replace, `core/recovery.AutoHealManager` (orthogonal failure surfaces: verifier `ShellResult` vs. Python exception).

## Auction-based agent selection (SPEC-09)

| Spec concept | Source spec | Target module | Status |
|---|---|---|---|
| `Capability` / `Fidelity` enums | SPEC-09 §2 | `cemaf/agents/selection.py` | landed |
| `BidContext` / `Bid` | SPEC-09 §2 | `cemaf/agents/selection.py` | landed |
| `CapabilityAdvertiser` (optional protocol) / `AgentSelector` | SPEC-09 §2 | `cemaf/agents/selection.py` | landed |
| `DefaultAgentSelector` (deterministic max-bid) | SPEC-09 §2 | `cemaf/agents/selection.py` | landed |
| Registry capability index + `get_candidates` | SPEC-09 §2 | `cemaf/agents/registry.py` | landed |
| `Node.auction(capability=...)` opt-in factory | SPEC-09 §2 | `cemaf/orchestration/dag.py` | landed |
| `AuctionResolver` dispatch + provenance (NodeResolver chain) | SPEC-09 §2, §9 | `cemaf/orchestration/resolvers/auction.py` | landed |
| `RuntimeServices.agent_selector` wiring | SPEC-09 §2 | `cemaf/orchestration/services.py`, `cemaf/bootstrap.py` | landed |
| ModelRouter fidelity floor (stops discarding `fidelity`) | SPEC-09 §3 Inv 9 | `cemaf/llm/model_router.py` | landed |

## Agent council (SPEC-10)

| Spec concept | Source spec | Target module | Status |
|---|---|---|---|
| `CouncilQuestion` / `Opinion` / `Ballot` / `CouncilDecision` / `CouncilConfig` | SPEC-10 §2 | `cemaf/council/types.py` | landed |
| `CouncilMember` / `VoteAggregator` protocols | SPEC-10 §2 | `cemaf/council/protocols.py` | landed |
| `DefaultVoteAggregator` (majority/weighted/quorum/unanimous) | SPEC-10 §2 | `cemaf/council/aggregator.py` | landed |
| `AgentCouncil` (concurrent, timed) + `create_agent_council` adapter; multi-round via `CouncilConfig.rounds` | SPEC-10 §2 | `cemaf/council/council.py` | landed |
| `Node.council` (incl. `rounds=N`) + `CouncilResolver` dispatch (output steers DAG) | SPEC-10 §2 | `cemaf/orchestration/dag.py`, `cemaf/orchestration/resolvers/council.py` | landed |
| `RuntimeServices.council_aggregator` wiring | SPEC-10 §2 | `cemaf/orchestration/services.py`, `cemaf/bootstrap.py` | landed |

## Production-grade autonomous context substrate (SPEC-17)

| Spec concept | Source spec | Target module | Status |
|---|---|---|---|
| `ArtifactRef`, `ArtifactRegistry` | SPEC-17 §2.2 | `cemaf/persistence/artifacts.py` | scaffold pending |
| `ContextManifest`, `WorkingContextReceipt` | SPEC-17 §2.2 | `cemaf/context/manifest.py` | scaffold pending |
| `AttemptLease`, `CheckpointEnvelope`, `NodeCommit` | SPEC-17 §2.3 | `cemaf/persistence/runtime.py` | scaffold pending |
| `RuntimeAuthority`, `DurabilityUnitOfWork`, `OutboxStore`, `OperationalProjection` | SPEC-17 §2.3 | `cemaf/persistence/runtime.py` | scaffold pending |
| `DurableRunCoordinator`, `DurableAttempt` | SPEC-17 §2.3 | `cemaf/orchestration/durable.py` | scaffold pending |
| `CompanionRuntime` | SPEC-17 §2.3 | `cemaf/orchestration/companion.py` | scaffold pending |
| `RuntimeServices.durable_execution` | SPEC-17 §2.3 | `cemaf/orchestration/services.py`, `cemaf/bootstrap.py` | scaffold pending |
| `EffectDeclaration`, `EffectDestination` | SPEC-17 §2.4 | `cemaf/tools/effects.py` | scaffold pending |
| `SchedulingLimits`, `BackpressurePolicy` | SPEC-17 §2.5 | `cemaf/scheduler/work_source.py` | scaffold pending |
| `AdapterCapabilityManifest`, `ProductionProfile` | SPEC-17 §2.6 | `cemaf/config/production_profile.py`, `cemaf/validation/profile.py` | scaffold pending |
| `EvidenceBundle`, `EvidenceVerifier`, `MaturityClaim` | SPEC-17 §2.7 | `cemaf/observability/evidence.py` | scaffold pending |

## Phase 2+ implementation plan

The map above is a target. The build-out is sequenced so each phase is independently mergeable and testable. Approximate ordering — phases may overlap when dependencies are satisfied.

| Phase | Scope | Gate |
|---|---|---|
| **Phase 1** (this doc) | Surface self-hosting + spec→module map | Docs land, reviewers sign off on trajectory |
| **Phase 2** | Scaffolding — empty Protocol files, type stubs, `__init__.py` exports for `interceptors/`, `datasources/`, `task/`, `guardian/`, `meta/dispatcher.py`. Add `NodeBudget`, `RunResult`, `RecoveryRequest` to `core/types.py`. Extend `RuntimeServices`. | All new modules import cleanly; mypy passes; no behavior changes |
| **Phase 3** | Interceptor pipeline (SPEC-01) — implement `NodeInterceptor`, `InterceptorPipeline`, `ChainProfile`. Wire into `ContextNodeExecutor` behind a feature flag. | Contract + integration tests prove PRE/POST ordering; default profile is no-op |
| **Phase 4** | Blueprint as LLM input (SPEC-03) — `BlueprintRequest[T]`, `StructuredGenerator`, `BlueprintInterceptor` (POST). | Round-trip test: typed request → structured response → validated payload |
| **Phase 5** | DataSources + KG (SPEC-02) — registry, `PullInterceptor`, eviction policy, KG adapter. | Pull interceptor hydrates a node's context from a registered source; eviction is deterministic across runs |
| **Phase 6** | Task state machine (SPEC-04) — `TaskRepository`, `AcquiredLease`, HITL pause/resume. | State transitions enforce SPEC-04 invariants; lease expiry reclaims orphaned tasks |
| **Phase 7** | Guardian mesh (SPEC-05) — six guardians as POST-interceptors, composed by `GuardianMesh`. | Each guardian has unit tests + a Gherkin scenario from SPEC-05 §4 |
| **Phase 8** | MetaDispatcher + self-resolving DAG (SPEC-06) — recovery routing, RECOVERY profile, audit-gated acceptance. | Failed node emits `RecoveryRequest`; dispatcher selects recovery DAG; audit gate blocks unsafe accepts |
| **Phase 9** | Audit-gate hardening + GATE evaluator SLOs (SPEC-00 §8) — promote OBSERVE evaluators to GATE once thresholds are stable. | All target evaluators in GATE mode with documented thresholds and incident playbooks |
| **Phase 10** | Production substrate foundation (SPEC-17) — reconcile task identity/leases, add evidence verifier and shared conformance harness, then coordinator/authority/context-manifest contracts. | SPEC-17 L0/L1 pass; one reference profile produces current invariant-addressed evidence before any production adapter is advertised |

Each phase ends with: (a) integration tests proving the seam, (b) updates to this map flipping rows from `scaffold pending` → `landed`, (c) any spec drift reflected back into SPEC-00..06.

## See also

- [`roadmap-plan.md`](roadmap-plan.md) — spec-driven sequencing + §10 test-coverage checklist for Phases 3–8
- [`docs/self-hosting.md`](../self-hosting.md) — meta-layer catalog and extension pattern
- [`docs/specs/SPEC-00`..`SPEC-06`](../specs/) — source specs
- [`CLAUDE.md`](../../CLAUDE.md) — project contract (architecture overview, module map, testing discipline)

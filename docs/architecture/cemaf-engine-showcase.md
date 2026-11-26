# CEMAF Engine Showcase

This design overview maps eight execution concerns onto CEMAF's modules and a
flagship request flow. The diagram preserves the July 2026 design proposal;
it includes proposed compositions and is not a promise that every service runs
by default. Module names describe ownership, not a request to replace existing
public protocols.

For the implemented execution path, read [Deep Architecture](deep-architecture.md).
For executable claims and their limits, use the
[Capability Evidence Ledger](../production-evidence.md). The
[spec-to-module map](spec-module-map.md) connects the design to its contracts.

## 1. Execution model

CEMAF runs a typed DAG through `create_executor` and `RuntimeServices`. Context,
budgets, gates, events, and memory compose at those public interfaces. The
executor controls dispatch and records outcomes; model responses and external
systems can still vary. Replay and provenance make those differences inspectable.

## 2. Flagship design diagram

The flow below describes the intended composition. Enable and configure the
relevant services explicitly; consult section 5 for implementation boundaries.

```
╔══════════════════════════════════════════════════════════════════════════════════════════════════════════════════╗
║                                    C E M A F   —   Context-Engineered Multi-Agent Framework                        ║
║      Thesis: a DETERMINISTIC, AUDITABLE control plane that spends tokens like money — priority-selected context,    ║
║      market-chosen agents, and a quality gate that genuinely BLOCKS bad output — through ONE composition root.      ║
╚══════════════════════════════════════════════════════════════════════════════════════════════════════════════════╝

LEGEND   ─▶ data/control flow    ═▶ per-node loop back    ┄▶ async event (fire-and-forget)    ⟲ self-hosting feedback
         [ CORE STAGE ]   « side rail / cross-cutting »   ✦ industry pain this stage KILLS   ⛔ blocks downstream

┌────────────────────────────────────────────────────── SIDE RAILS (cross-cutting, injected once, read everywhere) ──┐
│ «RuntimeServices DI»  ~20 frozen deps: llm · vector · memory · session · budget_guard · eval · council_agg ·        │
│                       interceptor_pipeline · knowledge_graph · agent_selector · blueprint_lib · tracer · event_bus  │
│ «EventBus pub/sub»    TASK_COMPLETED ┄▶ EVAL_COMPLETED ┄▶ QUALITY_ALERT ┄▶ MEMORY_EXTRACTED ┄▶ gate decisions       │
│ «Resilience»          retry × circuit_breaker × rate_limiter    «Budget/Cost»  per-run/per-workspace $ caps         │
│ «Memory»              semantic + episodic · TieredMemoryStore L0/L1/L2 · dedup · sqlite   «KG» hub-spoke bounded-LRU │
│ «Multi-tenant»        RBAC + ABAC · PII masking · MemoryScope SESSION/PROJECT/GLOBAL · SecurityLevel clearance gate  │
└─────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
        ║ injected                ║ subscribe                 ║ envelope                ║ scope/clearance
        ▼                         ▼                           ▼                        ▼
╭─────────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ (0) INGRESS  ──  bootstrap.create_executor(agent_registry, RuntimeServices(...)) ─▶ DAGExecutor                    │
│     data in: a typed DAG (Nodes+Edges, input_mapping) · initial Context · run_id · cancellation token             │
│     DAGExecutor.run(): set ContextVars(route_choices, correlation_id) ── concurrent runs never bleed state ──      │
│                        bootstrap memory Session · topological sort                                                 │
│     ✦ kills "agent loops nobody can reproduce" — the path is predictable, ordered, replayable BEFORE any LLM call  │
╰──────────────────────────────────────────────┬──────────────────────────────────────────────────────────────────╯
                                                │  ready node
                                                ▼
   ┌═══════════════════════════════════════════════════════════════════════════════════════════════════════════┐
   ║ (1) ORCHESTRATION DISPATCH  —  ContextNodeExecutor.execute_node  ▷  NodeResolver chain (first-match-wins)    ║
   ║                                                                                                             ║
   ║        ┌───────────────┐   no    ┌───────────────┐   no    ┌────────────────┐   no   ┌────────────────┐    ║
   ║   node─▶ CouncilResolver├───────▶ AuctionResolver ├───────▶ StaticRefResolver├──────▶│ <custom kind>  │    ║
   ║        └──────┬────────┘         └──────┬────────┘         └───────┬────────┘        └────────────────┘    ║
   ║           matches                    matches                    matches                                    ║
   ║     ✦ kills the "god-function of if-branches" — adding a node kind = registering a resolver, NOT a branch   ║
   └═════════════════════════════════════════════┬═══════════════════════════════════════════════════════════════┘
                                                  │  dispatch
                                                  ▼
   ┌───────────────────────────────────────────────────────────────────────────────────────────────────────────┐
   │ (2) INTERCEPTOR SPINE — PRE PHASE     InterceptorPipeline:  PRE ─▶ execute ─▶ POST  (every AGENT node)        │
   │     ┌─────────────────────┐  ┌─────────────────────┐  ┌───────────────────────┐                            │
   │     │ PullInterceptor      │  │ RBAC + SecurityLevel │  │ BudgetGuard cap check  │  DecisionKind here?        │
   │     │ hydrate ctx from     │─▶│ clearance gate       │─▶│ BEFORE any spend       │──▶ REJECT ⛔ short-circuit  │
   │     │ DataSource reg / KG  │  │ (drop over-clearance)│  │ else ACCEPT            │    (zero LLM cost)         │
   │     └─────────────────────┘  └─────────────────────┘  └───────────────────────┘                            │
   │     ✦ kills "eval runs after the fact" — access + budget are enforced on the WAY IN, not post-mortem         │
   └───────────────────────────────────────────────┬───────────────────────────────────────────────────────────┘
                                                    ▼
   ┌───────────────────────────────────────────────────────────────────────────────────────────────────────────┐
   │ (3) CONTEXT ECONOMICS ENGINE  —  spend tokens like money                                                     │
   │                                                                                                              │
   │   MemoryManager.recall ─┐   VectorStore retrieval ─┐   DataSource pulls ─┐   prior turns / domain facts ─┐   │
   │   (tiered L0/L1/L2)      │   (kNN candidates)       │   (SPEC-02)         │   (each: scope+tier+PROVENANCE)│   │
   │                         ▼                          ▼                     ▼                              ▼   │
   │              ┌────────────────────────── ContextCompiler ──────────────────────────────────┐               │
   │              │  select against node TokenBudget:                                            │               │
   │              │   1 hard invariants (NEVER dropped) → 2 goal+contract → 3 domain facts →      │               │
   │              │   4 recent turns → 5 memory → 6 examples   (drop BOTTOM-UP under budget)      │               │
   │              │   dedup applied · PII masked · token accounting emitted                       │               │
   │              └───────────────────────────────┬──────────────────────────────────────────────┘               │
   │                                CompiledContext slice ─▶ becomes the PROMPT                                   │
   │     ✦ kills "prompt-string state layer / context-window blowup / paying for redundant context"               │
   └───────────────────────────────────────────────┬───────────────────────────────────────────────────────────┘
                                                    ▼
   ┌───────────────────────────────── (4) NODE EXECUTION — the resolver runs ──────────────────────────────────┐
   │                                                                                                            │
   │  ┌─── STATIC ────────────┐   ┌─── AUCTION (SPEC-09) ─────────┐   ┌─── COUNCIL (SPEC-10) ────────────────┐  │
   │  │ named agent runs       │   │ candidates advertise Capability│   │ N members deliberate (concurrent,    │  │
   │  │                        │   │ + Fidelity → BidContext(load,  │   │ timed, multi-round)                  │  │
   │  │                        │   │ cost, fidelity)                │   │   member₁ ┐                          │  │
   │  │                        │   │ DefaultAgentSelector: max-bid  │   │   member₂ ├▶ DefaultVoteAggregator   │  │
   │  │                        │   │ (DETERMINISTIC) → winner runs  │   │   memberₙ ┘  majority/weighted/      │  │
   │  │                        │   │ bid provenance ▶ metadata      │   │              quorum/unanimous        │  │
   │  │                        │   │                                │   │ CouncilDecision steers edges;        │  │
   │  │                        │   │                                │   │ full ballot recorded (or ∅=success)  │  │
   │  └───────────┬────────────┘   └──────────────┬─────────────────┘   └──────────────┬───────────────────────┘  │
   │              └───────────────────────────────┴─────────────────────────────┬──────┘                          │
   │                          agent works over ▷ Skills / ShellSandbox (cwd-confined, net-screened, env-scrubbed)  │
   │                          model chosen by ▷ ModelRouter (complexity + fidelity FLOOR) inside ResilientLLMClient│
   │                                            (retry × circuit_breaker × rate_limiter × BudgetGuard)             │
   │     ✦ kills "single brittle opaque model, hardcoded 'use GPT-x here', unbounded cost blast radius"            │
   └───────────────────────────────────────────────┬───────────────────────────────────────────────────────────┘
                                                    │  produced output + citations
                                                    ▼
   ┌═══════════════════════════════════ (5) INTERCEPTOR SPINE — POST PHASE = QUALITY GATE MESH ══════════════════┐
   ║                                                                                                             ║
   ║   GateEvalInterceptor ▷ HierarchicalJudge:  tier1 deterministic ─▶ tier2 semantic ─▶ tier3 LLM judge        ║
   ║                                              (against declared SLO thresholds)                              ║
   ║   ┌── SIX GUARDIANS (POST, SPEC-05) ──────────────────────────────────────────────┐  + moderation safety   ║
   ║   │ CiteOrFail · UngroundedClaim · Schema · Policy · Hallucination · Calibration    │  + Blueprint validate  ║
   ║   └─────────────────────────────────────────────────────────────────────────────────┘    & REPAIR (SPEC-03)║
   ║                                                                                                             ║
   ║          VERDICT ┬─▶ ACCEPT   ─▶ downstream proceeds                                                        ║
   ║                  ├─▶ REJECT   ⛔ downstream NEVER runs — genuinely blocks, retries NOT burned                ║
   ║                  └─▶ RECOVER  ↺ bounded re-attempt w/ RecoveryHints (≤ max_recovery_attempts)               ║
   ║                                  on exhaustion → recovery-exhausted metadata stamped                       ║
   ║     ✦ kills "unvalidated hallucinations / schema-breakers / policy violations shipping straight to users"   ║
   ╚═══════════════════════════════════════════════┬═══════════════════════════════════════════════════════════┘
                                        ACCEPTED    │                            REJECT ⛔  ─────────┐
                                                    ▼                                               │
   ┌───────────────────────────────────────────────────────────────────────────────────────────┐  │
   │ (6) COLLISION-FREE CONCURRENCY COORDINATOR (SPEC-12) — for parallel nodes writing ctx paths │  │
   │     risk.py: TCAS-style pure-math overlap risk  ▷  coordinator: DETERMINISTIC resolution     │  │
   │     lower-priority writer DEFERS/steers · higher-priority HOLDS  → no last-write-wins corrupt│  │
   │     ✦ kills "parallel agents silently clobber shared state; nondeterministic to debug"       │  │
   └───────────────────────────────────────────────┬───────────────────────────────────────────┘  │
                                                    ▼                                               │
   ┌───────────────────────────────────────────────────────────────────────────────────────────┐  │
   │ (7) CONTEXT WRITE-BACK & EVENTS                                                             │  │
   │     NodeResult ─▶ Context.set() (deep-copied → immutable)   next node reads via input_mapping│  │
   │     EventBus publish ┄▶ TASK_COMPLETED ┄▶ EVAL_COMPLETED ┄▶ QUALITY_ALERT                     │  │
   │        async subscribers:  audit → AuditEntry · citations tracked · TrustLedger updates tool │  │
   └───────────────────────────────────────────────┬═══════════════════════════════════════════┘  │
                                                    ║  ═▶ LOOP BACK to (1) until DAG drains          │
                                                    ▼   ◀════════════════════════════════════════════┘ (rejected: edge dead)

    ┌──────────────────────── PROVENANCE & AUDIT LEDGER (fed continuously by ┄▶ events) ──────────────────────────┐
    │ audit/  append-only AuditTrail + z-score quality-anomaly detection                                          │
    │ citation/  cited_evidence_refs ⊆ surfaced sources  (every claim maps to a real source)                      │
    │ trust/  TrustLedger: each tool/skill  UNTRUSTED ▶ SANDBOXED ▶ TRUSTED / DEPRECATED  by observed outcomes     │
    │ observability/  StructuredLogger JSON lines + OTel GenAI spans  ── all queryable, exportable                 │
    │ ✦ kills "can't explain the answer / no forensics / no compliance trail"                                      │
    └─────────────────────────────────────────────────────────────────────────────────────────────────────────┘
                                                    │  on DAG drain
                                                    ▼
   ┌────────────────────────── (8) HARVEST & SELF-IMPROVEMENT FLYWHEEL ⟲ ───────────────────────────────────────┐
   │  create_blueprint_harvester(): high-scoring run ─▶ distilled reusable Blueprint (PROJECT ▶ GLOBAL promotion) │
   │                                 discoverable via library.search  (next run starts from a proven pattern)     │
   │  SelfImprovementLoop:  score run ─▶ update StrategyMemory + TrustLedger ─▶ flag underperformers → regenerate │
   │  KG refresh (hub-write / spoke-read bounded-LRU)                                                             │
   │  ✦ kills "static systems that never improve; failures don't feed back; good runs aren't captured"            │
   └───────────────────────────────────────────────┬───────────────────────────────────────────────────────────┘
                                                    ▼
   ┌────────────────────────── (9) AUDIT / OPERATOR OBSERVATORY ────────────────────────────────────────────────┐
   │  finally: dispose Session → post-session extraction promotes SESSION ▶ PROJECT memory; reset ContextVars     │
   │  operator/snapshot.py projects RunRecord + ExecutionResult ─▶  cemaf.session.v1  SessionSnapshot             │
   │            (the ONE versioned public contract every surface reads: CLI · service · MCP · benchmarks)         │
   │  replay/ + checkpointer (keep-N pruned) → resumable, reproducible traces                                     │
   │  ✦ kills "black-box runs, no repro, tooling coupled to churning internal dataclasses"                        │
   └───────────────────────────────────────────────┬───────────────────────────────────────────────────────────┘
                                                    ▼
   ╔═══════════════════════════════════════════════════════════════════════════════════════════════════════════╗
   ║ (10) RESULT — DAGExecutor returns ExecutionResult:  per-node NodeResults · final Context · route choices ·    ║
   ║               run status  =  a fully AUDITED, COST-BOUNDED, QUALITY-GATED, REPRODUCIBLE trace.               ║
   ╚═══════════════════════════════════════════════════════════════════════════════════════════════════════════╝

   ⟲──────────────────────────────── SELF-HOSTING META LAYER (CEMAF is its own first client) ────────────────────────⟲
   │  create_meta_executor() WRAPS the exact same flow above — no special execution path:                          │
   │    MetaArchitect ─▶ MetaSynthesizer ─▶ MetaAuditor ─▶ MetaKnowledgeGraph ─▶ MetaSpecifier ─▶ MetaScaffolder    │
   │    DAGs: self_audit · feature_synthesis · knowledge_refresh · app_synthesis                                   │
   │  Meta-agents are ordinary Agent/Tool/DAG citizens → they introspect, audit, and EXTEND the engine itself,     │
   │  reading the same AuditTrail (9) and Blueprints (8) this run just produced. The flywheel closes. ⟲───────────▶│
   └───────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

## 3. Component map

The eight components group related responsibilities. They do not introduce new
packages or a second orchestration loop. Stage numbers refer to the diagram.

| Component | Responsibility | Stages | Existing modules |
|---|---|---|---|
| Context selection | Select relevant evidence within a token budget | 3 | `context`, `memory`, `retrieval`, `rlm` |
| Orchestration | Dispatch DAG nodes, coordinate writes, checkpoint execution | 0, 1, 6 | `orchestration`, `collision`, `state` |
| Agent selection | Select candidates or aggregate council decisions | 4 | `agents`, `council`, `llm` |
| Quality gates | Validate outputs and block or recover failed steps | 2, 5 | `interceptors`, `evals`, `moderation`, `validation` |
| Provenance and audit | Record sources, patches, events, and run outcomes | 7, 9 | `audit`, `citation`, `observability`, `operator`, `replay` |
| Budget and resilience | Account for usage and bound retries or spending | 4 and shared services | `observability`, `resilience`, `cache` |
| Access control | Apply principal, scope, attribute, and clearance policies | 2 and shared services | `security`, `memory`, `context` |
| Self-hosting | Inspect the framework and reuse reviewed run artifacts | 8 and meta layer | `meta`, `blueprint`, `iteration`, `knowledge` |

### Context selection

`ContextCompiler` assembles `ContextSource` inputs under a `TokenBudget`.
Memory and retrieval supply candidates; policies determine priority and
clearance. Oversized research can use the existing RLM decomposition path.
A token budget controls input size; evidence quality still needs separate evals.

### Orchestration

`DAGExecutor` delegates through resolvers and node handlers. `RuntimeServices`
holds shared dependencies, while run-scoped state isolates concurrent calls.
Checkpoint and lease implementations determine recovery guarantees. A local
executor alone does not establish distributed durability.

### Agent selection

Auction selection ranks registered candidates; council nodes collect and
aggregate votes. These are alternative dispatch policies over the same agent
contracts. Record the selection and evaluate the result: consensus alone does
not establish correctness.

### Quality gates

The interceptor pipeline supports ACCEPT, REJECT, and bounded RECOVER decisions.
Applications choose evaluators, thresholds, validation, and moderation policies.
The six-guardian composition in the diagram is a design target, not an implicit
service enabled for every run.

### Provenance and audit

Context patches, citations, events, run logs, replay records, and operator
snapshots expose what a run consumed and produced. Audit storage and retention
are deployment choices. In-memory records last for the process lifetime;
external publication requires the application's evidence and authorization gates.

### Budget and resilience

Budget guards and instrumented clients account for observed usage. Retry,
circuit-breaker, rate-limiter, and cache protocols govern provider calls.
Configure these at the composition root and include repair or retry usage in
the budget. An uninjected service cannot enforce a policy.

### Access control

RBAC/ABAC memory decorators evaluate principals, actions, scopes, and attributes;
context compilation can filter sources by clearance. The application must
provide identities, policies, and trusted scope bindings. Files exported as OKF
need destination access controls too: importing a policy description grants no
runtime permissions.

### Self-hosting

`create_meta_executor` composes framework-aware agents through the same DAG
execution path. Blueprint harvesting and improvement services can propose
reusable artifacts; promotion remains subject to policy and review.
[OKF self-hosting](../okf.md#cemaf-describing-itself) exports modules, contracts,
registered capabilities, and governed descriptions for agents to inspect through
the existing documentation and knowledge-graph interfaces.

## 4. Composition and verification

Start with the [composed engine example](../../examples/composed_engine.py) or
[release engine example](../../examples/release_engine.py). Supply protocol
implementations through `RuntimeServices`, register domain agents and tools,
and express the flow as a DAG. Extend a resolver, interceptor, or event
subscriber when that interface owns the behavior.

Use integration evidence to assess the composition:

- [Composed engine](../../tests/integration/test_composed_engine.py) checks the
  shared execution path across subsystems.
- [Durable resume](../../tests/integration/test_runtime_services_durable_resume.py)
  checks the configured checkpoint and recovery path.
- [OKF self-hosting](../../tests/integration/test_okf_self_hosting.py) checks
  exported framework knowledge, runtime contracts, and governed access.

These tests support specific configurations. They do not establish universal
production suitability or comparative performance against other frameworks.

## 5. Implementation boundaries

| Design element | Boundary |
|---|---|
| DAG, resolver, and interceptor execution | Implemented; behavior depends on registered handlers and injected services. |
| Context compilation, auction, council, and blueprint harvesting | Available through public protocols; configure each required path explicitly. |
| Six-guardian default composition | Proposed composition; do not assume automatic injection. |
| Durable task ownership and distributed recovery | Use the [durability plan](enterprise-durability-plan.md) and its acceptance evidence for the current boundary. |
| Audit retention | In-memory and durable backends have different lifetimes and failure guarantees. |
| Regrouping `RuntimeServices` into smaller bundles | Design suggestion, not a required API migration. |
| Peer messaging and communal task board | [SPEC-18](../specs/SPEC-18-peer-communication-and-task-board.md) defines the phased design; the phase-one identity substrate does not imply the whole board is implemented. |
| OKF ontology and policy descriptions | The CEMAF vocabulary profile versions local terms; Git tracks content history. Runtime policy enforcement remains separate. |

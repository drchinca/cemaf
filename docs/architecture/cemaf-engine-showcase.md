# CEMAF Engine — The Best-in-Class Context-Engineered Multi-Agent Substrate

> High-level engine anatomy. No code — *what* the top-tier shell components are, *how* a
> request flows through them, and *why* this is the framework a serious team picks for 2027+.
> For where each concept lands in the codebase, see [`spec-module-map.md`](spec-module-map.md).

## 1. The one-line thesis

**CEMAF is a deterministic, auditable control plane for multi-agent AI that spends tokens
like money** — it wraps stochastic models inside a predictable, replayable execution spine
where context is priority-selected against a budget, agents are chosen by market or council,
and a quality gate genuinely *blocks* bad output before it ships.

The frontier problem has moved from "can a model do the task?" to "can you run models at
enterprise scale — cost-bounded, provenance-native, quality-gated, multi-tenant-safe —
through *one* composition root you can reproduce and audit?" CEMAF is that substrate: an
engine that owns control flow and invokes your agents, not a library your agents call.

## 2. The flagship diagram

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

## 3. The top-tier shell components

Eight components, each owning one industry-scale failure mode of production LLM systems.
Together they form the execution substrate, not a toolkit. Stage numbers map to the diagram.

| # | Shell component | Owns the pain of… | Diagram | CEMAF modules |
|---|---|---|---|---|
| 1 | **Context Economics Engine** | rolling-prompt state layers that blow windows & pay for redundant tokens | (3) | `context/`, `memory/`, `retrieval/`, `rlm/` |
| 2 | **Deterministic Orchestration Spine** | agent loops nobody can reproduce; god-function of `if`-branches | (0)(1)(6) | `orchestration/`, `collision/`, `state/` |
| 3 | **Agent Decision Market** | brittle single-model answers; hardcoded "use model-X here" | (4) | `agents/selection.py`, `council/`, `llm/model_router.py` |
| 4 | **Quality Gate Mesh** | hallucinations/schema-breakers shipping; evals that only *report* | (2)(5) | `interceptors/`, `evals/`, `moderation/`, `blueprint/` |
| 5 | **Provenance & Audit Ledger** | AI you can't explain; no forensics, no compliance trail | (7)(9) | `audit/`, `citation/`, `observability/`, `operator/`, `replay/` |
| 6 | **Cost Governance & Resilience Envelope** | unbounded cost blast radius; one flaky provider cascading to outage | rails+(4) | `observability/` (BudgetGuard), `resilience/`, `cache/` |
| 7 | **Multi-Tenant Isolation & Access Control** | cross-tenant leakage (P0 deal-killer); PII into prompts/logs | rails+(2) | `context/` (SecurityLevel), `memory/` (scope), security decorators |
| 8 | **Self-Hosting Improvement Flywheel** | static systems that never improve; good runs never captured | (8)+meta | `meta/`, `blueprint/harvest.py`, `iteration/`, `knowledge/` |

### 3.1 Context Economics Engine — stage (3)

- **Problem it owns:** teams use rolling prompt strings as their state layer — they blow
  context windows, pay for redundant tokens, and watch quality degrade as prompts bloat.
- **What it does:** turns a pile of candidate context (memory, vectors, datasource pulls,
  prior turns, domain facts) into a budget-fitting `CompiledContext` slice.
- **How:** `ContextCompiler` selects against a declared `TokenBudget` by priority tier — hard
  invariants first, nice-to-haves dropped bottom-up — over tiered `MemoryManager.recall`,
  `VectorStore` retrieval, and SPEC-02 `PullInterceptor` hydration; dedup + PII masking
  applied; every source carries a `ContextPatch` provenance stamp; `rlm/` handles oversized
  context by divide-and-conquer.
- **Why best-in-class 2027+:** as windows grow to millions of tokens, the constraint stops
  being *capacity* and becomes *economics* — cost, latency, signal-to-noise. A principled,
  provenance-aware, budget-first selection layer scales context instead of drowning in it.

### 3.2 Deterministic Orchestration Spine — stages (0)(1)(6)

- **Problem it owns:** stochastic models produce nondeterministic control flow no one can
  reproduce, replay, or audit; every new step means editing a god-function of `if`-branches.
- **What it does:** executes a typed DAG over an initial context, producing a
  topologically-ordered, checkpointed, resumable trace.
- **How:** `DAGExecutor.run` topologically sorts and dispatches each node through the
  `NodeResolver` chain (council/auction/static, first-match-wins) — adding a node kind is
  *registering a resolver*, never a branch; `RuntimeServices` injects deps at one composition
  root; `ContextVars` isolate route choices + correlation IDs so concurrent runs never bleed;
  the collision coordinator (TCAS-style risk math) deterministically resolves overlapping
  parallel writes; `run_lease` + `file_checkpointer` make runs resumable.
- **Why best-in-class 2027+:** the industry is converging on *auditable* control planes. A
  resolver-dispatched, deterministic, replayable spine — where model output can steer edges
  but never the mechanics of execution — satisfies both flexibility and compliance.

### 3.3 Agent Decision Market — stage (4)

- **Problem it owns:** single-model, single-agent answers are brittle and opaque — no
  consensus, no right-fidelity/right-cost selection per task, no record of *why*.
- **What it does:** resolves a node either by auctioning it to the best-fit agent or convening
  a council that deliberates and votes.
- **How:** Auction (SPEC-09) — agents submit `Bid`s against a `BidContext` (load/cost/
  fidelity), `DefaultAgentSelector` picks deterministic max-bid, provenance stamped. Council
  (SPEC-10) — N members deliberate over multi-round `CouncilConfig`, `DefaultVoteAggregator`
  (majority/weighted/quorum/unanimous) tallies a full `Ballot`, `CouncilDecision` steers
  edges; `model_router.py` cost-routes on complexity with a fidelity floor.
- **Why best-in-class 2027+:** with dozens of specialized models and price/quality tiers,
  static model assignment is malpractice. A deterministic, accountable *market* — every
  selection explainable, every dissent recorded — earns trust at enterprise scale.

### 3.4 Quality Gate Mesh — stages (2)(5)

- **Problem it owns:** unvalidated stochastic output ships straight to users; bolt-on eval
  scripts run *after* the fact without actually blocking anything.
- **What it does:** runs every agent node's output through a PRE→POST interceptor chain that
  can genuinely block bad output from flowing downstream.
- **How:** `InterceptorPipeline` (SPEC-01a) wraps execution; `GateEvalInterceptor` runs the
  `HierarchicalJudge` (deterministic → semantic → LLM judge) against declared SLO thresholds;
  six guardians (CiteOrFail, UngroundedClaim, Schema, Policy, Hallucination, Calibration —
  SPEC-05), moderation, and structured-output repair (SPEC-03) run POST. Verdict is `ACCEPT`,
  `REJECT` (downstream never runs, retries not burned), or `RECOVER` (bounded re-attempt).
- **Why best-in-class 2027+:** the cost of shipped hallucination is only rising. A gate that
  *blocks in the execution path* — not a dashboard after the fact — is the enforcement
  primitive every serious AI product needs; as interceptors, quality is a station, not an
  afterthought.

### 3.5 Provenance & Audit Ledger — stages (7)(9)

- **Problem it owns:** enterprises can't ship AI they can't explain — why did the model say
  this, from what sources, which tool ran, is that tool reliable?
- **What it does:** turns the event stream of a run into an append-only, queryable record of
  what happened, what it was grounded on, and how trustworthy each participant is.
- **How:** `audit/` projects events into `AuditEntry` records with z-score anomaly detection;
  `citation/` enforces `cited_evidence_refs ⊆ surfaced sources`; the `TrustLedger` promotes/
  demotes tools by observed outcomes; everything exports via OTel GenAI spans and projects
  into the versioned `cemaf.session.v1` `SessionSnapshot` (SPEC-14) — the one read-only
  contract every surface reads, plus `replay/` traces.
- **Why best-in-class 2027+:** AI governance regimes demand provenance as a shipping
  requirement. An immutable citation graph plus a behavior-earned trust ledger — through one
  stable public contract — is exactly the forensics surface auditors ask for.

### 3.6 Cost Governance & Resilience Envelope — side rails + stage (4)

- **Problem it owns:** unbounded cost blast radius — one runaway loop burns thousands of
  dollars, one flaky provider cascades into an outage.
- **What it does:** enforces hard per-run/per-workspace spend limits and keeps calls alive
  through transient failures while routing each task to the cheapest viable model.
- **How:** `BudgetGuard` caps spend, raises typed `BudgetExceeded` (never silent truncation),
  emits `cost_usd` + tokens tagged by workspace/adapter/tier; `resilience/` wraps every call
  in retry + circuit breaker + rate limiter; `model_router.py` picks the cheapest model that
  clears complexity + fidelity floor; `cache/` TTL-dedupes repeated work.
- **Why best-in-class 2027+:** as agents run longer and fan out wider, cost is the dominant
  operational risk. First-class per-tenant budgets that *stop* overspend, paired with
  resilience and complexity-aware routing, make autonomous agents financially safe to deploy.

### 3.7 Multi-Tenant Isolation & Access Control — side rails + stage (2)

- **Problem it owns:** cross-tenant data leakage is a P0 that kills enterprise deals — shared
  memory/context/caches, PII into prompts and logs, no scope-level access control.
- **What it does:** returns only the scoped, PII-masked context a principal is cleared to see
  — or denies the request — recording every decision.
- **How:** RBAC + ABAC via memory-store decorators and PII redaction; `MemoryScope` (SESSION/
  PROJECT/GLOBAL) with hierarchical `ScopePath` namespacing state per workspace;
  `SecurityLevel` clearance-gated compilation (SPEC-11) drops any over-classified source
  before it reaches the prompt; every access decision lands in the audit ledger.
- **Why best-in-class 2027+:** enterprise AI buying is gated on isolation guarantees.
  Clearance-gated *context compilation* — where over-classified data is structurally incapable
  of reaching a prompt — is stronger than perimeter access control, and unlocks regulated
  deals.

### 3.8 Self-Hosting Improvement Flywheel — stage (8) + meta layer

- **Problem it owns:** static AI systems never get better — pipelines are hand-designed,
  failures don't feed back, high-scoring runs aren't captured.
- **What it does:** uses the engine's own execution to distill high-scoring runs into reusable
  blueprints and update strategy/trust from outcomes and verifier failures.
- **How:** `meta/` agents run as ordinary Agent/Tool/DAG citizens through
  `create_meta_executor` — the *same* executor, no special path; `create_blueprint_harvester()`
  (SPEC-13) learns blueprints from high-scoring runs with PROJECT→GLOBAL promotion;
  `SelfImprovementLoop` scores runs into `StrategyMemory` + `TrustLedger`; `iteration/`
  (SPEC-08) parses pytest/ruff/mypy failures into `FailureSignal`s for bounded re-attempts;
  the hub-and-spoke KG (SPEC-07) stays refreshed.
- **Why best-in-class 2027+:** the frontier is self-improving systems. An engine that improves
  *through its own primitives* — no bespoke ML pipeline, every improvement step itself audited,
  budgeted, gated — is a compounding asset where competitors ship a static artifact.

### Why this is an engine, not a library

A library is helpers you call from control flow *you* own; an engine owns the control flow and
invokes *you*. There is exactly one composition root (`bootstrap.create_executor`) and one
path (`DAGExecutor.run`) through which every request flows. Every capability above is a
**station on that path**, not an optional import: context is compiled against a budget before a
prompt exists, spend and clearance are checked before a call fires, output is gated before it
flows downstream, provenance is emitted as it happens, the run improves itself on completion.
Adding a capability is registering a resolver or interceptor, never editing a god-function;
even the self-hosting meta layer wraps this exact same flow with no privileged path. That
inversion of control — correctness, cost, safety, and auditability as structural invariants of
the substrate rather than conventions a caller must remember — is what makes it an engine.

## 4. Why this wins in 2027+

Five compounding advantages no incumbent holds *together*:

1. **Deterministic orchestration over stochastic models** — LLM output steers edges (votes,
   bids, routes) but never the mechanics; the path is sorted, dispatched, checkpointed,
   replayable *before a token is spent*. LangGraph leaves determinism/replay/audit to you;
   CrewAI/AutoGen lean into the free-form chatter that *is* the unreproducible loop.
2. **Provenance-native context economics** — context as a budgeted asset, priority-dropped
   bottom-up, every source stamped, PII masked on the way in. DSPy optimizes prompts but has
   no runtime context-economics; the others use rolling strings.
3. **Eval-as-a-gate, not eval-as-a-report** — REJECT means downstream never runs and retries
   aren't burned. Agents-SDK/CrewAI offer advisory guardrails; CEMAF makes them load-bearing.
4. **Self-hosting flywheel** — meta-agents run through the *same* executor to introspect,
   audit, harvest blueprints, regenerate underperformers — each step itself audited, budgeted,
   gated. Competitors ship a static artifact.
5. **Collision-free multi-tenant concurrency** — TCAS-style deterministic write coordination +
   clearance-gated compilation that makes over-classified data *structurally unable* to reach a
   prompt.

**The synthesis:** LangGraph, CrewAI, AutoGen, DSPy, and the Agents-SDK each solve a *slice* —
graph wiring, role-play ergonomics, conversational agents, prompt optimization, a hosted loop.
None owns the whole governed control plane: deterministic and replayable, provenance-native and
budgeted, gated in-path, self-improving, multi-tenant-safe — through one composition root. That
is not a feature you add to a library later; it is an architecture you commit to on day one.
For any organization that must run AI it can *explain, afford, trust, and improve* at enterprise
scale, that is the durable moat.

## 5. Honesty layer — shipped today vs. CEMAF-V2 target

The diagram paints the *target* engine. Some stations are genuinely wired and verified; a few
are named but not yet built. A redo is honest about the difference.

| Element | Status | Note |
|---|---|---|
| Interceptor spine (PRE→execute→POST, ACCEPT/REJECT/RECOVER) | 🟢 shipped, verified-wired | The keystone; `GateEvalInterceptor` genuinely blocks downstream. |
| DAG kernel + NodeResolver chain + immutable Context | 🟢 shipped | Concurrency-tested; resolver chain replaces `if`-branches. |
| Context compiler (priority + token budget + provenance) | 🟢 shipped | `surfaced_sources` should graduate to a first-class `Context` field. |
| Auction / council / blueprint | 🟡 shipped as packages | Should collapse into resolvers/stations, not top-level packages. |
| Cost governance + resilience + model router | 🟢 shipped | `BudgetGuard`, retry/breaker/limiter, complexity routing all real. |
| Multi-tenant clearance-gated compilation (SPEC-11) | 🟢 shipped | RBAC/ABAC decorators + `SecurityLevel` gate. |
| **Guardian Mesh** (auto-inject six guardians in order) | ⚪ **new** | Primitives exist; nothing composes them by default yet. |
| **Durable Task aggregate** (state machine + step ledger + lease) | ⚪ **new** | FSM/lease/checkpointer substrate ships; `cemaf/task/` coordination does not. |
| `DistributedDAGExecutor` | 🔴 **rename/replace** | Single-process behind an unused `redis_url`; ship a real `QueuePort` adapter *or* name it honestly. |
| `InMemoryAuditTrail` as shipped default | 🔴 **replace** | A process-lifetime audit trail is not an audit trail; fold into a durable Replay & Audit Vault. |
| Regex-only "moderation" / template-fill "synthesis" | 🔴 **rename/fold** | Ship a BYO LLM-moderation adapter; demote mechanical "synthesis" to an honestly-named scaffolder. |
| 20-field `RuntimeServices` | 🟡 **regroup** | Split into intent-named sub-bundles (observability / quality / knowledge / governance). |

**The V2 north star, in one line:** *CEMAF-V2 is the provenance-native, durable-execution
substrate for auditable multi-agent systems — a run is a resumable Task, every token the model
saw is a ledgered fact, every claim it emits is checked against a membership set, and every
cross-cutting concern is one ordered station on a single interceptor spine.*

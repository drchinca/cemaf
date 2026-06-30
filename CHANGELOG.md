# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [2.3.0] - 2026-06-30

**Runnable examples, a self-guarding example harness, and an empirical value eval for the agent-assisted guidance.**

No public `src/cemaf/` API changed; this is additive — new examples, tests, and a benchmark.

**Added:**
- **BYO-X examples** (`examples/byo/`) — implement `LLMClient`, `VectorStore`, `MemoryStore` against the real protocols and wire each through its factory.
- **App-shape examples** (`examples/app_shapes/`) — grounded RAG with citations, and a tool-using agent that self-heals a transient failure via `@with_retry` inside a DAG.
- **Context-layer examples** (`examples/context_layers/`) — the namesake capability surfaced as focused PoCs: memory scope hierarchy (GLOBAL/TENANT/SESSION), typed `ContextSource` layers dropped by priority under a `TokenBudget`, and the full provenance → `Context` → priority-compile → budgeted-prompt pipeline.
- **Anti-pattern catalog** (`examples/anti_patterns/`) and an indexed `examples/README.md` on-ramp.
- **Universal example smoke harness** (`tests/integration/test_examples_smoke.py`) — auto-discovers and runs every `examples/**/*.py` offline; opt-out via `smoke_skip_reason()` (the Ollama examples run when a daemon is reachable, skip with a reason otherwise).
- **Self-healing integration tests** — citation self-healing, model-fidelity escalation, the self-healing+harvest triad, cooperative quality halting, and a council iterative-remediation loop.
- **Guidance-value eval** (`benchmarks/guidance_eval/`) + a regression gate (`tests/integration/test_guidance_value.py`) — A/B measures whether the agent-assisted docs shift an LLM from reinventing infrastructure to composing CEMAF.

**Changed:**
- Example source is now git-tracked (`.gitignore` whitelists `examples/**/*.py` and `*.md` while keeping generated artifacts ignored), so examples render on GitHub and are grep-able by coding agents.
- `CLAUDE.md` and `AGENTS.md` point at the agent-assisted guidance and the new examples.

**Fixed:**
- `docs/AI_DEVELOPMENT_GUIDE.md` referenced a non-existent `cemaf.guardian` module for content safety; corrected to `cemaf.moderation` wired via `cemaf.interceptors`.

## [2.2.0] - 2026-06-12

**README polish: rich-text dual-DAG framing + industry-standards table.**

No source code in `src/cemaf/` changed in this release; the package surface is identical to 2.1.0.

**Changed:**
- Removed two AI-feeling screenshots (`docs/architecture/img/dag-showcase.png` and `architecture-atlas.png`) from the README. Replaced with rich-text:
  - **The dual DAG · agents on top, context below** — ASCII rendering of the agent-lane / context-lane / recover-lane structure with a one-line summary of the structured-event stream emitted per `executor.run(dag)` call.
  - **What CEMAF makes the industry standard** — 9-row table mapping the hard problems the agentic-AI ecosystem keeps re-solving (token budget, citation grounding, agent selection, council voting, recover loop, observability, BYO-X integration, blueprint flywheel, framework boundary) to the CEMAF primitive that solves each as a first-class node-kind or `Protocol` rather than glue code.
- Architecture Atlas image swapped for a quoted text pointer — same link target, less visual noise.

**Reverted:**
- README architecture diagram is back to ASCII box-drawing (was briefly Mermaid in 2.1.0). The Mermaid render read as AI-generated; ASCII matches the rest of the README's voice.

## [2.1.0] - 2026-06-12

**Investor-ready interactive showcase + real CEMAF trace generator + docs cleanup.**

No source code in `src/cemaf/` changed in this release; the package surface is identical to 2.0.0. The `2.1.0` minor bump reflects the *new runnable demo capability* added under `docs/architecture/`.

**Added:**
- **Interactive DAG showcase** at `docs/architecture/cemaf-graph.html` — two tabs: AST-exact module dependency graph (40 modules, 167 imports) and an animated dual-DAG demo with 11 agents, 7 context surfaces, checkpoints, recover band, counterfactual toggles, event-kind summary, OTel-shape audit ticker. Works on `file://` (no server needed).
- **Real CEMAF trace generator** at `docs/architecture/scripts/produce_dag_trace.py` — runs CEMAF end-to-end via `executor.run(dag)` for 7 progressive scenarios (`hello → chain → parallel → council → auction → gate → full flow`). Captures `EventBus` output via `subscribe_all` and writes structured JSON traces (`docs/architecture/traces/step-1.json`…`step-7.json` + `index.json`). Step 7 produces 26 real events in 537ms with zero failures. Traces are inlined into the showcase so the demo is verifiable, not mocked.
- **Architecture Atlas** at `docs/architecture/cemaf-architecture.html` — interactive multi-view tour with every module placed by measured import fan-in.
- **README hero**: clickable DAG showcase screenshot above the fold; Mermaid Layer 1/2 architecture diagram (renders inline on GitHub); architecture atlas screenshot.

**Cleaned up:**
- **Deleted 19 redundant `_extended.md` companion files** plus their summary index (~11.7k lines) — LLM-generated boilerplate from January 2026 with no incoming links; canonicals (events.md, scheduler.md, observability.md, etc.) remain authoritative and are linked from `docs/index.md`.
- Fixed 3 stale facts: `docs/config.md` (`SettingsProvider` import path), `docs/env_configuration.md` (Claude 3 → Claude 4 model table), `docs/skills.md` (`Skill[InputT]` must be a `BaseModel`, not `str`).

**Fixed (showcase):**
- `rebuild()` resets transient run state (`endHoldUntil`, `previewT`, `lastTraceKey`, `lastT`) — toggling a counterfactual during the loop's end-hold no longer freezes the demo at t=0.
- `applyAll()` skipped when the DAG tab isn't active — saves CPU on the module-graph tab.
- Mobile (`@max-width:640px`): Python card `pre` wraps instead of horizontal-scrolling; trace correlation ID hidden.
- Accessibility (WCAG 2.4.11): focus rings on counterfactual labels + step ladder + cf-strip buttons; `aria-pressed` on step buttons; accordion `h3`s keyboard-reachable (`role=button`, `tabindex=0`, Space/Enter handler, `aria-expanded` synced with collapsed state).

## [2.0.0] - 2026-06-03

**Domain-agnostic core + persisted state machines + Hugging Face integration.**

First published release since 1.0.0 (the 1.1.0/1.1.1 tags were never published to PyPI; their content is rolled in here). Major bump for **breaking changes that make `cemaf.core` domain-neutral** — the framework no longer ships brand/marketing-specific vocabulary.

**BREAKING:**
- **Removed `ContextArtifactType` enum** (`cemaf.core.enums`). It hardcoded a brand/marketing taxonomy (`BRAND_CONSTITUTION`, `CAMPAIGN_BRIEF`, `SYMBOL_CANON`, `DO_NOT_SAY`...) into the framework core. `ContextArtifact.type` and the `ArtifactStore` protocol methods now take an **open `str`** — consumers define their own artifact taxonomy. Migration: replace `ContextArtifactType.BRAND_CONSTITUTION` with the string `"brand_constitution"` (or any consumer-defined value).
- **`MemoryScope` members renamed to domain-neutral terms.** `BRAND` → `TENANT` (the per-tenant isolation boundary; map to brand/org/workspace consumer-side); removed unused `AUDIENCE_SEGMENT`, `PLATFORM`, `PERSONAE`; added `GLOBAL` and `USER`. `PROJECT`/`SESSION`/`STRATEGY` unchanged. Migration: `MemoryScope.BRAND` → `MemoryScope.TENANT`.
- **`UISpec.brand_guidelines` renamed to `style_config`** (`cemaf.generation.protocols`).

**Added:**
- `cemaf.state` — typed, persisted, observable state-machine primitive (`StateMachine[StateT, EventT]`, `Transition`, `FsmState`, `FsmStore` Protocol, `InMemoryFsmStore`). Domain-neutral; composes with `DAGExecutor` (a transition handler can dispatch a DAG, inheriting `correlation_id`). Enforces typed states/events, explicit-transitions-only, optimistic locking, HITL non-bypass, append-only history, handler-failure rollback, terminal absorption. (#119, #121)
- Hugging Face integration (#120):
  - LLM provider (7th out of the box) via the OpenAI-compatible HF inference router — `create_llm_client("huggingface", ...)`
  - `HuggingFaceEmbeddingProvider` via feature-extraction inference
  - `HuggingFaceModelCatalog` (`cemaf.catalog`) over `huggingface_hub.HfApi` with typed `ModelCatalogQuery` / `CatalogModel` + `CatalogSettings` (#122)
- `SPEC-06` amendment — `MetaArchitectDecision` emission contract: `convergence_score ∈ [0.0, 1.0]`, `decision_kind` band-matching, replay determinism. (#117)
- Characterization tests pinning `DAGExecutor.run().success` semantics — a run can be COMPLETED while a `retry_on_failure=True` node failed; callers needing "all nodes succeeded" must inspect `node_results`. (#123)

**Fixed:**
- OBSERVE-mode evaluation now fires-and-forgets so judges do not serialize the hot path; production API + PULL cost-model docs. (#105)
- `[[tool.mypy.overrides]]` scoped to the four openai/redis adapter modules whose strict third-party stubs (`openai>=2.14`, `redis>=5`) rejected correct dynamic-kwargs / mapping call sites — restores green `Lint & Type Check`. (#127)

**Changed:**
- `core.types` restores `FinishReason` and `LLMProvider` StrEnums (with `HUGGINGFACE`).
- Scrubbed soft domain leaks: `from start.ini` doc references and `brand`-flavored scope examples across `core`, `memory`, `persistence`.

<details><summary>Superseded pre-release notes (1.1.0 / 1.1.1 — never published)</summary>

**Persisted state machines, Hugging Face integration, and a hardened eval loop.**

The 1.1.x line bundled the state primitive, HF integration, SPEC-06 amendment, OBSERVE fix, and CI mypy fix. It was tagged but never reached PyPI; 2.0.0 supersedes it and adds the domain-agnostic breaking changes.

**Added:**
- `cemaf.state` — typed, persisted, observable state-machine primitive (`StateMachine[StateT, EventT]`, `Transition`, `FsmState`, `FsmStore` Protocol, `InMemoryFsmStore`). Domain-neutral; composes with `DAGExecutor` (a transition handler can dispatch a DAG, inheriting `correlation_id` for telemetry joins). Enforces typed states/events, explicit-transitions-only, optimistic locking, HITL non-bypass, append-only history, handler-failure rollback, terminal absorption. (#119)
- Hugging Face integration across three layers (#120):
  - LLM provider (7th out of the box) via the OpenAI-compatible HF inference router — `create_llm_client("huggingface", ...)`
  - `HuggingFaceEmbeddingProvider` via feature-extraction inference
  - `HuggingFaceModelCatalog` (`cemaf.catalog`) over `huggingface_hub.HfApi` with typed `ModelCatalogQuery` / `CatalogModel` value objects and `CatalogSettings`
- `SPEC-06` amendment — `MetaArchitectDecision` emission contract: `convergence_score ∈ [0.0, 1.0]`, `decision_kind` band-matching (HALT/REVISE/CONVERGED), replay determinism. (#117)
- Integration tests pinning cross-module seams: `cemaf.state` → `DAGExecutor` (#121), `ModelCatalog` → `ModelRouter` (#122), and a characterization of `DAGExecutor.run().success` semantics — a run can be COMPLETED while a `retry_on_failure=True` node failed, so callers needing "all nodes succeeded" must inspect `node_results`. (#123)

**Fixed:**
- OBSERVE-mode evaluation now fires-and-forgets so judges do not serialize the hot path; added the production API that makes the fix testable; documented the PULL context + unit-of-work node cost model. (#105)

**Changed:**
- `core.types` restores `FinishReason` and `LLMProvider` StrEnums (with `HUGGINGFACE`) — fixes a broken-import state and adds the new provider member.

</details>

## [1.0.0] - 2026-05-27

**Enterprise Context Brain — spec-driven stability commitment.**

CEMAF crosses 1.0 on the back of seven converged specifications (SPEC-00..06) that define the Enterprise Context Brain target architecture: pull-not-push enterprise data, Blueprint-as-LLM-input, DAG-node task awareness, shared knowledge graph, internal guardian agents, low/zero-hallucination grounding. Specs landed after eight cross-agent review rounds (SA, senior-python, QA, junior-dev, AI/ML, LLM-systems, DevOps, context-engineering) covering ~3,600 lines of formal contracts.

**Added:**
- `SPEC-00` Enterprise Context Brain umbrella — common types, `RuntimeServices`, bootstrap, observability, GATE evaluator SLOs, citation membership predicate, `FinishReason` provider-mapping table, `EvalBudgetCounter`, `CassettePayload` schema with budget-accounting trio + truncation pair, `CassetteDivergenceError`
- `SPEC-01` Node Interceptor Pipeline — PRE/POST phases, `ChainProfile` (DEFAULT/RECOVERY), `ChainContractError`, deterministic chain semantics
- `SPEC-02` KG + DataSource services — `DataSource` Protocol, `PullInterceptor` (sole atomic writer of `ctx.surfaced_sources`), `EntityExtractor` Protocol, deterministic eviction order
- `SPEC-03` Blueprint as LLM Input — `BlueprintRequest[T]`, `StructuredGenerator` Protocol with `tool_registry` binding, tool-loop semantics with `tool_loop_budget`, structured-output validation, grounding annotation policy
- `SPEC-04` Task State Machine — `TaskRepository` Protocol, `AcquiredLease`, `TaskContext`, retry-ledger, decision windowing
- `SPEC-05` Guardian Mesh — six guardians (cite-or-fail, ungrounded-claim, schema, policy, hallucination, calibration), per-(node, attempt) `EvalBudgetCounter` clones with pre-flight reservation, judge–agent isolation
- `SPEC-06` Self-Resolving DAG — `MetaDispatcher`, `RecoveryRequest` projection, `pending_meta_patches` channel
- `docs/self-hosting.md` — meta-agent + meta-tool catalog, pre-built DAG walkthroughs (self_audit, feature_synthesis, knowledge_refresh)
- `docs/architecture/spec-module-map.md` — every SPEC concept → target module, Phase 2-9 implementation trajectory
- `README.md` "CEMAF runs on CEMAF" hero — surfaces self-hosting layer (meta/, audit/, knowledge/) above the fold
- Ollama tiered LLM router with Gemma 4b/12b local inference (`feat(llm)`)
- `structured_output` flag on executor; optional-node `None` resolution (`feat(executor)`)
- Generalized `$$key$$` placeholder resolution beyond `STEP_N_OUTPUT` (`feat(resolver)`)
- Blueprint triad: `BlueprintLibrary` curated entries, `WritableBlueprintSource` + `SqliteBlueprintSource`, `BlueprintSelectorHook` autonomous retrieval, `BlueprintHarvesterEngine` protocol-first harvest

**Changed:**
- Provider-native `finish_reason` strings normalized to `FinishReason` enum at adapter boundary; downstream specs reference enum members only
- `services.eval_budget` reclassified as TEMPLATE; live counters cloned per `(node_id, attempt_idx)` with `asyncio.Lock`-serialized reservation
- `gen_ai.usage.input_tokens` canonical source pinned to post-sanitization, post-truncation byte sequence; cassette/span divergence ≥1 token raises `CassetteDivergenceError`

**Stability:**
- Public `Agent`, `Tool`, `Skill`, `LLMClient`, `MemoryManager`, `ContextCompiler`, `EventBus`, `RuntimeServices`, `bootstrap.create_executor()` surfaces are now stable per semver. Breaking changes from this point require a major version bump.
- Phase 2-9 implementation against SPEC-00..06 is in flight; new optional protocols added under `RuntimeServices` ride the minor version.



### Added

**Evals System (PRs #61-65)**
- `OnlineEvalPipeline` subscribing to TASK_COMPLETED events with GATE/OBSERVE modes
- `HierarchicalJudge` with three-tier cascade: deterministic → semantic → LLM judge
- `QualityPolice` with rolling window, anomaly detection, and halt gate
- `RunEvalTool`, `CheckQualityTool`, `RecordScoreTool` as CEMAF tools
- `QualityGuardAgent` registered in AgentRegistry for self-evaluation
- Shared test fakes in `tests/unit/evals/conftest.py`

**OpenViking Enhancements (PRs #67-71)**
- `MemoryDeduplicator` protocol and `SemanticDeduplicator` (exact key + embedding similarity)
- `ContextType` enum (RESOURCE/MEMORY/SKILL) with `ContextTypeBehavior` rules
- `TieredMemoryStore` with L0/L1/L2 progressive retrieval
- `ScopePath` and `PropagatingScorer` for hierarchical scope propagation
- `ExtractionPipeline` and `RuleBasedExtractor` for post-session memory extraction

**Production Backends (PRs #74-76)**
- `StructuredLogger` with JSON-lines output
- `PrometheusMetrics` with lazy metric registration and `generate_metrics()`
- `SqliteMemoryStore` backed by aiosqlite
- `OpenAIEmbeddingProvider` using text-embedding-3-small
- `ResilientLLMClient` with retry, circuit breaker, and rate limiting
- VectorStore injectable in `create_memory_manager`

**Architecture (PRs #58-59)**
- `RuntimeServices` frozen dataclass bundling 16 optional runtime deps
- `bootstrap.create_executor()` composition root
- Node-type handlers extracted to `orchestration/node_handlers.py`

**Web (PR #77)**
- FastAPI architecture advisor using CEMAF's own agent stack

**Infrastructure (PRs #23-31)**
- `InstrumentedLLMClient` for transparent LLM call recording into RunLogger (PR #23)
- `ProviderRegistry[T]` generic extensible factory registry replacing if/elif chains (PR #24)
- `CancellationToken` support in `DAGExecutor.run()` for cooperative cancellation (PR #25)
- `NodeType.LOOP` and `Node.loop()` for iterative subgraph execution with exit conditions (PR #26)
- `create_token_estimator()` smart factory preferring tiktoken when available (PR #27)
- `compressible` flag in algorithm exclusion details for Greedy and Knapsack (PR #27)
- `context_compiler_registry`, `llm_registry`, `vector_store_registry` — extensible backend registries

### Fixed

**P0 Bugs**
- Session cascade bootstrap failure with proper recall query (PR #58)
- Loop `UnboundLocalError` in DAGExecutor (PR #60)
- `Context.set()` now uses `copy.deepcopy()` for nested dict immutability (PR #60)
- Dead online eval pipeline not receiving events (PR #63)
- Decorative thresholds in QualityPolice having no effect (PR #63)
- Swallowed errors hiding evaluation failures (PR #63)
- `scope_path` bug in `PropagatingScorer` causing incorrect ancestor queries (PR #73)

**P1 Bugs**
- Anthropic adapter: tool results, stream tool_use events, assistant tool_call blocks (PR #58)
- `datetime.now()` replaced with `utc_now()` everywhere (PR #60)
- Tiered store scope_path propagation (PR #73)
- MEMORY_EXTRACTED event missing output field (PR #73)
- P1/P2 type safety and dead code removal (PR #65)

**P2 Fixes**
- Session dispose scoped cleanup (PR #73)
- Zero-assertion tests replaced with proper checks (PR #60)
- Exception swallowing in EventBus handlers (PR #60)

**Integration & DI Gaps (PRs #72, #76)**
- `ContextTypeClassifier` protocol added
- `TieredMemoryStore` → `ContextProvider` wiring
- Factory gaps closed for extraction pipeline, scope scorer, session manager
- 30+ missing exports added to `__init__.py` across 7 packages: core, context, orchestration, llm, observability, agents, memory (PR #29)
- Redundant `_utc_now` in `result.py` replaced with `core.utils.utc_now` (PR #29)

### Changed
- MCP bridges consolidated to `mcp/bridges/` (PR #60)
- `ToolSchema.to_definition()` bridges tools → LLM protocols (PR #60)
- Singleton pattern removed from AgentRegistry (PR #60)
- Agentic DAG integration tests with real agents, eval pipeline, and quality police (PR #66)
- LLM, context compiler, and retrieval factories now use `ProviderRegistry` instead of if/elif chains
- `ContextNodeExecutor` auto-wraps agents' LLM clients with `InstrumentedLLMClient`
- Test suite expanded from 1464 → 1557 → 2118+ tests (PRs #29, #30, #57-76)
- CI pipeline added: lint, type-check, security scan, tests with coverage on every push/PR (PR #31)

## [0.2.0] - 2026-02-19

**Glass Box Architecture Enhancement**

Scientific-grade audit trail, provenance tracking, and full token accountability for production datalake-scale workloads.

**Added:**
- `ProvenanceChain` and `ProvenanceLink` for cross-referencing every artifact in a DAG run (LLM calls, context sources, citations, costs)
- `DomainContext` for domain-scoped business rules, vocabulary constraints, and citation style requirements
- `VerificationStatus` enum (UNVERIFIED, VERIFIED, DISPUTED, RETRACTED) for citation verification
- `ExclusionReason` enum (BUDGET_EXCEEDED, LOW_PRIORITY, STALE, DUPLICATE, FILTERED) for context source tracking
- `BudgetGuard` with configurable warning/critical/halt thresholds for cost and token enforcement across DAG runs
- `GlassBoxReporter` generating complete audit reports: decision traces, token audits, cost breakdowns, citation coverage verification
- `ContextNodeExecutor` bridging DAG nodes to agents via dynamic registry with provenance threading
- Dynamic `AgentRegistry` extending `BaseRegistry[Agent]` with domain-scoped lookups and auto-generated capabilities
- Autonomous `Planner` with LLM-based DAG generation and domain context injection
- Context engineering agents: Librarian, Researcher, Summarizer, Writer
- Parallel RLM chunk processing via `asyncio.gather` for divide-and-conquer branches
- Partial coverage fallback for RLM when max depth or single large chunk is reached
- Enhanced `LLMCall` and `ToolCall` with node_id, agent_id, context_sources_used, context_hash, budget_utilization, cost_usd, provenance_link_id
- Enhanced `RunRecord` with total_cost_usd, provenance_chain, selection_summaries
- Model pricing for claude-opus-4-6, claude-sonnet-4-6, gpt-4o, o1, o3 with cache pricing
- Token budget `utilization` and `headroom` properties
- Structured exclusion details in Greedy and Knapsack context selection algorithms
- `record_context_compilation()`, `record_budget_utilization()`, `record_citation_event()` metrics helpers
- `coverage_ratio` field on `RecursiveQueryResult`
- `DomainID`, `TenantID`, `ProvenanceID` NewType identifiers

**Changed:**
- `CitedFact.verification_status` uses `VerificationStatus` enum instead of raw string
- Citation protocol methods aligned to sync (matching tracker.py implementation)
- `Citation` model extended with `retrieved_at`, `agent_id`, `node_id`, `context_path`, `provenance_link_id`
- `DAGExecutor` accepts optional `budget_guard` parameter for cost enforcement
- RLM engine uses parallel processing instead of sequential left/right queries
- RLM fallback processes budget-sized batches instead of only the first chunk

**Stats:** 1464 tests | 100% passing | 47 files changed | +5,796 lines

## [0.1.0] - 2026-01-01

**Initial Alpha Release**

CEMAF provides infrastructure for building AI agent systems with context management, token budgeting, and deterministic replay.

**Core Features:**
- Context patches with provenance tracking
- Token budgeting and automatic compilation
- Deterministic run recording and replay
- DAG-based orchestration
- Memory management with scoping and TTL
- Framework-agnostic design (works with LangGraph, AutoGen, CrewAI)

For complete documentation, see [README.md](README.md) and [docs/](docs/).

**Note**: This is an Alpha release. APIs may change based on feedback.

---

[Unreleased]: https://github.com/drchinca/cemaf/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/drchinca/cemaf/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/drchinca/cemaf/releases/tag/v0.1.0

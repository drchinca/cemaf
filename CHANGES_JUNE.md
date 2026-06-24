# CEMAF Changes - June 2026

This file records the CEMAF framework work landed on top of
`origin/development` during the MeridianSight integration push. The goal across
these changes was consistent: move reusable wiring, runtime assembly, provider
selection, and backend composition into CEMAF so downstream apps stop
rebuilding framework seams locally.

## Branch Delta

Commits currently ahead of `origin/development` on this branch:

- `dd106a2` `feat(retrieval): add sqlite vector store and trace coverage`
- `2456303` `merge: integrate sqlite retrieval traceability`
- `5671264` `fix(sqlite): close test stores deterministically`
- `a37cf42` `merge: integrate sqlite lifecycle warning fix`
- `71d5a05` `feat(observability): add file run logger factory backend`
- `237da0e` `feat(factories): support CEMAF-native learning and moderation wiring`
- `3243389` `feat(evals): add CEMAF composition helpers for eval and recovery`
- `2331fd8` `feat(factories): add CEMAF runtime composition helpers`
- `6a2759f` `feat(factories): add logger and moderation composition helpers`
- `36e00f4` `feat(factories): add runtime services composition helper`
- `e6efff6` `feat(llm): add CEMAF Bedrock CLI provider`
- `3adcc3f` `feat(improvement): add runtime composition helpers`
- `f1fc0b5` `feat(state): add FSM store factory`
- `bf8eaa3` `feat(improvement): add self-improvement loop factory`
- `5c7214f` `feat(memory): add runtime composition factory`
- `ea694e2` `feat(llm): add resilient runtime factory`
- `16371e1` `feat(generation): add provider resolution helper`
- `99df8f1` `docs: add June framework changes summary`

The merge and fix commits above are included for completeness, but the
framework-facing additions are the feature commits listed below.

## Framework Additions

### Retrieval and learning backends

- Added SQLite vector-store support to the retrieval factory surface via
  `create_vector_store(..., backend="sqlite")` and the registered
  `SqliteVectorStore` backend.
- Extended retrieval composition so learning/runtime wiring can stay inside
  CEMAF rather than each app manually coordinating embedding providers,
  vector-store selection, and storage defaults.
- Added deep trace coverage around long-running context and retrieval flows so
  the new retrieval backend is exercised under realistic orchestration paths.

### Observability

- Added file-backed run logging to `create_run_logger(...)` and
  `create_run_logger_from_config(...)` through the `file` backend.
- This lets applications switch from in-memory run recording to persisted run
  bundles without owning the file logger wiring themselves.
- Added `export_standard_run_artifacts(...)` in the bundle surface to compose
  execution artifacts, asset evidence, optional run-record/replay artifacts,
  and model-usage export through one CEMAF helper.

### Moderation composition

- Added explicit moderation helper surfaces:
  - `create_keyword_rule(...)`
  - `create_keyword_moderation_pipeline(...)`
  - `create_post_flight_gate(...)`
  - `create_moderation_pipeline(...)`
- This moved common moderation assembly into CEMAF so downstream apps can
  compose blocked-word checks and post-flight gates through framework factories
  instead of directly instantiating moderation primitives.

### Evaluation and recovery composition

- Added evaluation composition helpers:
  - `create_node_eval_binding(...)`
  - `create_online_eval_pipeline(...)`
  - `create_quality_police(...)`
  - `create_single_node_eval_pipeline(...)`
- Added `create_auto_heal_manager()` to expose a clean factory seam for
  infrastructure recovery wiring.
- These additions make online evaluation, quality policing, and auto-heal
  setup CEMAF-native concerns instead of app-local bootstrap logic.

### Runtime composition helpers

- Added broader composition helpers across core factory modules so apps can ask
  CEMAF to build standard runtime components instead of reassembling them from
  concrete classes:
  - context compiler factories and config-oriented creation paths
  - LLM runtime helper surfaces
  - observability factory composition helpers
  - orchestration factory helpers such as `create_executor_config(...)` and
    `create_dag_executor(...)`

### Runtime services bundle

- Added `create_runtime_services(...)` so apps can assemble
  `RuntimeServices` through a CEMAF-owned helper instead of wiring the service
  bundle manually in application bootstrap code.

### LLM

- Added the Bedrock provider path in the LLM factory surface via
  `BedrockCliLLMClient` and `create_llm_client("bedrock", ...)`.
- Added `create_resilient_llm_client(...)` so provider auto-selection,
  credential lookup, model defaults, and resilient wrapping live in CEMAF
  instead of being duplicated in downstream apps.

### Improvement runtime

- Added `create_self_improvement_loop(...)` so apps do not directly construct
  the default `SelfImprovementLoop`.
- Added `ImprovementRuntime` and `create_improvement_runtime(...)` to bundle:
  - strategy memory
  - trust ledger
  - self-improvement loop
  - optional persisted runtime paths

### State

- Added `create_fsm_store(...)` so apps can request the default FSM storage
  backend through a stable factory instead of instantiating concrete state
  stores directly.

### Memory runtime

- Added `MemoryRuntime` and `create_memory_runtime(...)` to compose:
  - embedding provider
  - memory store
  - vector store
  - memory manager
  - extraction pipeline
  - session manager
  - optional session-recording subscription

This moved durable learning-memory assembly behind a CEMAF surface rather than
leaving each app to wire the graph itself.

### Generation/provider resolution

- Added `ProviderResolution` and `resolve_available_provider(...)` in the
  generation surface.
- This gives downstream apps a reusable helper for:
  - explicit-vs-auto provider selection
  - fallback through candidate order
  - warning accumulation from failed candidates
  - optional preflight checks such as local binary availability

## Why These Were Added

The downstream objective was to make MeridianSight consume framework surfaces
instead of concrete CEMAF internals or app-local composition logic. Each
addition above was introduced when MeridianSight still had to do at least one
of the following:

- manually assemble a CEMAF runtime bundle
- directly instantiate a default framework primitive
- own generic provider-selection or backend-selection logic
- wire moderation, evaluation, recovery, or observability concerns outside the
  framework

## Result

After these additions, MeridianSight now delegates substantially more of its
bootstrap/runtime wiring to CEMAF, including:

- runtime services composition
- file-backed and in-memory run logging selection
- Bedrock LLM construction
- resilient LLM runtime construction
- improvement runtime construction
- default self-improvement loop construction
- FSM store construction
- memory/learning runtime construction
- moderation and evaluation composition seams
- provider fallback resolution for image/video runtime selection

## Notes

- `99df8f1` is the documentation commit for this file.
- The merge/fix commits in the branch delta are integration support work, not
  new public framework surfaces.
- The intent across all of these changes is the same: leverage CEMAF first and
  stop re-implementing reusable framework logic in downstream projects.

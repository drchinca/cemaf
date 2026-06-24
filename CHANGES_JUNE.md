# CEMAF Changes - June 2026

This file records the CEMAF framework additions landed during the MeridianSight
integration work. The focus was to move reusable runtime/composition logic into
CEMAF so downstream apps stop rebuilding the same seams locally.

## Scope

These are the framework-facing changes added on top of `origin/development`
during this run:

- `36e00f4` `feat(factories): add runtime services composition helper`
- `e6efff6` `feat(llm): add CEMAF Bedrock CLI provider`
- `3adcc3f` `feat(improvement): add runtime composition helpers`
- `f1fc0b5` `feat(state): add FSM store factory`
- `bf8eaa3` `feat(improvement): add self-improvement loop factory`
- `5c7214f` `feat(memory): add runtime composition factory`
- `ea694e2` `feat(llm): add resilient runtime factory`
- `16371e1` `feat(generation): add provider resolution helper`

## Added Surfaces

### Runtime composition

- Added `create_runtime_services(...)` so apps can assemble
  `RuntimeServices` through a CEMAF-owned helper instead of wiring the bundle
  manually in their own bootstrap code.

### LLM

- Added the Bedrock provider path in the LLM factory surface via
  `BedrockCliLLMClient` and `create_llm_client("bedrock", ...)`.
- Added `create_resilient_llm_client(...)` so provider auto-selection,
  credential lookup, provider defaults, and resilient wrapping live in CEMAF
  instead of app bootstrap code.

### Improvement runtime

- Added `ImprovementRuntime` and `create_improvement_runtime(...)` to bundle
  strategy memory, trust ledger, and loop construction behind one framework
  seam.
- Added `create_self_improvement_loop(...)` so apps do not directly construct
  the default `SelfImprovementLoop`.

### State

- Added `create_fsm_store(...)` so apps can request the default FSM storage
  backend through a stable factory instead of instantiating concrete store
  classes directly.

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

The downstream goal was to make MeridianSight consume framework surfaces rather
than concrete CEMAF internals or app-local composition logic. Each addition
above was introduced only when MeridianSight still had to:

- manually assemble a CEMAF runtime bundle
- directly instantiate a default framework primitive
- own provider fallback logic that is generic enough to belong in CEMAF

## Result

After these additions, MeridianSight now delegates the following framework seams
to CEMAF:

- runtime services composition
- Bedrock LLM construction
- resilient LLM runtime construction
- improvement runtime construction
- default self-improvement loop construction
- FSM store construction
- memory/learning runtime construction
- provider fallback resolution for image/video runtime selection

Each of the commits above was landed with focused tests and a green full CEMAF
test run at the time of integration.

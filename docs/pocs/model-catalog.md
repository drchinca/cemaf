---
title: Provider/Model Catalog as Data
date: 2026-05-16
status: Complete
methodologies_compared:
  - M1 — Status quo (hand-coded provider factories + complexity-threshold router)
  - M2 — Pure cost-minimizer over catalog (capability + window gate, then cheapest)
  - M3 — Catalog + complexity-tiered quality floor (cheapest above tier)
decision: "Go — M3 (catalog with capability/window gates and complexity-tiered quality floor). M1 factories preserved as the construction layer; M3 selection replaces ModelRouter."
related:
  inspiration: https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/provider/provider.ts
  pocs: []
  specs: []
---

# POC: Provider/Model Catalog

## Question

Should CEMAF replace its hand-coded model defaults and threshold-only router with a **JSON model catalog** (à la opencode's `models.dev`) — so adding a model is config, not code; cost-aware routing comes for free; and context-window enforcement is a single lookup?

Inspiration: opencode `provider/provider.ts:1097-1180` pulls a JSON catalog with `{provider, model_id, context_window, max_output, input_cost_per_mtok, output_cost_per_mtok, supports_tools, supports_vision, supports_caching}` per model. User overrides merge in. New model release = config bump.

## Current State — Baseline Numbers

`src/cemaf/llm/factories.py` and `src/cemaf/llm/model_router.py`:

| Signal | Value | Source |
|---|---|---|
| Hardcoded model defaults | 7 across 7 factories | `factories.py:34-114` (e.g., `"claude-sonnet-4-20250514"`, `"gpt-4o"`, `"gemini-2.5-flash"`) |
| Cost data per model | none | grep no match |
| Context-window data per model | none | grep no match |
| Capability flags (tools/vision/caching) | none | grep no match |
| Router selection inputs | complexity score (0-1), hand-set thresholds | `model_router.py:101-106` |
| New model = code change | yes | requires factory edit, threshold add |
| Model deprecation handling | none — unchanged in code until edited | n/a |
| Cost-aware routing | no | router ignores price |

**Implications:**
- Routing by complexity-only ignores cost. A high-complexity request gets the "biggest" model regardless of whether a cheaper one would fit (small context-window check).
- Adding a new model (e.g., a Claude 4.8 release) requires editing `factories.py` and adding a threshold to the router config — every consumer.
- Self-hosting agents (`MetaAuditor`) have no per-model cost telemetry.
- A 200k-token request can be routed to a 32k-window model and silently truncated by the provider.

## Methodologies

### M1 — Status quo (hand-coded factories + threshold router)

`create_llm_client(provider="anthropic", model="claude-...")` with hardcoded defaults. `ModelRouter` selects by complexity threshold. No cost data.

- **Pros:** simple, works today, no new concepts
- **Cons:** model proliferation forces edits everywhere, no cost-aware routing, no context-window enforcement, no capability gating (e.g., "this request needs vision")

### M2 — JSON catalog (data-driven)

`ModelSpec` Pydantic model:
```python
class ModelSpec(BaseModel):
    provider: str
    model_id: str
    context_window: int
    max_output_tokens: int
    input_cost_per_mtok: float | None  # None = pricing unknown / local
    output_cost_per_mtok: float | None
    supports_tools: bool = True
    supports_vision: bool = False
    supports_caching: bool = False
    deprecated: bool = False
    aliases: tuple[str, ...] = ()
```

Catalog file `data/models.json` (or `cemaf/data/models.json`). Loaded once at startup via `ModelCatalog.load(path)`. User overrides merged on top. `create_llm_client` looks up model_id in catalog for spec; factory uses the spec to wire the client.

- **Pros:** new model = JSON edit; cost / window / capabilities queryable; downstream tools (router, budget guard, MetaAuditor) consume one source of truth
- **Cons:** new file format; need versioning + validation; out-of-catalog models become an explicit error case

### M3 — Hybrid (factories preserved; catalog drives routing/cost/window)

Existing `_create_anthropic`, `_create_openai`, etc. factories stay. Catalog adds *metadata* — cost, window, capabilities — keyed by `provider:model_id`. Router upgrades from threshold-only to a multi-factor selector: complexity + capability requirements + cost + window-fit. Lookup misses fall back to a `default_spec` (1k context, no caching, no vision) so old code still works.

- **Pros:** zero breaking changes; gradual migration; per-provider client code unchanged; catalog is additive
- **Cons:** two sources of truth (factory dict and catalog) — must stay aligned via test, with deprecation path to fold factories into catalog

## Success Criteria

| Metric | Target | Reason |
|---|---|---|
| Add a new model without code change | yes | The whole point |
| Cost-aware routing decision agrees with hand-picked optimal in ≥80% of test scenarios | yes | Cost wins when capability ties |
| Context-window enforcement: route only to models that fit the request | 100% | No silent truncation |
| Capability gating: vision-required request rejects vision-incapable models | 100% | Correctness |
| Backward compat: existing `create_llm_client(provider="anthropic")` keeps working | yes | Don't break callers |
| Catalog load latency | <50 ms | Startup tax |
| Per-route selection latency | <1 ms | Hot path |
| Lookup-miss handling | explicit (raise or fallback-with-warning) | No silent errors |

## Comparison Table

Bench: `docs/pocs/_experiments/model_catalog_bench.py`. 7-model catalog (Anthropic Haiku/Sonnet/Opus, OpenAI 4o-mini/4o, Ollama gemma3:4b/12b). 6 hand-picked-optimal scenarios. Run on 2026-05-16.

| Scenario | Profile | Optimal | M1 (status quo) | M2 (pure cost) | M3 (cost + quality floor) |
|---|---|---|---|---|---|
| tiny no-tools | 500 in / 200 out, no tools | gemma3:4b | ✓ | ✓ | ✓ |
| medium tool use | 8k in / 2k out, tools | gpt-4o-mini | ✓ | ✓ | ✓ |
| 200k window | 180k in / 4k out | claude-haiku-4-5 | ✗ (sonnet) | ✓ | ✓ |
| vision required | 4k in, vision flag | gpt-4o-mini | ✓ | ✓ | ✓ |
| complex coding | 40k in / 6k out, complexity 0.95 | claude-opus-4-7 | ✓ | ✗ (4o-mini) | ✓ |
| cheap bias | 2k in / 800 out, complexity 0.2 | gpt-4o-mini | ✓ | ✓ | ✓ |
| **Match rate** | | | **5/6 (83%)** | **5/6 (83%)** | **6/6 (100%)** |
| Capability violations | | | 0 | 0 | 0 |
| Window violations | | | 0 | 0 | 0 |

Latency:

| Metric | M1 | M2 | M3 |
|---|---|---|---|
| Catalog load (validate 7 specs) | n/a | 0.05 ms | 0.05 ms |
| Selection p50 | 0.0001 ms | 0.0022 ms | 0.0022 ms |

## Detailed Results

**M1 (status quo) — fails the 200k window scenario.** Routes by complexity threshold alone. A 180k-token request lands on `claude-sonnet-4-6` (matches the 0.7 complexity threshold). Sonnet *does* fit (200k window) but costs 3.75× more than `claude-haiku-4-5` which also has the 200k window. M1 has no concept of "cheapest model that fits" — it picks by tier alone. In a real deployment with mixed Anthropic / OpenAI / Ollama, M1 also can't gate on `supports_tools` or `supports_vision` — those checks live in caller code today, not the router.

**M2 (pure cost minimizer) — fails the high-complexity scenario.** Filters by capability + window then picks cheapest. For "complex coding" (40k in / 6k out, complexity 0.95), the cheapest model that meets hard requirements is `gpt-4o-mini` ($0.15/$0.60 per Mtok). It fits the window, supports tools — but the agent needs reasoning headroom Opus provides. Pure cost ignores quality demand.

**M3 (cost + complexity-tiered quality floor) — 100% match.** Adds a quality floor curve: complexity tiers map to a minimum input price (proxy for capability tier).
- `complexity < 0.5` → floor $0/Mtok (any model OK, including free local)
- `complexity < 0.85` → floor $0.5/Mtok (rules out tiny local Ollama for non-trivial tasks)
- `complexity ≥ 0.85` → floor $12/Mtok (forces a top-tier reasoning model)

Within the qualified set, cheapest wins. `claude-opus-4-7` is the cheapest model meeting the $12/Mtok floor for the complex-coding scenario. `claude-haiku-4-5` ($0.80) qualifies above the $0.5 floor at complexity 0.7 and beats Sonnet on cost while fitting 200k window. Behavior is principled, traceable, and tunable per deployment.

## Success Criteria — Actuals

| Metric | Target | Actual (M3) |
|---|---|---|
| Add a new model without code change | yes | yes — append a `ModelSpec` to the catalog list / JSON file |
| Cost-aware decision in ≥80% of scenarios | yes | 100% (6/6) on the bench |
| Window enforcement | 100% | 0 violations across all scenarios |
| Capability gating (vision/tools) | 100% | 0 violations |
| Backward compat — `create_llm_client(provider=)` keeps working | yes | M1 factories preserved as construction layer; catalog adds metadata only |
| Catalog load latency | <50 ms | 0.05 ms for 7 specs (extrapolates to ~5 ms for 700) |
| Selection latency | <1 ms | 0.0022 ms |
| Lookup-miss handling | explicit | spec must define: raise `UnknownModelError` OR fallback with warning |

## Decision

**Go — M3 (catalog + complexity-tiered quality floor).** Existing `factories.py` provider factories are preserved as the *construction* layer; the new `ModelCatalog` is the *selection* layer.

Rationale:
- M3 is the only method scoring 100% on the scenario suite. M1 misses the 200k-window cost optimization. M2 misses the high-complexity tier requirement.
- Latency is sub-millisecond; catalog load is sub-millisecond. No operational concerns.
- The complexity-tiered quality floor curve is **the** policy knob. Defaults ship as data; deployments override per-tenant. Replaces `ModelRouter`'s ad-hoc threshold list with a principled, capability-aware selector.
- Backward compat is preserved by keeping `_create_anthropic` etc. as the wiring path. Catalog only adds `ModelSpec` metadata; `create_llm_client(provider="anthropic", model="claude-haiku-4-5")` still resolves the same factory.

**Reject M1.** Hardcoded thresholds aren't capability-aware (tools/vision/window) and can't deduplicate across providers. Adding a new model requires touching `factories.py`, the router config, and probably tests — too much for what should be a config change.

**Reject M2 (as the only selector).** Pure cost minimization is correct for capability-bounded requests but cannot encode "needs reasoning headroom." It's the right *baseline* — M3 is M2 plus a quality floor — but M2 alone misroutes complex tasks.

## Learnings

- **The catalog is two artifacts: a schema and a data file.** `ModelSpec` Pydantic schema is code (versioned, tested). The catalog data lives in `cemaf/data/models.json` and can be overridden per-deployment via env (`CEMAF_MODEL_CATALOG_PATH`) or merged dict. Spec must define both: schema in §2 Interface Contract, data file location/format in §6 Dependencies.
- **Quality floor is a policy curve, not a single number.** `((complexity_threshold, min_input_price), ...)` ordered tuples encode tiering. Default curve ships with the framework; tenants override. Spec §2 Interface Contract: `QualityFloorCurve` type alias + `ModelSelector(catalog, quality_floor_curve)`.
- **Hard requirements before optimization.** Capability + window gates run *first* and reject; cost + quality floor optimize *within* the qualified set. The bench shows 0 violations across all methods that filter — but M1 is missing those filters today.
- **Model deprecation is free with a catalog.** `deprecated: bool` flag in `ModelSpec`. Selector skips deprecated entries. Spec §3 EARS invariant: `WHEN spec.deprecated, THE Selector SHALL NOT return that model unless explicitly requested by alias`.
- **Aliases bridge user-friendly names to model_ids.** `"haiku"` → `"anthropic:claude-haiku-4-5"`. Survives model version bumps without breaking caller code.
- **The router method has the wrong abstraction today.** `ModelRouter` thinks in *complexity tiers*; the right abstraction is *capability + cost optimization*. Replacing `ModelRouter` with `ModelSelector` (catalog-driven) is a clean migration: callers swap `router.complete()` for `client = catalog.select(req); client.complete()`.
- **Ollama tiered router (`ollama-tiered`) is a special-case of M3.** Once the catalog exists, the tiered Ollama router becomes a one-line config (two `ModelSpec` entries with quality-floor-driven escalation).
- **Cost telemetry comes for free.** Once the catalog has costs, every LLM call can emit `gen_ai.usage.cost_usd` from `(input_tokens × spec.input_cost) + (output_tokens × spec.output_cost)`. Closes the gap with `MetaAuditor` cost analysis.

## Next Steps

1. **Spec it** via `/write-spec` — `docs/specs/SPEC-model-catalog.md`. Required sections:
   - §2 Interface Contract: `ModelSpec` Pydantic schema, `ModelCatalog.load(path) / .add(spec) / .lookup(key|alias)`, `ModelSelector(catalog, quality_floor_curve, fallback_strategy)`, `Request` shape (input/output token estimates, capability flags, complexity).
   - §3 Invariants (EARS): `WHEN req.needs_vision, THE Selector SHALL only return supports_vision=True specs`. `WHEN spec.deprecated, THE Selector SHALL NOT return it unless requested by alias`. `IF no candidate fits, THEN THE Selector SHALL raise NoFittingModelError (no silent fallback)`. `WHILE catalog has specs with overlapping providers, THE Selector SHALL prefer cheapest within the complexity tier`.
   - §4 Gherkin scenarios: 8+ — capability filter / window filter / quality floor / cheap bias / explicit alias request / deprecated model rejection / catalog-miss fallback / per-tenant override merge.
   - §6 Dependencies: data file `cemaf/data/models.json`, env `CEMAF_MODEL_CATALOG_PATH` for overrides.
   - §7 Correctness Properties: window-fit guarantee, capability-gate guarantee, quality-floor monotonicity (higher complexity → equal or higher floor).
   - §9 Observability Contract: `gen_ai.model.select` span with `request.complexity`, `selected.model`, `qualified_count`, `selection_reason`. `gen_ai.usage.cost_usd` derived from spec costs.
2. **Migrate `ModelRouter` to `ModelSelector` in a follow-on PR.** Existing callers wrap `router` in a thin shim that delegates to `selector` — no API break.
3. **Out of scope:**
   - Live catalog refresh from a remote source (opencode pulls from models.dev) — defer to v2.
   - Per-org pricing overrides (some customers have negotiated rates) — `input_cost_per_mtok` is already overridable via catalog merge; UX/spec for it is a follow-on.
   - Cost budgets per agent / per session — that's `BudgetGuard` territory; this POC enables it but doesn't scope it.

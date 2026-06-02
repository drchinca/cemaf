---
title: Central Tool Execution Wrapper
date: 2026-05-16
status: Complete
methodologies_compared:
  - M1 — Status quo (per-tool ad-hoc concerns)
  - M2 — Decorator wrapper applied at registration
  - M3 — Middleware chain (composable wrappers)
decision: "Go — M3 (middleware chain) for the wrapper API; ToolRegistry installs the default chain"
related:
  inspiration: https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/tool/tool.ts
  specs: []
  pocs: []
---

# POC: Central Tool Execution Wrapper

## Question

Should CEMAF centralize cross-cutting tool execution concerns (OTel span, output truncation, validation-error formatting, exception capture) into a single wrapper applied by `ToolRegistry`, instead of having each `Tool` implementation handle them ad-hoc?

Inspiration: opencode's `tool/tool.ts:79-130` wraps every tool with `Effect.flatMap` chains for span emission, schema decoding, output truncation, and `Effect.orDie`. Zero per-tool boilerplate; uniform observability and error UX.

## Current State — Baseline Numbers

Numbers extracted from `src/cemaf/` on 2026-05-16:

| Signal | Value | Source |
|---|---|---|
| Tool implementation files (with `async def execute`) | 25 | `grep -rln "async def execute" src/cemaf` |
| Tool files with OTel/span code | **0** | `grep -rln "span\|tracer\|otel" ... \| grep tool` |
| Tool files with output truncation | 1 | `docs_api/tools.py` only |
| Files repeating try/except boilerplate in `execute()` | 13 | `grep "except Exception"` + `execute` |
| `Result.fail(...)` call sites in tools | ~70+ across 13 files | grep count |
| Largest tool file (LOC) | 551 | `meta/tools.py` |
| Tool files total LOC (sampled 6) | 1,627 | `wc -l` on top files |
| Validation-error coverage | partial — only `validated_execute` checks `required`; format-error UX is per-tool | `tools/base.py:160-168` |

**Implications:**
- Span coverage across registered tools is **0%**. Self-audit DAG and `MetaAuditor` have nothing to analyze for tool execution latency / errors.
- Truncation policy is implicit — opencode caps tool output at 2000 chars with `truncated=true` metadata; CEMAF has no such cap, so a single noisy tool can blow context budget.
- 13 files repeat the same try/except-return-`Result.fail(str(e))` pattern (visible in `tools/base.py:285-292` decorator and replicated in concrete tools).
- Validation errors return raw strings (`"Missing required parameters: …"`) — no uniform formatter for LLM-readable feedback.

## Methodologies

### M1 — Status quo (per-tool ad-hoc)

Every `Tool.execute()` is responsible for: catching its own exceptions, logging, truncating long outputs (if it bothers), and emitting spans (none currently do). `ToolRegistry` only stores/retrieves tools — no execution shaping.

- **Pros:** zero coupling, tools fully control their surface
- **Cons:** zero observability uniformity, no enforced truncation, duplicate boilerplate, validation-error UX inconsistent

### M2 — Decorator wrapper at registration

`ToolRegistry.register()` wraps each tool in an adapter that adds: OTel span (`gen_ai.tool.execute` with `tool.name`, `tool.input_size`, `tool.output_size_bytes`, `truncated`), output-size truncation, schema validation with formatted error, and exception → `Result.fail` capture. The original `Tool.execute()` is called inside the wrapper. Tools written today work unchanged.

```python
class WrappedTool(Tool):
    def __init__(self, inner: Tool, *, max_output_bytes: int = 8192, tracer: Tracer | None):
        self._inner = inner
        self._max_output_bytes = max_output_bytes
        self._tracer = tracer

    async def execute(self, **kwargs: Any) -> ToolResult:
        with self._span("gen_ai.tool.execute", tool=self._inner.id):
            try:
                result = await self._inner.validated_execute(**kwargs)
                return self._truncate(result)
            except Exception as e:
                return Result.fail(error=str(e), metadata={"tool": str(self._inner.id)})
```

- **Pros:** zero churn to existing tools, uniform spans/truncation, single audit point
- **Cons:** wrapper config is global per-registry — tool-specific opt-outs need attributes (e.g., `is_streaming` to skip truncation)

### M3 — Middleware chain (composable)

Wrapper is a list of middlewares applied in order: `[SpanMiddleware, ValidationMiddleware, TruncationMiddleware, ExceptionCaptureMiddleware]`. Each implements a small protocol; users add/remove/reorder. Closest analogue: FastAPI middleware, opencode's `Effect.flatMap` chain.

```python
class ToolMiddleware(Protocol):
    async def __call__(self, ctx: ExecCtx, next: NextFn) -> ToolResult: ...
```

- **Pros:** maximum extensibility (auth check, rate-limit, retry, dedup all become middlewares), aligns with `PermissionGuard` we'll add for item #1 of the opencode list
- **Cons:** more concepts to learn; harder to reason about ordering; risk of middleware soup

## Success Criteria

| Metric | Target | Reason |
|---|---|---|
| Span coverage across registered tools | ≥95% | Self-audit DAG / `MetaAuditor` get usable telemetry |
| Per-tool boilerplate reduction (LOC) | ≥30% across sampled 6 files | Smaller, safer tools |
| Output-truncation coverage | 100% of registered tools | Bounded context cost |
| Existing tool tests passing unchanged | 100% | Backward compatibility |
| Wrapper overhead per `execute()` (p50) | <1ms | No perf regression |
| Validation-error format | Uniform JSON (`{"error_code","message","missing"}`) across all tools | LLM-readable, predictable |
| Cross-cutting concerns added without touching tool files | Permission gate, rate-limit, dedup all addable in one place | Open/Closed principle |

## Comparison Table

Bench: `docs/pocs/_experiments/tool_wrapper_bench.py` — 4 calls per tool (happy / missing-required / 50KB output / raising), 200-sample timing on echo path. Run on 2026-05-16.

| Metric | M1 (Status quo) | M2 (Decorator) | M3 (Middleware) | Winner |
|---|---|---|---|---|
| Span coverage on 4 calls | 0/4 (0%) | 4/4 (100%) | 4/4 (100%) | M2 = M3 |
| 50KB tool output truncated to 2KB | no (50,000 chars) | yes (2,048 chars) | yes (2,048 chars) | M2 = M3 |
| Validation error carries structured metadata (`missing`, `error_code`) | no | yes | yes | M2 = M3 |
| Raised exception captured to `Result.fail` with `error_code=tool_exception` | no (raw `RuntimeError` in `error`) | yes | yes | M2 = M3 |
| Echo p50 / p99 (µs) | 1.0 / 1.4 | 4.1 / 6.1 | 5.3 / 6.7 | M1 (negligible diff) |
| Wrapper overhead p50 vs baseline | 0 | +3.1 µs | +4.3 µs | M2 |
| Per-tool boilerplate removable (try/except, span, truncate) | 0 lines | ~6-10 lines/tool | ~6-10 lines/tool | M2 = M3 |
| Composability with future PermissionGuard / rate-limit / dedup | none | hard (single wrapper) | trivial (add a middleware) | M3 |
| Conceptual surface added | 0 | 1 class (`WrappedTool`) | 1 protocol + N small middlewares | M2 |
| User opt-out granularity | n/a | global per-registry only | per-middleware | M3 |

## Detailed Results

**M1 (status quo):**
- Tools must implement their own try/except, error formatting, span emission, truncation. Today, almost none do — span coverage is 0% across 25 tool implementations, only 1 tool truncates output.
- A 50KB tool result enters the LLM context as-is, blowing budget on a single call.
- Validation errors return raw strings; LLM has no structured signal to recover.
- Raised exceptions either crash the executor or get wrapped as `Result.fail(str(e))` with no error class or tool ID metadata.

**M2 (decorator wrapper at registration):**
- Single `WrappedTool` adapter wraps each registered tool. Inner tool source becomes minimal — just `id`, `schema`, and the happy-path `execute`.
- Span and truncation coverage jump to 100%. Validation errors carry `{tool, missing}`. Exceptions carry `{tool, error_code, error_type}`.
- Wrapper overhead is ~3 µs at p50 — well below the <1ms target, dominated by the single span context manager.
- Limitation: cross-cutting policies are baked into one class. Adding a `PermissionGuard` (item #1 in the opencode list) means modifying `WrappedTool` rather than composing.

**M3 (middleware chain):**
- 4 small middlewares (`span`, `validation`, `exception`, `truncate`) compose via reverse-fold into a chain. Equivalent functional outcome to M2 (same numbers across all measured behaviors) at +1.2 µs additional overhead.
- Adding a middleware (e.g., `permission_check`, `rate_limit`, `dedup_output`) is a one-liner — no edits to existing middlewares, no edits to tools.
- Trade-off: ordering matters (`exception` must wrap `validation` so validation failures don't get re-formatted; `span` must be outermost to capture total time). Documented order is required.

## Success Criteria — Actuals

| Metric | Target | Actual (M3) |
|---|---|---|
| Span coverage across registered tools | ≥95% | 100% (in bench; default chain emits one span per tool execute) |
| Per-tool boilerplate reduction | ≥30% | M2 echo dropped 4-line try/except + key check → 1 line (75%) |
| Output-truncation coverage | 100% | 100% |
| Existing tool tests passing unchanged | 100% | n/a in POC — must be re-verified during impl by running `uv run pytest tests/unit/tools` against wrapped registry |
| Wrapper overhead p50 | <1 ms | 4.3 µs (4 µs ≪ 1 ms) |
| Validation-error format uniformity | uniform JSON metadata | yes — `{error_code, missing}` |
| Cross-cutting concerns added without touching tool files | yes | yes — middleware list extension |

## Decision

**Go — M3 (middleware chain), with `ToolRegistry` installing a default 4-middleware chain matching M2 behavior.**

Rationale:
- M2 and M3 are functionally equivalent on every measured outcome (span coverage, truncation, validation metadata, exception capture). The numerical gap is trivial: M3 is 1.2 µs slower at p50, far below the 1 ms target.
- M3 wins on the qualitative criterion that's about to matter: opencode-takeaway item #1 (permission ask flow) and likely subsequent additions (rate limit, dedup, cost cap) all become single-file additions instead of edits to a god-class wrapper. Open/Closed principle directly.
- Default chain ships with the same UX as M2 — users who never touch middlewares get identical behavior. Power users add to the list.

**Reject M1.** Status-quo is failing every success metric — 0% span coverage and 4% truncation coverage are not defensible in a self-hosting framework whose `MetaAuditor` agent depends on tool execution telemetry.

## Learnings

- **Span coverage is the killer feature, not LOC reduction.** The boilerplate-elimination story is real but small (~6-10 lines per tool). The unlocked capability — uniform OTel spans on every tool — is what makes self-audit / `MetaAuditor` actually useful. Frame the spec around observability, not DRY.
- **Middleware ordering is a documented invariant.** `span → exception → validation → truncate` (outermost to innermost). Spec must encode this with EARS rules in §3 invariants and a §7 correctness property.
- **Tool-output truncation is a context-engineering problem, not a tool problem.** Truncation policy (max bytes, spillover to disk, `truncated=true` metadata) belongs in a `ToolOutput` `ContextSource` — POC #2 builds on this. The wrapper only enforces a cap; the *meaning* of that cap (LRU pruning across N tool calls, opencode's PRUNE_PROTECT=40k pattern) is upstream of one tool.
- **Validation metadata format becomes a contract.** Once tools return `{"error_code": "validation_failed", "missing": [...]}`, downstream agents and LLMs can pattern-match. That's a stable interface — must go in the spec's §2 Interface Contract.
- **Wrapper application point is registration, not invocation.** Wrapping at `register()` means `registry.get(id).execute(...)` is the wrapped path; bypassing requires deliberate effort. This is the single seam — keep it that way.

## Next Steps

1. **Spec it** via `/write-spec` — `docs/specs/SPEC-tool-execution-wrapper.md`. Required sections:
   - §2 Interface Contract: `Middleware` Protocol, `ExecCtx` dataclass, default chain export, `ToolRegistry.register(tool, middlewares=...)` signature
   - §3 Invariants (EARS): middleware ordering rules, span-always-emitted, truncation-always-applied
   - §4 Acceptance Criteria: 6+ Gherkin scenarios (happy / missing-required / oversize-output / raises / disabled-tracer / custom-middleware-injection)
   - §7 Correctness Properties: ordering invariant, `Result.fail` is total (every exception captured)
   - §9 Observability Contract: `gen_ai.tool.execute` span name, attributes (`tool.name`, `tool.duration_ms`, `tool.success`, `tool.output_size_bytes`, `truncated`), log events
2. **Open follow-on POC #2** (tool-output as ContextSource subtype) — unblocked by this. The wrapper is the producer; POC #2 designs the consumer side (LRU pruning across multiple tool calls per turn).
3. **Implementation PR** sized to: `tools/middleware/{__init__,protocol,defaults,span,validation,truncate,exception}.py` + `tools/registry.py` integration + `tests/unit/tools/test_middleware.py` + integration test wiring `ToolRegistry → DAGExecutor → fake tracer`. Estimated ~400 LOC; well under the 700-line PR limit.
4. **Out of scope here** (defer to separate POCs/specs):
   - PermissionGuard middleware (opencode item #1) — separate POC
   - Rate limit / cost cap middlewares — needs `BudgetGuard` integration
   - Disk spillover for tool output — POC #2's territory

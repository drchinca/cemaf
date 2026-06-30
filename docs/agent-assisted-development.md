# Agent-Assisted Development With CEMAF

This guide is written for LLMs, coding agents, and humans supervising them. Its
job is to keep generated CEMAF apps from using three or four modules and then
rebuilding the rest of the framework in application code.

> 💡 **For AI coding systems (Cursor, Gemini, Claude):** Refer directly to the [AI Integration & Development Guide](AI_DEVELOPMENT_GUIDE.md) for dense, production-ready code recipes, Python 3.12+ standards, and direct Do/Violation matrices.

CEMAF is the substrate. Application repos should bring domain agents, tools,
policies, stores, and product workflows; CEMAF should own the generic execution,
context, provenance, quality, safety, and operator machinery.

## The CEMAF-First Contract

When building on CEMAF, do this in order:

1. Search CEMAF's docs/API for the concern.
2. Compose the existing module through `RuntimeServices`, a registry, an
   interceptor, an event subscriber, or a factory.
3. Implement the smallest app-specific adapter that satisfies a CEMAF protocol.
4. Add an integration test that proves the adapter is wired through CEMAF.
5. Only create new infrastructure when the missing behavior cannot be expressed
   through an existing protocol.

If generated code contains a custom orchestrator, prompt compiler, memory
manager, budget tracker, eval runner, moderation gate, citation tracker, replay
format, event bus, or agent selector, that code should come with a short
justification explaining why the matching CEMAF module was not used.

## Start From The Composition Root

The default shape of a CEMAF app is one executor plus one service bundle:

```python
from cemaf.bootstrap import create_executor
from cemaf.orchestration.executor import ExecutorConfig
from cemaf.orchestration.services import RuntimeServices

executor = create_executor(
    agent_registry=registry,
    services=RuntimeServices(
        event_bus=event_bus,
        run_logger=run_logger,
        budget_guard=budget_guard,
        context_compiler=context_compiler,
        token_budget=token_budget,
        llm_client=llm_client,
        vector_store=vector_store,
        memory_manager=memory_manager,
        moderation_pipeline=moderation_pipeline,
        online_eval_pipeline=online_eval_pipeline,
        quality_police=quality_police,
        agent_selector=agent_selector,
        council_aggregator=council_aggregator,
        interceptor_pipeline=interceptor_pipeline,
        blueprint_library=blueprint_library,
        blueprint_selector=blueprint_selector,
        auto_heal_manager=auto_heal_manager,
    ),
    config=ExecutorConfig(enable_events=True),
)
```

Absent services are off. Present services become part of the run lifecycle. That
is how CEMAF keeps deterministic nodes cheap while richer LLM nodes get the
budget, eval, memory, citation, safety, and provenance machinery they need.

## Module Checklist

Before inventing infrastructure, map the requirement to the CEMAF module that
already owns it:

| Requirement | Use CEMAF |
|---|---|
| Multi-step flow, branching, retries, node output propagation | `orchestration` (`DAG`, `Node`, `Edge`, `DAGExecutor`) |
| Request-scoped dependency injection | `RuntimeServices` |
| Agent discovery and typed goals/results | `agents`, `AgentRegistry` |
| Deterministic tools and reusable capabilities | `tools`, `skills`, `sandbox` |
| Prompt/context assembly under token limits | `context`, `ContextCompiler`, `TokenBudget` |
| Immutable state updates and auditability | `ContextPatch`, provenance metadata |
| Semantic/episodic/project/session memory | `memory`, `persistence`, `ingestion` |
| Retrieval and embeddings | `retrieval`, `vector_store`, `llm` embedding adapters |
| LLM provider access, exact token counting, resilience wrappers | `llm`, `resilience`, `cache` |
| Pre/post content safety and prompt-injection screening | `moderation`, `validation`, `interceptors` |
| Output quality checks and gates | `evals`, `GateEvalInterceptor`, `quality_police` |
| Citation membership and groundedness | `citation`, groundedness evaluators |
| Cost caps and operator visibility | `observability`, `BudgetGuard`, `RunLogger`, metrics |
| Run events and subscribers | `events` |
| Deterministic replay/debugging | `replay` |
| Concurrent context write coordination | `collision` |
| Council decisions and agent selection | `council`, auction `AgentSelector` |
| Learned reusable prompts/templates | `blueprint`, blueprint harvest, scoped promotion |
| Failure feedback and bounded self-healing | `iteration`, `improvement`, `AutoHealManager` |
| Operator/API/dashboard read model | `operator` session snapshots |
| MCP or external tool surfaces | `mcp`, `docs_api` |
| Large-context divide-and-conquer | `rlm` |
| State transitions independent of agents | `state` |

Use app code for domain concepts: business objects, product-specific agents,
product UI/API routes, tenant policy, database schemas, and deployment glue.

## Good Integration Shape

A good generated app usually has this structure:

1. Domain models: Pydantic goal/result types and product entities.
2. Protocol adapters: your LLM, vector store, DB-backed memory, policy, or
   tool implementations.
3. Agent/tool registration: `AgentRegistry`, `ToolRegistry`, and optional
   factories.
4. Services bundle: one `RuntimeServices(...)` at the composition root.
5. Declarative DAGs: `DAG` definitions for workflows.
6. Operator surface: events, run logs, replay, and session snapshots.
7. Integration tests: one test per cross-module path.

That structure lets the app customize behavior while CEMAF remains responsible
for the rails.

## Anti-Patterns To Avoid

Do not generate these unless the task explicitly requires a replacement:

- A custom `while agent_not_done` loop that bypasses `DAGExecutor`.
- A shared mutable dict as the system state layer.
- Prompt assembly by string concatenation when `ContextSource` and
  `ContextCompiler` can express the inputs.
- Per-feature budget counters instead of `BudgetGuard`.
- Per-feature callback logs instead of `EventBus` and `RunLogger`.
- A bespoke eval/moderation/citation pipeline hidden inside an agent.
- A new agent router when auction selection, council nodes, static refs, or a
  custom resolver can do the job.
- A reusable prompt library that ignores `BlueprintLibrary` and the harvest
  flywheel.

## Use The Docs API During Generation

CEMAF exposes its own docs as a queryable index for agents:

```bash
uv run cemaf docs search "composition root runtime services" -k 5
uv run cemaf docs search "agent auction council gate eval blueprint harvest" -k 8
uv run cemaf docs search "context compiler token budget provenance patch" -k 8
uv run cemaf docs search "moderation validation citation groundedness" -k 8
```

Tool-using agents can register the docs search tools:

```python
from cemaf.docs_api import build_default_index, CemafDocsSearchTool, DocsRetrievalTool

index = build_default_index()
tool_registry.register_instance(item=CemafDocsSearchTool(index=index))
tool_registry.register_instance(item=DocsRetrievalTool(index=index))
```

When uncertain, query the docs before coding. The search index covers
`docs/**/*.md`, package docstrings, module docstrings, and design-pattern
sections.

## Whole-Engine References

Use these before starting from a blank file:

- [../examples/release_engine.py](../examples/release_engine.py) - flagship
  whole-engine example: council, conditional steering, auction, gate/recovery,
  eval, blueprint harvest, provenance, and output reports.
- [../examples/composed_engine.py](../examples/composed_engine.py) - compact
  composition-root example with council, auction, eval, budget, events, context
  compiler, and harvest.
- [../tests/integration/test_composed_engine.py](../tests/integration/test_composed_engine.py) -
  integration proof for the composed engine.

The important lesson: CEMAF features are stations in one run lifecycle, not
separate utilities that the app remembers by hand.

## Pull-Request Checklist

For any app or integration built on CEMAF, include answers to these questions:

1. Which CEMAF modules are used for orchestration, context, memory, quality,
   safety, observability, and replay?
2. Which app-specific adapters implement CEMAF protocols?
3. What is wired through `RuntimeServices`?
4. What is intentionally left out because the product does not need it?
5. Which integration tests prove the full CEMAF path works?

The goal is not to turn every app into a maximal demo. The goal is to make each
omitted subsystem explicit, so omissions are design choices instead of accidental
rewrites.

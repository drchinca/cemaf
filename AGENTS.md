# Agent Instructions

## Project Shape

CEMAF is a protocol-first, multi-agent orchestration framework for context engineering. Keep the base framework domain-neutral and framework-agnostic. Every integration point should prefer a `@runtime_checkable` `Protocol`, structural typing, and injected dependencies over inheritance, globals, or hidden singletons.

The project has two layers:

- Layer 1: base framework primitives under `src/cemaf/`, including orchestration, agents, tools, context, memory, evals, moderation, events, resilience, observability, retrieval, and LLM integration.
- Layer 2: self-hosting consumers under `audit/`, `knowledge/`, and `meta/`. These may consume the base framework, but base modules must not import self-hosting modules.

Primary composition entry points:

- `cemaf.bootstrap.create_executor(agent_registry=..., services=..., config=...)`
- `cemaf.meta.bootstrap.create_meta_executor(...)`

## Development Rules

- Follow existing module boundaries and local patterns before adding abstractions.
- Keep CEMAF as substrate, not an application control plane. Generic file, shell, sandbox, skill, tool, and FSM primitives belong here; task-specific orchestration belongs outside the framework.
- Use `RuntimeServices` for cross-cutting dependencies. Do not introduce module-level service singletons.
- Prefer immutable value objects: frozen dataclasses, frozen Pydantic models, tuple collections, and context patches with provenance.
- Use `utc_now()` from `cemaf.core.utils` for timestamps.
- Use `NewType` IDs from `cemaf.core.types` for framework identifiers.
- Use `Result[T]` for expected success/failure paths in tools and evaluators.
- Keep docs and README examples live against current imports.

## Testing Discipline

Every meaningful feature needs three levels of evidence:

- Contract tests for protocols and interfaces.
- Unit tests for isolated module behavior.
- Integration tests for real cross-module wiring.

Unit tests alone are not enough when one module produces data another module consumes. Bridges, adapters, factories, resolver changes, and event subscribers need integration tests that run the real flow end to end.

Important integration patterns to preserve:

- `DAGExecutor.run(...)` with real `ContextNodeExecutor` wiring.
- Memory store to context compiler flow.
- EventBus subscribers receiving real events.
- Eval pipeline and QualityPolice reacting to executor events.
- Interceptor gates blocking downstream DAG nodes.
- Auction and council nodes resolved through the resolver chain.
- Blueprint harvest through EventBus into a searchable library.
- SQLite memory store round-trips and concurrent write behavior.

## Commands

Use the project's `uv` workflow:

```bash
uv sync --extra dev
make check
uv run pytest -q
uv run pytest --cov=src/cemaf --cov-report=term-missing:skip-covered --cov-fail-under=80 -q
uv run python examples/hello_world.py
uv run python examples/release_engine.py --dry-run
uv run python examples/release_engine.py --produce
uv run python benchmarks/run_benchmarks.py
```

`make check` is the pre-PR gate: Ruff, format check, strict MyPy, internal doc links, architecture graph drift, and trace-data drift.

## Documentation

When behavior changes, update the docs that claim it. Useful starting points:

- `README.md`
- `docs/README.md`
- `docs/architecture.md`
- `docs/patterns.md`
- `docs/modules.md`
- module-specific docs under `docs/`

Keep public claims tied to runnable examples, tests, or deterministic audit scripts.

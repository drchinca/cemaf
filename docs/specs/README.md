# CEMAF Specs

Specs are the primary artifact. Code, tests, and docs derive from them.

## Enterprise Context Brain — SPEC-00 program

The current spec program turns CEMAF into an **enterprise context brain**:
pull-not-push retrieval, Blueprints as LLM input, long-horizon task awareness,
shared Knowledge Graph, guardian mesh, online-eval halt, cite-or-fail grounding,
self-resolving DAG. Six child specs decompose under one umbrella.

| ID | Title | Depends on | Owns |
|---|---|---|---|
| [SPEC-00](SPEC-00-enterprise-context-brain.md) | Enterprise Context Brain (umbrella) | — | cross-cutting invariants, glossary, the interceptor seam |
| [SPEC-01](SPEC-01-node-interceptor-pipeline.md) | Node Interceptor Pipeline | SPEC-00 | the chain, decisions, recovery |
| [SPEC-02](SPEC-02-kg-and-datasource-services.md) | KG + DataSource RuntimeServices | SPEC-01 | pull-not-push, KG promotion, enterprise connector protocol |
| [SPEC-03](SPEC-03-blueprint-as-llm-input.md) | Blueprint as LLM Input | SPEC-01 | structured generation; Blueprint replaces English prompts |
| [SPEC-04](SPEC-04-task-state-machine.md) | Long-Horizon Task State Machine | SPEC-01 | TaskContext, pause/resume, prior decisions |
| [SPEC-05](SPEC-05-guardian-mesh.md) | Guardian Mesh | SPEC-01..04 | legitimacy, cite-or-fail, eval-halt, goal-completion, audit |
| [SPEC-06](SPEC-06-self-resolving-dag.md) | Self-Resolving DAG | SPEC-01, SPEC-05 | meta-agents invocable mid-run, bounded recursion |

## Implementation order

Specs depend in number order. PRs flat against `main`, one PR per spec — see
`rules/pr-templates.md` and `rules/git-workflow.md`.

## Standards

Each spec adheres to `rules/spec-driven.md`:

- §1 Context (with mermaid where flow is non-trivial)
- §2 Interface Contract (MDE) — typed protocols and dataclasses
- §3 Invariants (DbC) — EARS-style where naturally state-machine
- §4 Acceptance Criteria (BDD) — Gherkin scenarios
- §5 Out of Scope
- §6 Dependencies
- §7 Correctness Properties — numbered claims citing §3/§4
- §8 Eval Criteria — for any LLM behavior
- §9 Observability Contract — OTel GenAI spans, log events, metrics

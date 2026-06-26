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

## ECC-Informed Extensions (SPEC-11..14)

Additive capabilities ported from the ECC harness review (see
`docs/analysis/ECC_ENHANCEMENT_RESEARCH.md`). Each stands alone — not part of the
SPEC-00 umbrella — and ships backward-compatible.

| ID | Title | Owns |
|---|---|---|
| [SPEC-11](SPEC-11-context-security-classification.md) | Context Security Classification | `SecurityLevel` on `ContextPatch`; clearance-gated compilation |
| [SPEC-12](SPEC-12-agent-collision-avoidance.md) | Agent Collision Avoidance | TCAS-style coordination over concurrent `ContextPatch` writes |
| [SPEC-13](SPEC-13-scoped-blueprint-harvest.md) | Scoped Blueprint Harvest | per-project blueprint scoping + PROJECT→GLOBAL promotion |
| [SPEC-14](SPEC-14-session-snapshot-contract.md) | Operator Session Snapshot | `cemaf.session.v1` read-only run snapshot contract |
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

## Spec-source drift audits

Last verified 2026-06-12: **all 5 Implemented specs** reference every
class, factory, file path, and test by name. Zero drift across the
implemented surface.

```bash
# SPEC-01a — Interceptor Spine
for f in cemaf/interceptors/{types,protocols,pipeline,gate_eval}.py \
         cemaf/orchestration/results.py \
         tests/unit/interceptors/test_pipeline.py \
         tests/integration/test_interceptor_gate.py; do test -f "src/$f" || test -f "$f"; done
grep -nE "interceptor_pipeline" src/cemaf/orchestration/services.py

# SPEC-07 — Hub & Spoke Knowledge
grep -nE "^(class|def) (LocalSpokeCache|HubKnowledgeGraph|SpokeReadHubWriteKG|create_hub_spoke_kg)\b" \
  src/cemaf/knowledge/hub_spoke.py
grep -nE "enable_hub_spoke_kg" src/cemaf/meta/bootstrap.py
test -f tests/integration/test_hub_spoke_kg.py

# SPEC-08 — Failure-Feedback Loop
grep -rE "^class (AutoHealManager|IterationLoop|FailureSignal|FailureParser|PytestParser|IterationOutcome|IterationReport)\b" src/
test -f tests/integration/test_iteration_sandbox.py

# SPEC-09 — Auction Agent Selection
grep -nE "^class (Capability|Bid|BidContext|CapabilityAdvertiser|AgentSelector|DefaultAgentSelector)\b" \
  src/cemaf/agents/selection.py
test -f src/cemaf/orchestration/resolvers/auction.py
test -f tests/integration/test_agent_auction.py

# SPEC-10 — Agent Council
for f in cemaf/council/{types,protocols,aggregator,council}.py \
         cemaf/orchestration/resolvers/council.py \
         tests/integration/test_agent_council.py; do test -f "src/$f" || test -f "$f"; done
grep -nE "^class CouncilResolver\b" src/cemaf/orchestration/resolvers/council.py
grep -nE "council_aggregator" src/cemaf/orchestration/services.py
grep -nE "rounds: int" src/cemaf/council/types.py   # multi-round deliberation
```

All clean as of the date above. If a spec rename refactor lands,
re-run the matching greps and update the date here. Specs marked
`Reviewed` (00, 01, 02, 03, 04, 05, 06) are design docs without a
matching implementation surface — they're audited separately when
they transition to `Implemented`.

## Cross-doc link audit

Last verified 2026-06-12: **0 broken file links + 0 broken anchor
links across 83 markdown files** (`README.md`, all top-level
user-facing docs, and every `.md` under `docs/`).

Re-run any time with:

```bash
uv run python docs/architecture/scripts/check_doc_links.py
```

Exits non-zero on any broken link, so it's CI-wireable. Skips
external URLs (link rot for `https://...` is a different problem)
and ignores anything inside fenced code blocks or inline code spans
(so Python type annotations like `Agent[GoalT](ABC):` don't trigger
false positives).

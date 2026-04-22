# Add MetaSpecifier agent + self_spec DAG

## Why

CEMAF's self-hosting layer has agents for DAG design (MetaArchitect), code generation (MetaSynthesizer), trace analysis (MetaAuditor), and knowledge graph ops (MetaKnowledgeGraph). It has no agent that produces **structured specs**.

Without a MetaSpecifier, the self-evolution loop is code-first: agents propose DAGs and synthesize code directly, with no reviewable artifact between "idea" and "implementation." This is the exact anti-pattern the SDD rule forbids: no code without a spec.

The OpenSpec bridge (PR #86) gave CEMAF the tooling to write and validate spec proposals. MetaSpecifier is the agent that uses it, closing the first layer of the self-spec loop.

## What Changes

- **Add `cemaf.meta.specifier.MetaSpecifier`** — agent that takes a `SpecGoal(feature_description, change_id, capabilities)` and produces a `SpecResult(change_id, proposal, validation_report)`.
- **Add `cemaf.meta.specifier.ProposalDoc`** — typed Pydantic model of an OpenSpec change (proposal.md text, tasks.md text, per-capability spec deltas with typed requirements and scenarios).
- **Add `render_proposal(doc: ProposalDoc) -> Mapping[str, str]`** — pure-function markdown renderer producing the file map the OpenSpec workspace expects.
- **Add `create_self_spec_dag()`** in `cemaf.meta.dags` — pipeline: MetaSpecifier writes proposal → `openspec validate --strict` via bridge → MetaAuditor reads `ValidationReport` → emits `AuditEntry`. Closes the loop.
- **Register** MetaSpecifier + OpenSpec tools in `create_meta_executor()` when an `OpenSpecRuntime` + `OpenSpecWorkspace` are available in `RuntimeServices`.

## Impact

- **Affected specs**: `meta-specifier` (new)
- **Affected code**: `src/cemaf/meta/specifier.py` (new), `src/cemaf/meta/dags.py` (extend), `src/cemaf/meta/bootstrap.py` (extend), `src/cemaf/orchestration/services.py` (add two optional fields: `openspec_runtime`, `openspec_workspace`)
- **Not affected**: Base framework (one-way dependency preserved — meta imports from mcp.bridges.openspec, never the reverse)

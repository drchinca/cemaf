# SPEC-16 — Declarative engine manifest

> Status: Draft · Last-Reviewed: 2026-07-04 · Depends on: SPEC-00
> Owns: a single frozen Pydantic model that serialises an already-composable
> CEMAF engine, plus a loader that lowers it to the existing imperative
> `create_executor()` call. **No diff engine, no `plan`/`apply` daemon, no
> new registration surface.**

## 1. Context

CEMAF composition is imperative today:

- `cemaf.bootstrap.create_executor(agent_registry=, services=)` builds a
  `DAGExecutor` from Python objects.
- `cemaf.meta.bootstrap.create_meta_executor()` does the same with the
  self-hosting registry and audit + KG defaults wired.
- Examples (`examples/release_engine.py`, `examples/composed_engine.py`)
  are hand-wired composition roots.

That is fine for a library. It is not fine as the **only** way to boot a
CEMAF engine — three problems compound as the surface grows:

1. **Operators cannot see the engine shape** without reading Python. There
   is no artifact you can review, diff, or version-control alongside a
   deployment.
2. **Cross-repo callers duplicate wiring.** `cemaf-service` and any
   future runner each re-implement a bespoke composition root.
3. **The `meta/` self-hosting layer has no declarative form** — you cannot
   ask CEMAF "which meta-agents are active, and against which registry?"
   without importing them.

Substrates that ship declarative cluster manifests (see
`docs/analysis/GRAPH_BACKEND_SEAMS_FOR_CEMAF.md`) show the shape works:
one YAML/JSON artifact declares the runtime; a load step lowers it to
whatever the runtime needs. This spec adopts that **shape** without any
of the cluster-plane machinery — CEMAF is a library, not a control plane.

## 2. Interface Contract (MDE)

New module: `cemaf.config.manifest`.

```python
class ManifestSchemaVersion(StrEnum):
    V1 = "cemaf.engine.v1"

class AgentEntry(BaseModel):
    model_config = {"frozen": True}
    id: str
    factory: str                     # dotted path resolved via cemaf.config.registry
    goal_type: str                   # dotted path
    kwargs: JSON = Field(default_factory=dict)

class ToolEntry(BaseModel):
    model_config = {"frozen": True}
    id: str
    factory: str
    kwargs: JSON = Field(default_factory=dict)

class InterceptorEntry(BaseModel):
    model_config = {"frozen": True}
    factory: str                     # e.g. "cemaf.interceptors:GateEvalInterceptor"
    kwargs: JSON = Field(default_factory=dict)

class ServicesEntry(BaseModel):
    """Named refs into cemaf.config's provider registry.

    Every value is either 'absent' or a factory-dotted-path. The loader
    resolves each ref to the RuntimeServices field of the same name. No
    field names are invented here — they mirror RuntimeServices exactly.
    """
    model_config = {"frozen": True}
    llm_client: str | None = None
    memory_manager: str | None = None
    event_bus: str | None = None
    vector_store: str | None = None
    knowledge_graph: str | None = None
    interceptor_pipeline: str | None = None
    # ... other RuntimeServices fields follow

class EngineManifest(BaseModel):
    model_config = {"frozen": True}
    schema: ManifestSchemaVersion = ManifestSchemaVersion.V1
    agents: tuple[AgentEntry, ...] = ()
    tools: tuple[ToolEntry, ...] = ()
    interceptors: tuple[InterceptorEntry, ...] = ()
    services: ServicesEntry = ServicesEntry()
    metadata: JSON = Field(default_factory=dict)

def load_manifest(path: Path | str) -> DAGExecutor: ...
```

`load_manifest` lowers the manifest to `create_executor()`:

1. Reads YAML/JSON at `path`, validates against `EngineManifest`.
2. Resolves each factory dotted-path through `cemaf.config.registry`
   (existing module — no new registry).
3. Builds an `AgentRegistry` by calling each `AgentEntry.factory(**kwargs)`
   and registering the returned instance under `goal_type`.
4. Builds `RuntimeServices` by calling each factory named in `ServicesEntry`
   with no kwargs (services are cheap; no need for a second-order DSL).
5. Delegates to `create_executor(agent_registry=..., services=...)`.

Everything after step 5 is unchanged — the manifest is a **view** over
`create_executor`, not a parallel path.

## 3. Invariants (DbC)

1. `load_manifest` produces an executor **structurally identical** to a
   hand-wired call that supplied the same agents, tools, interceptors,
   and services. Behavioural parity is enforced by §10 parity tests.
2. `EngineManifest.schema` mismatch raises immediately — no auto-migration.
3. Unknown top-level keys in the source YAML/JSON raise (strict Pydantic).
   Unknown *nested* keys under `metadata` are tolerated.
4. `ServicesEntry` field names always mirror `RuntimeServices` field
   names verbatim. Adding a runtime service is a two-line change —
   `RuntimeServices` gets the field, `ServicesEntry` gets the same name.
5. No field of `EngineManifest` triggers side effects at parse time. All
   side effects (factory calls, registration) happen inside
   `load_manifest`.
6. A manifest never expresses more than one CEMAF engine. Multi-engine
   deployments compose multiple manifests at the caller.

## 4. Acceptance Criteria (BDD)

```gherkin
Feature: Engine manifest

  Scenario: A manifest boots the same executor as a hand-wired composition
    Given the composition in examples/release_engine.py
    And a manifest release_engine.yaml expressing the same agents/tools/services
    When load_manifest("release_engine.yaml") is called
    Then the resulting DAGExecutor has the same registered agent ids
    And the same registered tool ids
    And the same non-None fields in its RuntimeServices
    And running the same DAG through both produces the same NodeResult ids

  Scenario: Unknown top-level key raises at parse time
    Given a manifest with a top-level key not in EngineManifest
    When load_manifest is called
    Then a ValidationError is raised before any factory runs

  Scenario: Missing service ref means service is absent
    Given a manifest with services.event_bus omitted
    When load_manifest is called
    Then services.event_bus on the resulting executor is None
```

## 5. Out of scope

- **`plan` / `apply` UX.** No dry-run diff, no state ledger, no daemon.
- **Hot reload.** A manifest edits require a new `load_manifest` call.
- **Cluster / multi-node runtimes.** One manifest → one process → one
  executor. Multi-instance deployments layer above CEMAF.
- **Manifest linting or LSP.** A future skill / tool can add this; not
  part of the framework.
- **YAML-specific extensions.** The loader accepts JSON too — YAML is a
  format, not a contract.

## 6. Dependencies

- SPEC-00 — RuntimeServices field list is the source of truth for
  `ServicesEntry`.
- `cemaf.config.registry` — existing factory dotted-path registry;
  reused, not reinvented.
- `cemaf.bootstrap.create_executor` — the imperative composition root
  this manifest lowers to.

## 7. Correctness Properties

### Property 1: Lowering parity

*For any manifest `M` that passes validation, the executor returned by
`load_manifest(M)` is behaviourally identical to a hand-wired
`create_executor(agent_registry=R, services=S)` call where `R` and `S`
are the objects the loader constructs from `M`.*

**Validates: §3 Invariant 1, §4 Scenario "A manifest boots the same executor"**

### Property 2: Strict schema

*For any source document containing a top-level key not declared on
`EngineManifest`, `load_manifest` raises before invoking any factory.*

**Validates: §3 Invariant 3, §4 Scenario "Unknown top-level key raises"**

## 10. Test Coverage Update

- **L0**: Pydantic validation cases — schema mismatch, unknown top-level
  key, missing required fields on entries, malformed dotted paths.
- **L1**: loader dispatch — each factory in `AgentEntry` / `ToolEntry` /
  `InterceptorEntry` is resolved through the config registry, called
  exactly once, and the instance is registered under the correct id.
- **L2**: parity test between `examples/release_engine.py` and a
  `release_engine.yaml` expressing the same graph — same agent ids,
  tool ids, services set, same run outcome on a shared DAG.
- **e2e**: any consumer repo that adopts the manifest form (cemaf-service
  is the first candidate) runs its existing e2e suite against a
  manifest-loaded executor. This is a downstream-repo obligation; the
  framework just ships the loader.

## Non-obligation to implement

This spec is **shape-only**. Implementation follows once at least one
downstream consumer wants to boot from a manifest instead of a Python
composition root. The imperative `create_executor` path stays
first-class forever; the manifest is an additive lowering, not a
replacement.

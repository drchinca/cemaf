# Blueprint Triad

CEMAF's `Blueprint` is a **semantic prompt object** — a structured,
typed spec for how a piece of content should be generated (goal, style,
entities, policies). The **blueprint triad** turns it from a reference
type into a self-growing runtime asset:

1. **[BlueprintLibrary](#1-blueprintlibrary)** — curated, searchable
   catalog with three storage kinds (SNAPSHOT / FACTORY / RECIPE).
   Developer-authored (BYO).
2. **[BlueprintSelectorHook](#2-blueprintselectorhook)** — runtime
   retrieval wired into `ContextNodeExecutor`; every context-compiled
   agent call pulls the best-matching blueprint's prompt into compiled
   context automatically.
3. **[BlueprintHarvesterEngine](#3-blueprintharvesterengine)** —
   autonomous write path. Subscribes to `EVAL_COMPLETED`, turns
   high-quality runs into RECIPE entries, appends to a writable source
   so they show up in future selector queries.

One library grows with experience while remaining fully authorable by
humans — the BYO catalog and the harvested entries coexist in the same
index, same `search()`, same protocol surface.

> **Protocol surface > adapter count.** Every decision in the triad —
> "what's harvestable", "how to correlate", "how to derive a blueprint",
> "where do blueprints live" — is a `@runtime_checkable` Protocol.
> Bundled defaults are opt-in, not the only way.

---

## 1. `BlueprintLibrary`

A searchable index of `BlueprintEntry` records. Each entry carries one
of three storage representations that all resolve to the same
`Blueprint` type — consumers are agnostic to how an entry was stored.

| Kind       | Payload                     | Optimizes for          |
|------------|-----------------------------|------------------------|
| `SNAPSHOT` | serialized `Blueprint` dict | **Fidelity**           |
| `FACTORY`  | `pkg.module:function`       | **Liveness**           |
| `RECIPE`   | declarative dict            | **Authorability**      |

### Usage

```python
from cemaf.blueprint import (
    BlueprintEntry,
    BlueprintLibrary,
    Blueprint,
    SceneGoal,
)

library = BlueprintLibrary()

# (a) SNAPSHOT — capture a Blueprint you built in Python
bp = Blueprint(id="announce", name="Announcement", scene_goal=SceneGoal(objective="Announce X"))
library.register(entry=BlueprintEntry.snapshot_entry(
    id="content/announce",
    title="Announcement",
    blueprint=bp,
    tags=("content",),
))

# (b) FACTORY — point at an importable zero-arg callable
library.register(entry=BlueprintEntry.factory_entry(
    id="content/release-notes",
    title="Release Notes",
    factory_ref="mypkg.blueprints:release_notes",
))

# (c) RECIPE — declarative dict (YAML/JSON authorable)
library.register(entry=BlueprintEntry.recipe_entry(
    id="content/faq",
    title="FAQ",
    recipe={
        "name": "FAQ",
        "goal": {"objective": "Produce an FAQ", "priority": 2},
        "style": {"tone": "helpful", "format": "markdown"},
    },
))

# Resolution is uniform — you don't care how it was stored.
blueprint = library.resolve(entry_id="content/faq")
prompt = blueprint.to_prompt()

# Search with weighted-overlap scoring (title ×3, tags ×2, description ×1).
hits = library.search(query="product announcement", k=3)
```

### Pluggable sources

`BlueprintLibrary` ingests entries from any `BlueprintSource`. Two read-only
sources ship out of the box:

- **`InMemoryBlueprintSource`** — hand-authored tuple (tests, bootstrap).
- **`JSONFileBlueprintSource`** — a single `blueprints/catalog.json` file.

Plus one **writable** source (see below):

- **`SqliteBlueprintSource`** — persistent catalog at a SQLite file.
  Idempotent upsert via `INSERT OR REPLACE`. Survives restarts.

### Writable seam

`WritableBlueprintSource` is a **sibling** protocol of `BlueprintSource`
— *not* a subclass. Read-only implementations remain valid
`BlueprintSource`s; callers that need write access type against
`WritableBlueprintSource` explicitly.

```python
@runtime_checkable
class WritableBlueprintSource(Protocol):
    @property
    def name(self) -> str: ...
    def load(self) -> Iterable[BlueprintEntry]: ...
    async def append(self, *, entry: BlueprintEntry) -> None: ...
    async def close(self) -> None: ...
```

`BlueprintLibrary.register_async(entry=..., overwrite=...)` is the
`asyncio.Lock`-guarded write path for runtime writers (harvesters, HTTP
endpoints). Sync `register` stays for boot-time wiring.

### Design notes

- **Entry vs. Blueprint**: the library holds *entries*, not live
  `Blueprint` objects. Resolution is lazy — callers cache the returned
  `Blueprint` themselves.
- **Id collisions** raise `BlueprintIdCollision` by default;
  `overwrite=True` to replace.
- **Malformed entries** raise at the right layer: `BlueprintLibraryError`
  at construction (payload/kind mismatch, empty id); `BlueprintResolutionError`
  at `resolve()` (bad import path, recipe missing required fields,
  snapshot fails Pydantic validation).
- **Recipe ↔ snapshot compatibility**: the recipe parser accepts both
  short-form keys (`goal`, `style`) and long-form (`scene_goal`,
  `style_guide`). `Blueprint.to_dict()` output is itself a valid
  recipe, so SNAPSHOT ⇄ RECIPE migration is free.

---

## 2. `BlueprintSelectorHook`

Before every context-compiled agent call, the executor can consult a
selector hook that returns a rendered blueprint prompt (or empty string
on no-match). The hook is a narrow Protocol — `ContextNodeExecutor`
imports **only** the hook, not any blueprint type:

```python
@runtime_checkable
class BlueprintSelectorHook(Protocol):
    async def select(self, *, query: str) -> str: ...
```

### Default adapter

`LibraryBlueprintSelectorHook` wraps a `BlueprintLibrary`:

```python
from cemaf.blueprint import BlueprintLibrary
from cemaf.meta.blueprint_selector import LibraryBlueprintSelectorHook

library = BlueprintLibrary(entries=(...))
hook = LibraryBlueprintSelectorHook(library=library)
```

### Wiring

Pass the hook into `ContextNodeExecutor` (or via `RuntimeServices.blueprint_selector`
through `create_executor`):

```python
from cemaf.orchestration.context_node_executor import ContextNodeExecutor

executor = ContextNodeExecutor(
    agent_registry=registry,
    context_compiler=compiler,
    token_budget=budget,
    blueprint_selector=hook,  # <— enables retrieval
)
```

When set, every node's `_compile_context` derives a search query from
well-known goal fields (`objective`, `goal`, `description`, `task`,
`query`, `feature_description`) and prepends the top match's prompt as
the **highest-priority artifact** under key `blueprint:selected`. Under
token-budget truncation, the blueprint survives while lower-priority
inputs may be dropped — correct failure mode for RAG-style systems.

### Contract

- **Empty query → no preamble.** If inputs lack any goal-like field,
  the selector returns `""` and nothing is injected. Deliberate:
  matching on the agent name alone produces false positives (every
  `Writer` node getting any blueprint tagged "writer").
- **Selector failures are non-fatal.** An exception from the hook is
  logged as a `blueprint_select` warning and the node proceeds without
  a preamble.
- **Zero overhead when off.** `blueprint_selector=None` → the compile
  path is byte-identical to the no-hook baseline.

### Agent form (optional)

`BlueprintSelectorAgent` is a standard `Agent[SelectionGoal, SelectionResult]`
for when you want retrieval as an explicit DAG node rather than a
per-node side effect. Registered by `register_blueprint_selector` under
`SelectionGoal`.

---

## 3. `BlueprintHarvesterEngine`

The autonomous write path. The engine is **pure orchestration with zero
hardcoded judgment** — every decision is a pluggable Protocol.

```
         policy.should_harvest(event) ────────── True/False
                        │
                        ▼ (True)
         correlator.lookup(run_id, node_id) ──── HarvestContext
                        │
                        ▼
         distiller.distill(event, context) ──── BlueprintEntry | None
                        │
                        ▼ (non-None)
         writable_source.append(entry)
         library.register_async(entry, overwrite=True)
```

### The three decision protocols

```python
@runtime_checkable
class HarvestPolicy(Protocol):
    """Is this run good enough to harvest?"""
    def should_harvest(self, *, event: Event) -> bool: ...

@runtime_checkable
class RunCorrelator(Protocol):
    """What do we know about this run?"""
    async def observe(self, *, event: Event) -> None: ...
    async def lookup(self, *, run_id: str, node_id: str) -> HarvestContext | None: ...

@runtime_checkable
class BlueprintDistiller(Protocol):
    """What blueprint does this run yield?"""
    async def distill(
        self, *, event: Event, context: HarvestContext,
    ) -> BlueprintEntry | None: ...
```

### Bundled defaults

Opt-in in `cemaf.meta.harvest_defaults`:

- **`ScoreThresholdHarvestPolicy(threshold=0.8)`** — harvests when
  `overall_score >= threshold` and `overall_passed` is truthy. Guards
  against aggressive misconfiguration via `min_threshold`.
- **`InMemoryRunCorrelator(ttl_seconds=600, max_entries=10_000)`** —
  watches `TASK_STARTED` (goal) + `TASK_COMPLETED` (output), indexed by
  `(run_id, node_id)`. TTL + LRU eviction.
- **`RecipeBlueprintDistiller`** — builds a RECIPE-kind entry with
  content-addressed id (`harvest/{sha256(goal_text)[:12]}`). Repeated
  harvests of the same goal upsert a single entry, not duplicates.

### Correlation contract + race handling

`InMemoryRunCorrelator.lookup` requires **both** `goal_text` and
`output_text`. Half-populated contexts return `None`. This pushes race
handling up to the engine, which:

- **Retries `lookup` up to `correlation_retry_attempts=3` times** with
  `correlation_retry_delay_s=0.05` between attempts (both configurable;
  `ValueError` on negatives).
- **Logs `WARNING`** on final miss with a cause hint so operators can
  diagnose silent drops (usually: subscription-order race between
  `OnlineEvalPipeline` and the correlator on the same `TASK_COMPLETED`
  event).

### Usage

```python
from cemaf.blueprint import (
    BlueprintHarvesterEngine,
    BlueprintLibrary,
)
from cemaf.blueprint.sqlite_source import SqliteBlueprintSource
from cemaf.meta.harvest_defaults import (
    InMemoryRunCorrelator,
    RecipeBlueprintDistiller,
    ScoreThresholdHarvestPolicy,
)

source = SqliteBlueprintSource(db_path="blueprints.db")
library = BlueprintLibrary()
library.register_from(sources=(source,))  # hydrate from disk

engine = BlueprintHarvesterEngine(
    writable_source=source,
    library=library,
    policy=ScoreThresholdHarvestPolicy(threshold=0.85),
    correlator=InMemoryRunCorrelator(),
    distiller=RecipeBlueprintDistiller(source_name="my-app"),
)
engine.subscribe(event_bus=bus)
# ... app runs ...
engine.unsubscribe()
await source.close()
```

### TASK_STARTED emission

`DAGExecutor._try_once` now emits `EventType.TASK_STARTED` before each
node's `execute_node` call with payload:

```python
{
    "node_id": str,
    "node_type": str,
    "agent_id": str,        # node.ref_id
    "inputs": dict,         # resolved_inputs
    "goal_text": str,       # derived via well-known goal fields
}
```

Correlators that observe this event can capture goal text before
`TASK_COMPLETED` provides output. Purely additive — no existing
consumer was affected.

### BYO any protocol

Swap any of the three decisions:

```python
class MyPolicy:
    def should_harvest(self, *, event):
        # custom logic — remote-service call, multiple-metric check, etc.
        return ...

class MyDistiller:
    async def distill(self, *, event, context):
        # LLM-based distillation, domain-specific recipe shape, etc.
        return ...

engine = BlueprintHarvesterEngine(
    writable_source=my_source,
    policy=MyPolicy(),
    correlator=InMemoryRunCorrelator(),  # or your own
    distiller=MyDistiller(),
)
```

---

## Self-hosting composition root

`meta.bootstrap.create_meta_executor` wires the triad when enabled:

```python
from cemaf.orchestration.services import RuntimeServices
from cemaf.meta.bootstrap import MetaServices, create_meta_executor
from cemaf.meta.blueprint_selector import LibraryBlueprintSelectorHook

library = BlueprintLibrary()
library.register_from(sources=(source,))
selector = LibraryBlueprintSelectorHook(library=library)

services = RuntimeServices(
    event_bus=bus,
    blueprint_library=library,
    blueprint_selector=selector,
    # ...
)
meta_services = MetaServices(
    enable_blueprint_harvester=True,
    writable_blueprint_source=source,
    blueprint_harvest_threshold=0.8,
    # Optional: override any of the three decision protocols
    # harvest_policy=MyPolicy(),
    # harvest_correlator=MyCorrelator(),
    # harvest_distiller=MyDistiller(),
)

executor = create_meta_executor(
    agent_registry=registry,
    services=services,
    meta_services=meta_services,
)
```

All fields default to `None` / `False` — when none are set, runtime
behavior is byte-identical to the pre-triad baseline.

---

## Catalog format (JSON)

For `JSONFileBlueprintSource`:

```json
[
  {
    "id": "content/announce",
    "kind": "snapshot",
    "title": "Announcement",
    "tags": ["content"],
    "snapshot": { "id": "announce", "name": "Announcement", "scene_goal": {"objective": "..."} }
  },
  {
    "id": "content/release-notes",
    "kind": "factory",
    "title": "Release Notes",
    "factory_ref": "mypkg.blueprints:release_notes"
  },
  {
    "id": "content/faq",
    "kind": "recipe",
    "title": "FAQ",
    "recipe": { "name": "FAQ", "goal": "Produce an FAQ" }
  }
]
```

## Env configuration

```bash
# Registry-backed source selection: json_file, sqlite, memory, or registered custom backend.
export CEMAF_BLUEPRINT_SOURCE_BACKEND=json_file
export CEMAF_BLUEPRINT_SOURCE_PATH=/path/to/blueprints.json

# Legacy shortcut, still supported when CEMAF_BLUEPRINT_SOURCE_BACKEND is unset.
export CEMAF_BLUEPRINT_CATALOG=/path/to/blueprints.json
```

```python
from cemaf.blueprint.factories import (
    blueprint_source_registry,
    create_blueprint_library_from_env,
    create_blueprint_source,
)

library = create_blueprint_library_from_env()

# Direct factory use.
source = create_blueprint_source("sqlite", db_path="blueprints.db")

# Custom source backends plug into env and factory construction.
blueprint_source_registry.register(
    backend="opensearch",
    factory=lambda **kwargs: OpenSearchBlueprintSource(index=kwargs["index"]),
)
```

## CLI

```bash
cemaf blueprint list                     # list entries
cemaf blueprint search "product launch"  # keyword search
cemaf blueprint show content/announce    # resolve and render prompt
```

---

## What's not in the triad

Explicit non-goals:

- **New LLM / vector-store adapters** — the triad is protocol surface,
  not adapter breadth. Existing CEMAF LLM adapters (Anthropic, OpenAI,
  Gemini, etc.) are reused unchanged.
- **Multi-tenancy** — single-tenant by design.
- **LLM-based recipe distillation** — `RecipeBlueprintDistiller` is
  template-based. LLM-powered distillers are legitimate
  `BlueprintDistiller` implementations; ship your own when you need
  them.

### Known follow-ups (not yet landed)

- **Harvester teardown in `create_meta_executor`** — engine is
  subscribed in the composition root but there's no dispose hook on the
  returned executor. Callers with their own lifespan (like
  `cemaf-service`) wire subscription manually.
- **Multi-replica library staleness** — library hydrates once per
  process. Harvests from replica A don't appear in replica B until
  restart. Fine for single-process; needs a refresh strategy for
  horizontal scale.
- **`HarvestTelemetry` protocol** — `on_outcome: Callable` is a raw
  callable today. A typed protocol is planned for production
  observability sinks.
- **Catalog retention policy** — `SqliteBlueprintSource` grows
  unbounded. `RetentionPolicy` protocol is planned.

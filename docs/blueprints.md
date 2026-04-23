# Blueprint Library

CEMAF's `Blueprint` is a **semantic prompt object** — a structured,
typed spec for HOW a piece of content should be generated (goal, style,
entities, policies). The `BlueprintLibrary` is the curated, searchable
index over reusable `Blueprint`s so your agents, humans, and MCP clients
can discover and materialize them without knowing where the definition
lives.

## Three kinds of entries, one resolved type

A `BlueprintEntry` can be stored in three representations. All three
resolve to the same `Blueprint` type, so downstream code is agnostic.

| Kind       | Payload                     | When to use                                                                        |
|------------|----------------------------|------------------------------------------------------------------------------------|
| `SNAPSHOT` | serialized `Blueprint` dict | Faithful replay. Immune to registry drift. Frozen at capture time.                 |
| `FACTORY`  | `pkg.module:function`       | Always current. Contributors ship Python. Best when a blueprint needs live inputs. |
| `RECIPE`   | declarative dict            | Contributor-friendly, YAML/JSON-authorable, language-agnostic.                     |

Three representations exist because each optimizes for a different cost:
**fidelity** (SNAPSHOT), **liveness** (FACTORY), **authorability**
(RECIPE). Pick per entry, not per library. They coexist.

## Usage

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
        "goal": {
            "objective": "Produce an FAQ",
            "success_criteria": ["Covers top 5 questions"],
            "priority": 2,
        },
        "style": {"tone": "helpful", "format": "markdown"},
    },
))

# Resolution is uniform — you don't care how it was stored.
blueprint = library.resolve(entry_id="content/faq")
prompt = blueprint.to_prompt()
```

## Pluggable sources

`BlueprintLibrary` ingests entries from any `BlueprintSource`. Ship two
out of the box:

- `InMemoryBlueprintSource` — hand-authored tuple (tests, bootstrap).
- `JSONFileBlueprintSource` — a single `blueprints/catalog.json` file.

Bring your own source for databases, git-tracked registries, or HTTP
catalogs — the protocol is one method, `load() -> Iterable[BlueprintEntry]`.

## Catalog format (JSON)

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
export CEMAF_BLUEPRINT_CATALOG=/path/to/blueprints/catalog.json
```

```python
from cemaf.blueprint.factories import create_blueprint_library_from_env
library = create_blueprint_library_from_env()
```

## CLI

```bash
cemaf blueprint list                     # list entries
cemaf blueprint search "product launch"  # keyword search
cemaf blueprint show content/announce    # resolve and render prompt
```

## Design notes

- **Entry vs. Blueprint**: the library holds *entries*, not live
  `Blueprint` objects. Resolution is lazy — `resolve(entry_id)`
  materializes a `Blueprint` on demand. Callers that need caching
  cache the returned `Blueprint` themselves; the library stays
  stateless.
- **Id collisions** raise `BlueprintIdCollision` by default. Pass
  `overwrite=True` when you genuinely want to replace.
- **Malformed entries** raise at the right layer: `BlueprintLibraryError`
  at construction time (payload/kind mismatch, empty id), and
  `BlueprintResolutionError` at `resolve()` (bad import path, recipe
  missing required fields, snapshot fails Pydantic validation).
- **Recipe ↔ snapshot compatibility**: the recipe parser accepts both
  short-form keys (`goal`, `style`) and long-form keys (`scene_goal`,
  `style_guide`). This means `Blueprint.to_dict()` output is itself a
  valid recipe, so you can freely migrate between SNAPSHOT and RECIPE
  without a conversion tool.

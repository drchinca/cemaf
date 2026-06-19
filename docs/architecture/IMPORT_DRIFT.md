# Doc Import Drift — Backlog

`docs/architecture/scripts/check_doc_imports.py` runs every `from cemaf...`
import statement found inside fenced Python blocks across user-facing markdown
and reports what fails. As of 2026-06-19 it finds **74 broken imports across
18 files**.

This file lists them. The script is **not yet wired into CI** (it would
hard-fail every PR until the backlog is cleared). Wire it in once the count
hits zero, or as a warning-only check before that.

Re-run any time:

```bash
uv run python docs/architecture/scripts/check_doc_imports.py
```

## Failures by error category

### Modules that no longer exist (38 imports)

These docs reference whole packages that have been removed or renamed since
they were written. Fixing means either (a) deleting the doc if the feature
is gone, (b) pointing at the surviving primitive, or (c) reviving the
package as part of a real spec.

| Missing module | Imports | Doc(s) |
|---|---|---|
| `cemaf.sync` | 11 | `docs/sync.md` (×11), `docs/offline.md` (×1) |
| `cemaf.offline` | 11 | `docs/offline.md` (×9), `docs/throttling.md` (×2) |
| `cemaf.throttling` | 10 | `docs/throttling.md` (×8), `docs/offline.md` (×1), `docs/standalone_usage.md` (×1) |
| `cemaf.context.compression` | 6 | `docs/context_algorithms.md` (×6) |
| `cemaf.context.protocols` | 4 | `docs/protocol_guide.md` (×1), `docs/standalone_usage.md` (×1), `docs/extension_patterns.md` (×2) |
| `cemaf.context.kv_cache` | 4 | `docs/context_algorithms.md` (×4) |
| `cemaf.context.prefix` | 2 | `docs/context_algorithms.md` (×2) |
| `cemaf.orchestration.health` | 1 | `docs/orchestration.md` |
| `cemaf.llm.mock_client` | 1 | `docs/context.md` |
| `cemaf.llm.local` | 1 | `docs/llm.md` |

The `cemaf.sync` / `cemaf.offline` / `cemaf.throttling` clusters are large
enough that their docs are probably aspirational ports of an older design.
Audit these first.

### Renamed / removed names within real modules (~36 imports)

The package exists but the imported name is gone. Mostly small renames.
Sample (not exhaustive — re-run the script for the full list):

- `from cemaf.moderation.rules import ToxicityRule` (×3) — `ToxicityRule`
  isn't in the module today.
- `from cemaf.moderation.rules import ComplianceRule` — same.
- `from cemaf.agents.registry import AGENT_TOOLKIT` (×2) — `AGENT_TOOLKIT`
  isn't exported.
- `from cemaf.blueprint import OutputContract, DataContract` — names gone.
- `from cemaf.blueprint import ExecutionPolicy`, `SecurityPolicy` — gone.
- `from cemaf.blueprint import create_content_blueprint, create_analysis_blueprint`
  — factory functions gone.
- `from cemaf.retrieval import MockEmbeddingProvider` — gone.
- `from cemaf.memory import InMemoryMemoryStore` — current name is
  `InMemoryStore`.
- `from cemaf.evals.semantic import SemanticEvaluator` — gone.
- `from cemaf.evals.llm_judge import LLMJudge` — gone (the class name has
  changed; check `cemaf.evals.hierarchy`).
- `from cemaf.llm.protocols import LLMResponse` — gone.
- `from cemaf.config.protocols import EnvConfigSource, DictConfigSource` —
  gone.
- `from cemaf.context.compiler import MyCustomCompiler` — placeholder name
  the script catches; the doc should rename or annotate it as illustrative.
- `from cemaf.ingestion import TaskDistillationAdapter` — gone.

## Failures by file (counts)

```
13  docs/context_algorithms.md
12  docs/sync.md
10  docs/throttling.md
10  docs/offline.md
 4  docs/moderation.md
 4  docs/ingestion.md
 4  docs/blueprint.md
 3  docs/extension_patterns.md
 2  docs/standalone_usage.md
 2  docs/protocol_guide.md
 2  docs/evals.md
 2  docs/context_engineering_agents.md
 1  docs/rlm.md
 1  docs/retrieval.md
 1  docs/orchestration.md
 1  docs/mcp.md
 1  docs/context.md
 1  docs/config.md
```

## Suggested triage order

1. **`docs/sync.md`, `docs/offline.md`, `docs/throttling.md`** (33 of 74
   failures). Most likely candidates for outright deletion or "Status:
   aspirational" frontmatter — the underlying packages don't exist.
2. **`docs/context_algorithms.md`** (13 failures, 12 of them in the dead
   `cemaf.context.compression` / `kv_cache` / `prefix` submodules). Same
   call.
3. **Smaller name-rename PRs** for the rest — one doc per PR, fix the
   imports against the live source, run the script to confirm zero.

## Adding to CI

Once the count hits zero, append to `.github/workflows/ci.yml` under the
`docs:` job:

```yaml
- name: Verify documented imports actually resolve
  run: uv run python docs/architecture/scripts/check_doc_imports.py
```

Until then leave it manual to avoid blocking unrelated PRs.

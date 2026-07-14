# Graph Backend Seams For CEMAF

Graph databases are useful to study because they solve durable graph state:
typed nodes and edges, graph traversal, hybrid retrieval, branches, commits,
merges, policy-gated writes, and operator-facing deployment surfaces. CEMAF
should not reimplement that substrate. CEMAF should expose small protocol seams
that let a graph backend provide durable state while CEMAF remains the
execution, context, eval, and runtime-services framework.

## Boundary

CEMAF owns:

- DAG execution, agent/tool dispatch, retries, recovery, and event emission.
- `Context`, `ContextPatch`, token-budgeted context compilation, replay, and
  provenance.
- Protocol-first runtime composition through `RuntimeServices`.
- Eval, moderation, citation, budget, collision, and operator snapshots.
- The abstract `KnowledgeGraph`, retrieval, memory, and data-source contracts.

Graph backends own:

- Physical graph storage, schema enforcement, branch storage, commit history,
  merge algorithms, indexes, compaction, and time travel.
- Query languages and query planners.
- Object-store layout, server boot, cluster convergence, and backend policy
  enforcement.

The rule is: compose graph databases through CEMAF protocols; do not build a
second graph database inside CEMAF.

## Worth Borrowing

1. **Branch-per-agent/task memory.** Agents should be able to isolate durable
   KG writes, review a diff, then merge through a backend-owned workflow.
   CEMAF now exposes this as the optional `BranchingKnowledgeGraph` protocol.

2. **Backend capability discovery.** Some graph stores support branches,
   snapshots, hybrid retrieval, or server-side policy. CEMAF now exposes
   `KnowledgeGraphCapabilitiesProvider` so adapters can report these facts
   without expanding the base `KnowledgeGraph` protocol.

3. **Logical state over derived state.** The durable graph or memory store is
   the source of truth. Embeddings, ANN indexes, full-text indexes, spoke
   caches, and retrieval rankings are derived state: useful, rebuildable, and
   not a reason for CEMAF to reject a logical operation.

4. **Hybrid retrieval as a pull concern.** Graph traversal, vector search,
   text search, memory recall, and external data sources should converge in the
   SPEC-02 pull pipeline and surface citeable chunks in `ctx.surfaced_sources`.

## Not Worth Borrowing Now

- A CEMAF graph query language.
- A CEMAF graph storage engine.
- A CEMAF commit DAG or branch storage format.
- A cluster control plane with plan/apply/state ledgers.
- A backend-specific policy language clone.
- Inline graph-database dependencies in the orchestration core.

Those belong in adapters or downstream deployments until repeated CEMAF users
need a stable framework-level abstraction.

## Adapter Shape

A graph database adapter should implement the smallest useful set:

```python
from cemaf.knowledge import (
    BranchingKnowledgeGraph,
    KnowledgeGraph,
    KnowledgeGraphCapabilities,
    KnowledgeGraphCapabilitiesProvider,
)


class MyGraphBackend(
    KnowledgeGraph,
    BranchingKnowledgeGraph,
    KnowledgeGraphCapabilitiesProvider,
):
    @property
    def capabilities(self) -> KnowledgeGraphCapabilities:
        return KnowledgeGraphCapabilities(
            branching=True,
            snapshots=True,
            hybrid_retrieval=True,
            server_side_policy=True,
        )
```

Then wire it through:

```python
from cemaf.orchestration.services import RuntimeServices

services = RuntimeServices(knowledge_graph=my_graph_backend)
```

Agents receive the adapter on `AgentContext`:

```python
async def run(self, goal, context):
    if context.knowledge_graph is not None:
        await context.knowledge_graph.add_entity(...)
```

No app-level orchestration loop should be required.

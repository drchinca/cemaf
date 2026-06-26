"""Bridge a CEMAF KnowledgeGraph into a synchronous dependency-distance function (SPEC-12).

``collision_risk`` takes a *sync* ``dep_distance(path_a, path_b) -> hops`` so the risk math
stays pure and clock-free. A ``KnowledgeGraph`` is *async*. This module bridges the two:
``build_kg_dep_distance`` walks the graph once (async, up to ``max_depth`` hops) over the
entities an agent cohort intends to write, snapshots the pairwise hop counts, and returns a
plain sync callable suitable to pass straight into ``collision_risk`` /
``TcasCollisionPolicy(dep_distance=...)``.

Snapshotting (rather than querying per-pair lazily) keeps the risk computation deterministic
and side-effect-free for a given cohort, and bounds KG traffic to one BFS per source entity.
"""

from collections.abc import Callable, Iterable

from cemaf.knowledge.protocols import KnowledgeGraph

INF = float("inf")


async def build_kg_dep_distance(
    *,
    knowledge_graph: KnowledgeGraph,
    entity_ids: Iterable[str],
    max_depth: int = 6,
) -> Callable[[str, str], float]:
    """Snapshot pairwise dependency hop-counts over a KnowledgeGraph into a sync distance fn.

    For each entity id in the cohort, walk the graph (BFS up to ``max_depth``) and record the
    hop distance to every other reachable cohort entity. The returned callable looks the pair
    up in the snapshot: a direct edge → 1.0, N hops → N.0, unreachable / unknown → +inf.
    """
    if max_depth < 1:
        raise ValueError("max_depth must be >= 1")
    ids = list(dict.fromkeys(entity_ids))  # de-dupe, preserve order
    id_set = set(ids)
    distances: dict[tuple[str, str], float] = {}

    for source in ids:
        # query_neighbors collects everything reachable within depth; we then read back the
        # per-target hop count. KGQueryResult exposes entities + relations; we reconstruct hops
        # by expanding one depth at a time so the count is exact (not just "reachable").
        frontier = {source}
        seen = {source}
        for hop in range(1, max_depth + 1):
            next_frontier: set[str] = set()
            for node in frontier:
                result = await knowledge_graph.query_neighbors(entity_id=node, depth=1)
                for entity in result.entities:
                    if entity.id in seen:
                        continue
                    seen.add(entity.id)
                    next_frontier.add(entity.id)
                    if entity.id in id_set:
                        distances[(source, entity.id)] = float(hop)
            if not next_frontier:
                break
            frontier = next_frontier

    def dep_distance(path_a: str, path_b: str) -> float:
        """Sync dependency distance from the snapshot — direct edge 1.0, unreachable +inf."""
        if path_a == path_b:
            return INF  # same node is the overlap channel's job, not dependency
        return distances.get((path_a, path_b), INF)

    return dep_distance
